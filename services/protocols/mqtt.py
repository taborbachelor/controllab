"""MQTT telemetry publishing (completing the master specification, item 8).

Stdlib only, like the Modbus server, and for the same reason: the subset a
telemetry publisher needs is small. The condition for hand-rolling a
protocol is proving it interoperates, so tests/integration/test_mqtt_broker.py
runs this client against a real Mosquitto broker (a Docker container, in CI
too) and reads the result back with Mosquitto's own `mosquitto_sub`.

Implements MQTT 3.1.1 (OASIS standard, 2014), the client side of:

    CONNECT / CONNACK     clean session, keep-alive, a last will, username/password
    PUBLISH               QoS 0, retained or not (the publisher never needs more)
    SUBSCRIBE / SUBACK    QoS 0, for the tests and for anyone reading the telemetry back
    PINGREQ / PINGRESP    the keep-alive
    DISCONNECT

Nothing else: no QoS 1/2 (telemetry is state, and the next sample supersedes
a lost one; the retained copy covers a late subscriber), no TLS (a broker on
the same host or behind one that terminates it), no MQTT 5.

Two layers, each testable on its own:

- **Packet functions** -- pure, bytes in and bytes out (encode_*, the
  remaining-length varint, read_packet() over any stream).
- **MqttClient** -- a blocking socket client. **TelemetryPublisher** turns
  the dashboard's snapshot (the same one the browser polls) into topics, by
  exception: a tag is published when it changes by more than its deadband,
  the controller state when any of it changes, and every event once.

Topics, under a prefix (default `controllab/line1`):

    <prefix>/status          "online" / "offline" (retained; "offline" is the last will)
    <prefix>/tags/<TAG>      {"value": ..., "t": ...} (retained), one per I/O tag
    <prefix>/state           {"state", "line_mode", "fault_reason", "alarms", ...} (retained)
    <prefix>/events          one JSON event per message, as the event log records it

Telemetry only: nothing subscribes to commands. Operating the line stays on
the HMI paths (the dashboard, the Modbus HMI registers, OPC UA methods).
"""
from __future__ import annotations

import json
import socket
import struct
import threading
import time
from collections.abc import Callable

CONNECT, CONNACK, PUBLISH, SUBSCRIBE, SUBACK, PINGREQ, PINGRESP, DISCONNECT = 1, 2, 3, 8, 9, 12, 13, 14

CONNACK_CODES = {
    1: "unacceptable protocol version",
    2: "client identifier rejected",
    3: "server unavailable",
    4: "bad user name or password",
    5: "not authorized",
}


class MqttError(Exception):
    """A protocol error or a refused connection."""


# ---- packets -----------------------------------------------------------------------------


def encode_remaining_length(n: int) -> bytes:
    """MQTT's variable-length integer (§2.2.3): 7 bits a byte, low first."""
    if not 0 <= n <= 268_435_455:
        raise ValueError(f"remaining length {n} out of range")
    out = bytearray()
    while True:
        byte, n = n % 128, n // 128
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _string(s: str | bytes) -> bytes:
    data = s.encode("utf-8") if isinstance(s, str) else s
    if len(data) > 65_535:
        raise ValueError("an MQTT string is at most 65535 bytes")
    return struct.pack(">H", len(data)) + data


def _packet(kind: int, flags: int, body: bytes) -> bytes:
    return bytes([kind << 4 | flags]) + encode_remaining_length(len(body)) + body


def _check_topic(topic: str, wildcards: bool = False) -> None:
    if not topic:
        raise ValueError("a topic can't be empty")
    if not wildcards and ("+" in topic or "#" in topic):
        raise ValueError(f"a published topic can't contain wildcards: {topic!r}")


def encode_connect(
    client_id: str,
    keepalive_s: int = 30,
    will: tuple[str, bytes, bool] | None = None,
    username: str | None = None,
    password: str | None = None,
) -> bytes:
    """CONNECT with a clean session. `will` is (topic, payload, retain),
    published by the broker at QoS 0 if this client drops without a
    DISCONNECT."""
    if not 0 <= keepalive_s <= 65_535:
        raise ValueError("keep-alive is 0-65535 s")
    if password is not None and username is None:
        raise ValueError("MQTT 3.1.1 sends a password only with a user name")
    flags = 0x02  # clean session
    payload = _string(client_id)
    if will is not None:
        topic, message, retain = will
        _check_topic(topic)
        flags |= 0x04 | (0x20 if retain else 0)
        payload += _string(topic) + _string(message)
    if username is not None:
        flags |= 0x80
        payload += _string(username)
    if password is not None:
        flags |= 0x40
        payload += _string(password)
    header = _string("MQTT") + bytes([4, flags]) + struct.pack(">H", keepalive_s)
    return _packet(CONNECT, 0, header + payload)


def encode_publish(topic: str, payload: bytes, retain: bool = False) -> bytes:
    """PUBLISH at QoS 0 (no packet identifier)."""
    _check_topic(topic)
    return _packet(PUBLISH, 0x01 if retain else 0, _string(topic) + payload)


