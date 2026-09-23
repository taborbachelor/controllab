"""The dashboard's HTTP layer end to end on a real localhost socket
(port 0, stdlib only). The Pacer is constructed but never started --
tests step the session by hand, so nothing here depends on wall-clock
timing."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from services.visualization.live import LiveSession, Pacer, make_handler


@pytest.fixture
def server():
    session = LiveSession()
    pacer = Pacer(session)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(session, pacer))
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", session, pacer
    httpd.shutdown()
    httpd.server_close()


def request(url, data=None, content_type="application/json", host=None):
    headers = {}
    if data is not None:
        headers["Content-Type"] = content_type
    if host:
        headers["Host"] = host
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def test_index_serves_the_assembled_dashboard(server):
    base, _, _ = server
    status, body, _ = request(base + "/")
    assert status == 200
    assert 'id="mimic"' in body and "/*__" not in body and "<!--__" not in body


def test_command_round_trip(server):
    base, session, _ = server
    assert request(base + "/api/command", {"name": "start"})[0] == 200
    session.step()
    status, body, _ = request(base + "/api/state")
    state = json.loads(body)
    assert status == 200
    assert state["state"] == "starting"
    assert state["running"] is True and state["speed"] == 1.0


def test_stimulus_and_bad_input(server):
    base, session, _ = server
    assert request(base + "/api/stimulus", {"key": "estop", "value": "tripped"})[0] == 200
    session.step()
    session.step()  # Control sees a plant-side change one scan after it's published
    assert json.loads(request(base + "/api/state")[1])["state"] == "estopped"
    status, body, _ = request(base + "/api/stimulus", {"key": "estop", "value": 7})
    assert status == 400 and "estop" in json.loads(body)["error"]


def test_run_controls_pause_and_speed(server):
    base, _, pacer = server
    assert request(base + "/api/run", {"running": False, "speed": 5})[0] == 200
    assert (pacer.running, pacer.speed) == (False, 5.0)
    assert request(base + "/api/run", {"speed": 3})[0] == 400


def test_replay_download(server):
    base, session, _ = server
    session.step()
    status, body, headers = request(base + "/api/replay")
    assert status == 200
    assert "attachment" in headers["Content-Disposition"]
    assert "ControlLab Replay" in body


def test_post_without_json_content_type_is_refused(server):
    """A cross-origin page can send text/plain without a preflight; it
    must not be able to drive the line."""
    base, session, _ = server
    status, _, _ = request(base + "/api/command", {"name": "start"}, content_type="text/plain")
    assert status == 415
    session.step()
    assert session.snapshot()["state"] == "idle"


def test_foreign_host_header_is_refused(server):
    base, _, _ = server
    assert request(base + "/api/state", host="evil.example")[0] == 403
    assert request(base + "/api/command", {"name": "start"}, host="evil.example:8000")[0] == 403


def test_pacer_steps_in_real_time_and_stops_cleanly():
    session = LiveSession()
    pacer = Pacer(session, speed=10.0)  # 100 ticks per real second
    pacer.start()
    try:
        deadline = 50
        while session.snapshot()["t"] < 0.5 and deadline:
            threading.Event().wait(0.02)
            deadline -= 1
        assert session.snapshot()["t"] >= 0.5
    finally:
        pacer.stop()
        pacer.join(timeout=2)
    assert not pacer.is_alive()
