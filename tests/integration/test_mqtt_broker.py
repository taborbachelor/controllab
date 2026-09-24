"""The hand-rolled MQTT client against a real broker (master specification,
item 8): Eclipse Mosquitto, in Docker locally and as a CI step.

Runs when CONTROLLAB_MQTT_BROKER names a broker (host:port) that allows
anonymous clients:

    docker run -d --name controllab-mosquitto -p 127.0.0.1:1883:1883 \\
        eclipse-mosquitto:2 mosquitto -c /mosquitto-no-auth.conf
    CONTROLLAB_MQTT_BROKER=127.0.0.1:1883 CONTROLLAB_MQTT_CONTAINER=controllab-mosquitto pytest ...

With CONTROLLAB_MQTT_CONTAINER naming the broker's container as well, the
telemetry is also read back with Mosquitto's own `mosquitto_sub`, so the
client is never only checked against itself."""
import json
import os
import shutil
import subprocess
import uuid

import pytest

from services.protocols import mqtt
from services.visualization.live import LiveSession

BROKER = os.environ.get("CONTROLLAB_MQTT_BROKER")
CONTAINER = os.environ.get("CONTROLLAB_MQTT_CONTAINER")
pytestmark = pytest.mark.skipif(not BROKER, reason="set CONTROLLAB_MQTT_BROKER=host:port to run against a broker")


def client(**kw) -> mqtt.MqttClient:
    host, port = BROKER.rsplit(":", 1)
    return mqtt.MqttClient(host, int(port), client_id=f"controllab-test-{uuid.uuid4().hex[:8]}", **kw)


@pytest.fixture
def prefix():
    """A topic prefix of its own per test, and its retained messages cleared after."""
    p = f"controllab-test/{uuid.uuid4().hex[:8]}"
    yield p
    reader = client()
    reader.connect()
    reader.subscribe([f"{p}/#"])
    retained = []
    while (msg := reader.receive(0.5)) is not None:
        retained.append(msg[0])
    for topic in retained:
        reader.publish(topic, b"", retain=True)  # an empty retained message clears it
    reader.disconnect()


def collect(sub: mqtt.MqttClient, timeout_s: float = 1.0) -> dict[str, list]:
    got: dict[str, list] = {}
    while (msg := sub.receive(timeout_s)) is not None:
        topic, payload, retain = msg
        got.setdefault(topic, []).append((payload, retain))
    return got


def test_publish_and_subscribe_round_trip_through_the_broker(prefix):
    sub = client()
    sub.connect()
    sub.subscribe([f"{prefix}/#"])
    pub = client()
    pub.connect()
    pub.publish(f"{prefix}/a", "hello")
    pub.publish(f"{prefix}/b", b"\x00\xff" * 200, retain=True)  # binary, and a two-byte remaining length
    got = collect(sub)
    assert got[f"{prefix}/a"] == [(b"hello", False)]
    assert got[f"{prefix}/b"] == [(b"\x00\xff" * 200, False)]  # retain is cleared on a live delivery
    late = client()
    late.connect()
    late.subscribe([f"{prefix}/b"])
    assert late.receive(1.0) == (f"{prefix}/b", b"\x00\xff" * 200, True)  # the retained copy
    for c in (sub, pub, late):
        c.disconnect()


def test_the_last_will_announces_a_publisher_that_drops(prefix):
    sub = client()
    sub.connect()
    sub.subscribe([f"{prefix}/status"])
    pub = client(will=(f"{prefix}/status", b"offline", True))
    pub.connect()
    pub.publish(f"{prefix}/status", "online", retain=True)
    assert sub.receive(1.0)[1] == b"online"
    pub.abort()  # no DISCONNECT: the broker publishes the will
    assert sub.receive(3.0)[1] == b"offline"
    sub.disconnect()


def test_a_clean_disconnect_discards_the_will(prefix):
    sub = client()
    sub.connect()
    sub.subscribe([f"{prefix}/status"])
    pub = client(will=(f"{prefix}/status", b"offline", True))
    pub.connect()
    pub.disconnect()
    assert sub.receive(1.0) is None
    sub.disconnect()


def test_the_keep_alive_holds_an_idle_connection_open(prefix):
    """Keep-alive 2 s: the broker drops a silent client after 3 s. Pinging at
    half the interval keeps this one; publishing afterwards proves it."""
    import time

    sub = client()
    sub.connect()
    sub.subscribe([f"{prefix}/x"])
    pub = client(keepalive_s=2)
    pub.connect()
    for _ in range(40):  # 4 s, longer than the broker's 3 s limit
        pub.ping_if_idle()
        time.sleep(0.1)
    pub.publish(f"{prefix}/x", "still here")
    assert sub.receive(1.0)[1] == b"still here"
    for c in (sub, pub):
        c.disconnect()


def test_the_line_telemetry_reaches_a_subscriber(prefix):
    session = LiveSession()
    sub = client()
    sub.connect()
    sub.subscribe([f"{prefix}/#"])
    publisher = mqtt.TelemetryPublisher(client(), session.snapshot, prefix=prefix)
    publisher.connect()
    publisher.publish_changes()
    session.command("start")
    for _ in range(40):
        session.step()
        publisher.publish_changes()
    got = collect(sub)
    assert got[f"{prefix}/status"][0][0] == b"online"
    assert len([t for t in got if "/tags/" in t]) == len(session.rig.io.names())
    states = [json.loads(p)["state"] for p, _ in got[f"{prefix}/state"]]
    assert states[0] == "idle" and "starting" in states
    events = [json.loads(p) for p, _ in got[f"{prefix}/events"]]
    assert events[0]["type"] == "command_issued" and events[0]["command"] == "start"
    last_run = json.loads(got[f"{prefix}/tags/M-104.RUN"][-1][0])
    assert last_run["value"] is True
    publisher.close()
    sub.disconnect()


@pytest.mark.skipif(not CONTAINER or not shutil.which("docker"), reason="set CONTROLLAB_MQTT_CONTAINER to cross-check")
def test_mosquitto_sub_reads_what_the_publisher_retained(prefix):
    """The broker's own client reads the retained telemetry back."""
    session = LiveSession()
    publisher = mqtt.TelemetryPublisher(client(), session.snapshot, prefix=prefix)
    publisher.connect()
    publisher.publish_changes()
    out = subprocess.run(
        ["docker", "exec", CONTAINER, "mosquitto_sub", "-t", f"{prefix}/#", "-v", "-W", "2"],
        capture_output=True, text=True, timeout=30,
    ).stdout
    publisher.close()
    lines = dict(line.split(" ", 1) for line in out.splitlines() if " " in line)
    assert lines[f"{prefix}/status"] == "online"
    assert json.loads(lines[f"{prefix}/tags/WT-105"])["value"] == pytest.approx(session.snapshot()["values"]["WT-105"])
    assert json.loads(lines[f"{prefix}/state"])["state"] == "idle"