def encode_subscribe(packet_id: int, topics: list[str]) -> bytes:
    """SUBSCRIBE, every filter at QoS 0. The fixed-header flags are 0b0010 (§3.8.1)."""
    if not topics:
        raise ValueError("SUBSCRIBE needs at least one topic filter")
    body = struct.pack(">H", packet_id)
    for t in topics:
        _check_topic(t, wildcards=True)
        body += _string(t) + b"\x00"
    return _packet(SUBSCRIBE, 0x02, body)


PINGREQ_PACKET = bytes([PINGREQ << 4, 0])
DISCONNECT_PACKET = bytes([DISCONNECT << 4, 0])


def read_packet(read: Callable[[int], bytes]) -> tuple[int, int, bytes]:
    """One packet from `read(n)` (which returns exactly n bytes or raises):
    (type, flags, body)."""
    first = read(1)[0]
    length, shift = 0, 0
    for _ in range(4):
        byte = read(1)[0]
        length |= (byte & 0x7F) << shift
        if not byte & 0x80:
            break
        shift += 7
    else:
        raise MqttError("malformed remaining length")
    return first >> 4, first & 0x0F, read(length) if length else b""


def decode_publish(flags: int, body: bytes) -> tuple[str, bytes, bool]:
    """(topic, payload, retain) of a received PUBLISH."""
    (n,) = struct.unpack_from(">H", body)
    topic = body[2 : 2 + n].decode("utf-8")
    offset = 2 + n + (2 if flags & 0x06 else 0)  # a packet identifier only at QoS > 0
    return topic, body[offset:], bool(flags & 0x01)


# ---- client ------------------------------------------------------------------------------


