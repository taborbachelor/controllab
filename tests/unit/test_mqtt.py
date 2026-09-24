"""The MQTT packet layer and the telemetry publisher (master specification,
item 8), without a broker. tests/integration/test_mqtt_broker.py proves the
same client against a real Mosquitto."""
import io
import json
import struct

import pytest

from services.protocols import mqtt
from services.visualization.live import LiveSession


def reader(data: bytes):
    stream = io.BytesIO(data)

    def read(n):
        chunk = stream.read(n)
        if len(chunk) != n:
            raise EOFError
        return chunk
    return read


@pytest.mark.parametrize("n, encoded", [
    (0, b"\x00"), (127, b"\x7f"), (128, b"\x80\x01"), (16_383, b"\xff\x7f"),
    (16_384, b"\x80\x80\x01"), (2_097_151, b"\xff\xff\x7f"), (2_097_152, b"\x80\x80\x80\x01"),
    (268_435_455, b"\xff\xff\xff\x7f"),
])
def test_remaining_length_matches_the_standards_table(n, encoded):
    """The boundary values of MQTT 3.1.1 §2.2.3, Table 2.4."""
    assert mqtt.encode_remaining_length(n) == encoded
    kind, _, body = mqtt.read_packet(reader(b"\x30" + encoded + b"x" * n)) if n < 20_000 else (3, 0, b"x" * n)
    assert kind == 3 and len(body) == n


def test_remaining_length_rejects_what_four_bytes_cant_carry():
    with pytest.raises(ValueError):
        mqtt.encode_remaining_length(268_435_456)
    with pytest.raises(mqtt.MqttError, match="malformed"):
        mqtt.read_packet(reader(b"\x30\xff\xff\xff\xff\x01"))


def test_connect_packet_layout():
    """§3.1: protocol name, level 4, the flags, keep-alive, then the payload
    in the standard's order (client id, will topic, will message, user, password)."""
    pkt = mqtt.encode_connect("cl", 30, will=("s/status", b"offline", True), username="u", password="p")
    kind, flags, body = mqtt.read_packet(reader(pkt))
    assert (kind, flags) == (mqtt.CONNECT, 0)
    assert body[:7] == b"\x00\x04MQTT\x04"
    assert body[7] == 0x80 | 0x40 | 0x20 | 0x04 | 0x02  # user, password, will retain, will, clean session
    assert struct.unpack(">H", body[8:10]) == (30,)
    assert body[10:] == b"\x00\x02cl" + b"\x00\x08s/status" + b"\x00\x07offline" + b"\x00\x01u" + b"\x00\x01p"
    plain = mqtt.read_packet(reader(mqtt.encode_connect("cl")))[2]
    assert plain[7] == 0x02  # clean session only
    with pytest.raises(ValueError, match="password only with a user name"):
        mqtt.encode_connect("cl", password="p")


def test_publish_and_subscribe_packets():
    kind, flags, body = mqtt.read_packet(reader(mqtt.encode_publish("a/b", b"42", retain=True)))
    assert (kind, flags) == (mqtt.PUBLISH, 0x01) and body == b"\x00\x03a/b42"
    assert mqtt.decode_publish(flags, body) == ("a/b", b"42", True)
    # A QoS 1 PUBLISH from a broker carries a packet identifier after the topic.
    assert mqtt.decode_publish(0x02, b"\x00\x03a/b\x00\x07hi") == ("a/b", b"hi", False)
    kind, flags, body = mqtt.read_packet(reader(mqtt.encode_subscribe(7, ["x/#", "y/+"])))
    assert (kind, flags) == (mqtt.SUBSCRIBE, 0x02)
    assert body == b"\x00\x07" + b"\x00\x03x/#\x00" + b"\x00\x03y/+\x00"
    with pytest.raises(ValueError, match="wildcards"):
        mqtt.encode_publish("x/#", b"")


def one_shot_broker(reply: bytes):
    """A socket that answers one CONNECT with `reply`, then closes."""
    import socket
    import threading

    server = socket.create_server(("127.0.0.1", 0))

    def serve():
        conn, _ = server.accept()
        with conn:
            mqtt.read_packet(lambda n: conn.recv(n, socket.MSG_WAITALL))
            conn.sendall(reply)
        server.close()
    threading.Thread(target=serve, daemon=True).start()
    return server.getsockname()[1]


