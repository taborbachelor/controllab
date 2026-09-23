"""OpenPLC Runtime (v3) as a controller under test (docs/CONTROL-LAB.md
§10, Phase 9 step 2): its web API, and a cold restart through it.

ControlLab never talks to the PLC's logic except over Modbus. This is
only the commissioning engineer's other hand on the PLC: the runtime's
own web UI, used to log in and to stop and start the PLC -- the same
buttons a person presses at http://127.0.0.1:8080. `OpenPLCWeb` is also
what examples/openplc/setup_openplc.py scripts the upload/compile/device
forms with.

**Stop then start is a cold restart** (found by probing a running
runtime, not assumed): a start refused at bin low left the program's
`start_inhibit` at BIN_LOW and the warning latched; after stop_plc +
start_plc both were gone, and the PLC booted ESTOPPED, as it does on
first power-up, because its first scans run before its first Modbus
poll. While stopped it writes nothing. A restart takes about 4 s.

Stdlib only.
"""
from __future__ import annotations

import http.cookiejar
import time
import urllib.parse
import urllib.request
import uuid


class OpenPLCError(RuntimeError):
    pass


class OpenPLCWeb:
    """A logged-in session with the OpenPLC Runtime web UI (form posts and
    a cookie jar, exactly what a browser sends)."""

    def __init__(self, base: str, timeout_s: float = 30.0) -> None:
        self.base = base.rstrip("/")
        self.timeout_s = timeout_s
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(self, path: str) -> str:
        with self.opener.open(self.base + path, timeout=self.timeout_s) as r:
            return r.read().decode("utf-8", "replace")

    def post(self, path: str, fields: dict[str, str]) -> str:
        data = urllib.parse.urlencode(fields).encode()
        with self.opener.open(self.base + path, data=data, timeout=self.timeout_s) as r:
            return r.read().decode("utf-8", "replace")

    def upload(self, path: str, filename: str, content: bytes) -> str:
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            self.base + path, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        with self.opener.open(req, timeout=self.timeout_s) as r:
            return r.read().decode("utf-8", "replace")

    def wait_until_up(self, timeout_s: float = 60.0) -> None:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                self.get("/login")
                return
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)

    def login(self, user: str, password: str) -> None:
        page = self.post("/login", {"username": user, "password": password})
        if "Bad credentials" in page or "Dashboard" not in page:
            raise OpenPLCError(f"OpenPLC login failed at {self.base}")


class OpenPLCController:
    """ControllerUnderTest (services/testing/realtime.py) for an OpenPLC
    Runtime already configured to poll the plant (setup_openplc.py).
    `restart()` = stop_plc + start_plc, a cold restart; `close()` leaves
    the PLC running, as found."""

    def __init__(self, url: str = "http://127.0.0.1:8080", user: str = "openplc", password: str = "openplc") -> None:
        self.url = url
        self.name = f"OpenPLC Runtime at {url}, running examples/openplc/controllab_line.st"
        self._user, self._password = user, password
        self._web: OpenPLCWeb | None = None

    def restart(self) -> None:
        if self._web is None:
            web = OpenPLCWeb(self.url)
            web.login(self._user, self._password)
            self._web = web
        self._web.get("/stop_plc")
        self._web.get("/start_plc")

    def close(self) -> None:
        self._web = None
