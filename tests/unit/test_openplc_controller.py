"""OpenPLCController (Phase 9 step 2) against a stand-in for OpenPLC's web
UI: the real runtime is exercised by `scripts/scenario_report.py
--realtime openplc` (examples/openplc/COMMISSIONING-REPORT.md), not by
the unit suite, which needs no Docker."""
import itertools
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from services.protocols.openplc import OpenPLCController, OpenPLCError


class FakeOpenPLC:
    """Just enough of OpenPLC's web UI, behaving as the real one does: a
    session cookie from /login; without a live session every page redirects
    to /login; /stop_plc and /start_plc redirect to /dashboard, which shows
    the runtime's status. `expire()` loses every session (what happened an
    hour into the 2026-09-27 report); `stuck` leaves the runtime running
    whatever is pressed."""

    def __init__(self, password="openplc"):
        self.calls = []
        self.sessions: set[str] = set()
        self.status = "Running"
        self.stuck = False
        self.refuse_logins = False  # a login "succeeds" but its session is never honoured
        numbers = itertools.count(1)
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

            def _redirect(self, to):
                self.send_response(302)
                self.send_header("Location", to)
                self.end_headers()

            def do_POST(self):
                fields = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
                fake.calls.append(("POST", self.path))
                if self.path == "/login" and fields.get("password") == [password]:
                    session = f"s{next(numbers)}"
                    if not fake.refuse_logins:
                        fake.sessions.add(session)
                    self._reply("<h2>Dashboard</h2>", cookie=f"session={session}")
                else:
                    self._reply("Bad credentials! Try again")

            def do_GET(self):
                fake.calls.append(("GET", self.path))
                cookie = self.headers.get("Cookie") or ""
                session = cookie.partition("session=")[2].split(";")[0]
                if self.path == "/login":
                    self._reply("<form>login</form>")
                elif session not in fake.sessions:
                    self._redirect("/login")
                elif self.path in ("/stop_plc", "/start_plc"):
                    if not fake.stuck:
                        fake.status = "Stopped" if self.path == "/stop_plc" else "Running"
                    self._redirect("/dashboard")
                elif self.path == "/dashboard":
                    colour = "#02CC07" if fake.status == "Running" else "Red"
                    self._reply(f"<p><b>Status: <font color = '{colour}'>{fake.status}</font></b></p>")
                else:
                    self._reply("ok")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def expire(self):
        self.sessions.clear()

    def presses(self):
        return [c for c in self.calls if c in (("GET", "/stop_plc"), ("GET", "/start_plc"), ("POST", "/login"))]

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
    assert plc.presses() == [
        ("POST", "/login"),
        ("GET", "/stop_plc"), ("GET", "/start_plc"),
        ("GET", "/stop_plc"), ("GET", "/start_plc"),
    ]
    assert plc.status == "Running"


def test_bad_credentials_fail_loudly_instead_of_restarting_nothing(plc):
    controller = OpenPLCController(plc.url, password="wrong")
    with pytest.raises(OpenPLCError, match="login failed"):
        controller.restart()
    assert ("GET", "/stop_plc") not in plc.calls


def test_a_lost_session_logs_in_again_and_the_restart_happens(plc):
    """The 2026-09-27 finding: the session went away mid-run, and every
    stop/start after that landed on the login page and restarted nothing."""
    controller = OpenPLCController(plc.url)
    controller.restart()
    plc.expire()
    plc.calls.clear()
    controller.restart()
    assert plc.presses() == [
        ("GET", "/stop_plc"),                       # lands on the login page
        ("POST", "/login"), ("GET", "/stop_plc"),   # logged in again, pressed again
        ("GET", "/start_plc"),
    ]
    assert plc.status == "Running"


def test_a_login_that_never_sticks_stops_the_run(plc):
    controller = OpenPLCController(plc.url)
    plc.refuse_logins = True
    with pytest.raises(OpenPLCError, match="login page even after logging in again"):
        controller.restart()
    assert ("GET", "/start_plc") not in plc.calls  # never "started" a PLC it couldn't stop


def test_a_runtime_that_does_not_stop_stops_the_run(plc):
    controller = OpenPLCController(plc.url)
    plc.stuck = True
    with pytest.raises(OpenPLCError, match="expected its dashboard to say Stopped, it says Running"):
        controller.restart()