def test_a_refused_connection_is_reported_with_its_reason():
    port = one_shot_broker(bytes([0x20, 0x02, 0x00, 0x05]))  # CONNACK, return code 5
    c = mqtt.MqttClient("127.0.0.1", port)
    with pytest.raises(mqtt.MqttError, match="not authorized"):
        c.connect()
    assert not c.connected


def test_a_reply_that_isnt_a_connack_is_a_protocol_error():
    port = one_shot_broker(bytes([0xD0, 0x00]))  # a PINGRESP
    c = mqtt.MqttClient("127.0.0.1", port)
    with pytest.raises(mqtt.MqttError, match="expected CONNACK"):
        c.connect()
    assert not c.connected


class FakeClient:
    def __init__(self):
        self.sent = []
        self.connected = False
        self.will = None
        self.pings = 0

    def connect(self):
        self.connected = True

    def publish(self, topic, payload, retain=False):
        self.sent.append((topic, json.loads(payload) if payload.startswith("{") else payload, retain))

    def ping_if_idle(self):
        self.pings += 1

    def disconnect(self):
        self.connected = False

    def topics(self):
        return [t for t, _, _ in self.sent]


def publisher(session, **kw):
    client = FakeClient()
    pub = mqtt.TelemetryPublisher(client, session.snapshot, **kw)
    pub.connect()
    client.sent.clear()
    return pub, client


def test_the_first_publish_sends_every_tag_and_the_state_retained_then_only_changes():
    s = LiveSession()
    pub, client = publisher(s)
    assert client.will == ("controllab/line1/status", b"offline", True)
    n = pub.publish_changes()
    tags = [t for t in client.topics() if "/tags/" in t]
    assert len(tags) == len(s.rig.io.names()) and "controllab/line1/state" in client.topics()
    assert all(retain for t, _, retain in client.sent)
    assert n == len(client.sent)
    client.sent.clear()
    assert pub.publish_changes() == 0 and client.pings == 1  # nothing changed: a keep-alive, not a message
    s.command("start")
    s.step()
    pub.publish_changes()
    topics = client.topics()
    assert "controllab/line1/tags/M-104.RUN" in topics and "controllab/line1/state" in topics
    events = [p for t, p, retain in client.sent if t.endswith("/events")]
    assert {"type": "command_issued"}.items() <= events[0].items() and not any(
        retain for t, _, retain in client.sent if t.endswith("/events"))
    state = next(p for t, p, _ in client.sent if t.endswith("/state"))
    assert state["state"] == "starting" and state["line_mode"] == "auto"


def test_a_deadband_holds_a_tag_until_it_moves_a_whole_band_from_the_last_published_value():
    s = LiveSession()
    pub, client = publisher(s, deadbands={"WT-105": 50.0})
    pub.publish_changes()
    s.command("start")
    published = []
    for _ in range(600):
        s.step()
        client.sent.clear()
        pub.publish_changes()
        published += [p["value"] for t, p, _ in client.sent if t.endswith("/tags/WT-105")]
    assert len(published) >= 3
    assert all(b - a > 50.0 for a, b in zip(published, published[1:]))


def test_a_new_session_republishes_its_events_from_the_start():
    s = LiveSession()
    pub, client = publisher(s)
    s.command("start")
    for _ in range(5):
        s.step()
    pub.publish_changes()
    s.restart()
    s.command("start")
    s.step()
    client.sent.clear()
    pub.publish_changes()
    assert any(t.endswith("/events") and p["type"] == "command_issued" for t, p, _ in client.sent)


def test_the_publishing_loop_survives_a_broker_that_is_down():
    import threading

    class DownClient(FakeClient):
        def connect(self):
            raise ConnectionRefusedError("refused")

        def abort(self):
            pass

    halt = threading.Event()
    pub = mqtt.TelemetryPublisher(DownClient(), LiveSession().snapshot)
    logs = []
    thread = threading.Thread(target=mqtt.run_publisher, args=(pub, halt), kwargs={"retry_s": 0.01, "log": logs.append})
    thread.start()
    halt.wait(0.1)
    halt.set()
    thread.join(2)
    assert not thread.is_alive()