class MqttClient:
    """A blocking MQTT 3.1.1 client: connect, publish, subscribe, receive.
    Not thread-safe; one thread owns it (the publisher's)."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1883,
        client_id: str = "controllab",
        keepalive_s: int = 30,
        will: tuple[str, bytes, bool] | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        self.host, self.port = host, port
        self.client_id = client_id
        self.keepalive_s = keepalive_s
        self.will = will
        self.username, self.password = username, password
        self.timeout_s = timeout_s
        self._sock: socket.socket | None = None
        self._last_sent = 0.0
        self._packet_id = 0

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout_s)
        self._sock = sock
        try:
            self._send(encode_connect(self.client_id, self.keepalive_s, self.will, self.username, self.password))
            kind, _, body = read_packet(self._read)
            if kind != CONNACK or len(body) != 2:
                raise MqttError(f"expected CONNACK, got packet type {kind}")
            if body[1]:
                raise MqttError(f"connection refused: {CONNACK_CODES.get(body[1], f'code {body[1]}')}")
        except BaseException:
            self._drop()
            raise

    def publish(self, topic: str, payload: bytes | str, retain: bool = False) -> None:
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        self._send(encode_publish(topic, data, retain))

    def subscribe(self, topics: list[str]) -> None:
        self._packet_id = self._packet_id % 65_535 + 1
        self._send(encode_subscribe(self._packet_id, topics))
        while True:
            kind, _, body = read_packet(self._read)
            if kind == SUBACK:
                if body[:2] != struct.pack(">H", self._packet_id):
                    raise MqttError("SUBACK for another packet")
                if b"\x80" in body[2:]:
                    raise MqttError("subscription refused")
                return
            if kind not in (PUBLISH, PINGRESP):
                raise MqttError(f"unexpected packet type {kind} awaiting SUBACK")

    def receive(self, timeout_s: float) -> tuple[str, bytes, bool] | None:
        """The next PUBLISH (topic, payload, retain), or None on timeout."""
        deadline = time.monotonic() + timeout_s
        while (left := deadline - time.monotonic()) > 0:
            self._require().settimeout(left)
            try:
                kind, flags, body = read_packet(self._read)
            except TimeoutError:
                return None
            finally:
                self._require().settimeout(self.timeout_s)
            if kind == PUBLISH:
                return decode_publish(flags, body)
        return None

    def ping_if_idle(self) -> None:
        """Keep the connection alive: a PINGREQ once the client has been quiet
        for half the keep-alive (the broker drops it at 1.5x). A publisher
        subscribes to nothing, so all it is ever sent is PINGRESPs: they are
        discarded here, unread, so they can't fill the socket's buffer."""
        if self.keepalive_s and time.monotonic() - self._last_sent >= self.keepalive_s / 2:
            self._discard_pending()
            self._send(PINGREQ_PACKET)

    def _discard_pending(self) -> None:
        sock = self._require()
        sock.setblocking(False)
        try:
            while sock.recv(4096):
                pass
            self._drop()  # recv returned b"": the broker closed the connection
            raise MqttError("connection closed by the broker")
        except BlockingIOError:
            pass
        finally:
            if self._sock is not None:
                self._sock.settimeout(self.timeout_s)

    def disconnect(self) -> None:
        """A clean DISCONNECT: the broker discards the last will."""
        if self._sock is not None:
            try:
                self._send(DISCONNECT_PACKET)
            finally:
                self._drop()

    def abort(self) -> None:
        """Drop the connection without a DISCONNECT (the broker publishes the will)."""
        self._drop()

    def _require(self) -> socket.socket:
        if self._sock is None:
            raise MqttError("not connected")
        return self._sock

    def _send(self, data: bytes) -> None:
        try:
            self._require().sendall(data)
        except OSError:
            self._drop()
            raise
        self._last_sent = time.monotonic()

    def _read(self, n: int) -> bytes:
        sock = self._require()
        chunks, left = [], n
        while left:
            chunk = sock.recv(left)
            if not chunk:
                self._drop()
                raise MqttError("connection closed by the broker")
            chunks.append(chunk)
            left -= len(chunk)
        return b"".join(chunks)

    def _drop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None


# ---- telemetry ---------------------------------------------------------------------------

STATE_FIELDS = ("mode", "state", "line_mode", "fault_reason", "last_start_refusal", "source_bin", "active_bin", "batch",
                "alarms")


class TelemetryPublisher:
    """Publishes a snapshot source (LiveSession.snapshot, or anything
    returning the same shape) to MQTT by exception. Call publish_changes()
    periodically; it returns how many messages it sent.

    `deadbands` maps tag -> the change (engineering units) worth publishing;
    tags not in it publish on any change. A tag whose change stays inside its
    deadband keeps its last published value, so a slow drift is still
    published once it has moved a whole deadband from there."""

    def __init__(
        self,
        client: MqttClient,
        snapshot: Callable[[int], dict],
        prefix: str = "controllab/line1",
        deadbands: dict[str, float] | None = None,
    ) -> None:
        _check_topic(prefix)
        self.client = client
        self.snapshot = snapshot
        self.prefix = prefix.rstrip("/")
        self.deadbands = dict(deadbands or {})
        self.status_topic = f"{self.prefix}/status"
        client.will = (self.status_topic, b"offline", True)
        self._published: dict[str, object] = {}
        self._state: dict | None = None
        self._since = 0
        self._session: object = None

    def connect(self) -> None:
        """Connect (the will registered), announce "online", and forget what
        was published, so the first publish_changes() sends everything."""
        self.client.connect()
        self.client.publish(self.status_topic, "online", retain=True)
        self._published.clear()
        self._state = None

    def close(self) -> None:
        """Publish "offline" and disconnect cleanly."""
        if self.client.connected:
            self.client.publish(self.status_topic, "offline", retain=True)
            self.client.disconnect()

    def publish_changes(self) -> int:
        snap = self.snapshot(self._since)
        if snap.get("session") != self._session:  # a new session: its events start again from 0
            self._session = snap.get("session")
            if self._since:
                self._since = 0
                snap = self.snapshot(0)
        sent = 0
        t = round(snap["t"], 3)
        for tag, value in snap["values"].items():
            if self._changed(tag, value):
                self.client.publish(f"{self.prefix}/tags/{tag}", json.dumps({"value": value, "t": t}), retain=True)
                self._published[tag] = value
                sent += 1
        state = {k: snap.get(k) for k in STATE_FIELDS}
        if state != self._state:
            self.client.publish(f"{self.prefix}/state", json.dumps({**state, "t": t}), retain=True)
            self._state = state
            sent += 1
        for event in snap["events"]:
            self.client.publish(f"{self.prefix}/events", json.dumps(event))
            sent += 1
        self._since = snap["event_count"]
        if not sent:
            self.client.ping_if_idle()
        return sent

    def _changed(self, tag: str, value: object) -> bool:
        if tag not in self._published:
            return True
        last = self._published[tag]
        band = self.deadbands.get(tag)
        if band and isinstance(value, (int, float)) and not isinstance(value, bool) and isinstance(last, (int, float)):
            return abs(value - last) > band
        return value != last


def run_publisher(
    publisher: TelemetryPublisher,
    halt: threading.Event,
    interval_s: float = 0.5,
    retry_s: float = 5.0,
    log: Callable[[str], None] = print,
) -> None:
    """The dashboard's publishing loop: publish_changes() every interval
    until `halt` is set. A broker that is down or goes away is reported and
    retried, never fatal: telemetry must not stop the line it observes."""
    up = False
    while not halt.is_set():
        try:
            if not publisher.client.connected:
                publisher.connect()
                log(f"MQTT: publishing to {publisher.client.host}:{publisher.client.port} under {publisher.prefix}/")
                up = True
            publisher.publish_changes()
        except (OSError, MqttError) as exc:
            publisher.client.abort()
            if up:
                log(f"MQTT: lost the broker ({exc}); retrying every {retry_s:g} s")
                up = False
            halt.wait(retry_s)
            continue
        halt.wait(interval_s)
    try:
        publisher.close()
    except (OSError, MqttError):
        pass
