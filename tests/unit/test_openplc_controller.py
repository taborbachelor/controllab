"""OpenPLCController (Phase 9 step 2) against a stand-in for OpenPLC's web
UI: the real runtime is exercised by `scripts/scenario_report.py
--realtime openplc` (examples/openplc/COMMISSIONING-REPORT.md), not by
the unit suite, which needs no Docker."""
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from services.protocols.openplc import OpenPLCController, OpenPLCError


class FakeOpenPLC:
    """Just enough of OpenPLC's web UI: a session cookie from /login, and
    /stop_plc and /start_plc that only work when logged in."""

    def __init__(self, password="openplc"):
        self.calls = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, body, cookie=None):
                self.send_response(200)
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                self.end_headers()
                self.wfile.write(body.encode())

            def do_POST(self):
                fields = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
                fake.calls.append(("POST", self.path))
                if self.path == "/login" and fields.get("password") == [password]:
                    self._reply("<h2>Dashboard</h2>", cookie="session=ok")
                else:
                    self._reply("Bad credentials! Try again")

            def do_GET(self):
                fake.calls.append(("GET", self.path))
                if "session=ok" not in (self.headers.get("Cookie") or ""):
                    self._reply("<form>login</form>")
                    return
                self._reply("ok")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def plc():
    fake = FakeOpenPLC()
    yield fake
    fake.close()


def test_restart_is_stop_then_start_after_one_login(plc):
    controller = OpenPLCController(plc.url)
    controller.restart()
    controller.restart()
    assert plc.calls == [
        ("POST", "/login"),
        ("GET", "/stop_plc"), ("GET", "/start_plc"),
        ("GET", "/stop_plc"), ("GET", "/start_plc"),
    ]


def test_bad_credentials_fail_loudly_instead_of_restarting_nothing(plc):
    controller = OpenPLCController(plc.url, password="wrong")
    with pytest.raises(OpenPLCError, match="login failed"):
        controller.restart()
    assert ("GET", "/stop_plc") not in plc.calls
