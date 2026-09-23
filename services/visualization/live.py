"""The live dashboard (docs/CONTROL-LAB.md §10, Phase 6 step 3): the
simulated line running in real time in-process, the shared line mimic in
a browser, operator commands, and a separate test-stimulus panel for
injecting faults -- served by Python's stdlib http.server, bound to
localhost only. `python scripts/dashboard.py` starts it.

Three pieces, each small enough to test on its own:

- **LiveSession** -- the deterministic core. Owns a rig built exactly as
  every scenario's is (services/testing/rig.py), the same telemetry pair
  the runner records (EventLog + command sink + TagHistory), and the
  continuous invariants (services/testing/invariants.py). Commands and
  stimuli from the browser are *queued* and applied only at the next
  tick boundary, inside step() -- the same "stimuli are applied at the
  start of a scan" rule as docs/CONTROL-LAB.md §3.3, so a click can never
  land halfway through a scan. step() advances simulated time by exactly
  one DT; nothing in here reads the wall clock.
- **Pacer** -- the only thing that knows about real time: a thread that
  calls step() every DT/speed wall-clock seconds.
- **make_handler()** -- the HTTP routes, a thin JSON layer over the two.

Operator commands go through LineController's own one-shot methods;
stimuli go through services/testing/vocabulary.apply_field -- the same
closed vocabulary scenario files use -- so the dashboard adds no new way
to reach into the plant. Visualization depends on Testing here (the rig,
the vocabulary, the invariants) because the dashboard *drives* the line,
the same role the scenario runner has; replay.py, which only observes,
still depends on Telemetry alone.

A live run is not reproducible the way a scenario is -- command timing
comes from a person -- but its record is: the session records the same
telemetry a scenario does, and replay_html() turns it into the step-2
replay viewer, so any live session can be saved and inspected afterwards.

Security: localhost only, no authentication (docs/CONTROL-LAB.md §9: no
multi-user, no auth in early phases). Two cheap guards still apply,
because any web page the user visits can make requests to localhost:
every POST must be `Content-Type: application/json` (a cross-origin page
can't send that without a CORS preflight, which this server never
answers), and the Host header must be localhost/127.0.0.1 (blocks DNS
rebinding).
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from services.telemetry.events import EventLog
from services.telemetry.tag_history import TagHistory
from services.testing.invariants import InvariantViolation, Invariants
from services.testing.rig import DEFAULT_PLANT_CONFIG, DT, build_rig, tick
from services.testing.vocabulary import apply_field
from services.visualization.page import assemble
from services.visualization.replay import build_replay, render_html

COMMANDS = ("start", "stop", "reset", "acknowledge")

# The fault/condition half of the scenario vocabulary, with the value
# shape each accepts. Operator commands are deliberately not in here --
# they're a different panel and a different kind of action.
STIMULI: dict[str, str] = {
    "estop": "estop",  # "tripped" | "healthy"
    "conveyor_trip": "bool",
    "feeder_trip": "bool",
    "conveyor_fail_to_start": "bool",
    "feeder_fail_to_start": "bool",
    "gate_stuck": "bool",
    "belt_slip": "bool",
    "feeder_drive_reset": "action",  # field resets: true only, one-shot
    "conveyor_overload_reset": "action",
    "gate_reset": "action",
    "hopper_level_pct": "pct",
    "bin_level_pct": "pct",
}
# Directly setting a level is a deliberate setup action, not a physical
# event -- the conservation invariant is rebaselined after it, exactly as
# the scenario runner does for given/when (see Invariants.rebaseline()).
LEVEL_STIMULI = {"hopper_level_pct", "bin_level_pct"}

PLANT = {
    key: DEFAULT_PLANT_CONFIG[key]
    for key in ("hopper_capacity_kg", "hopper_high_pct", "hopper_high_high_pct", "bin_capacity_kg")
}


class LiveSession:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fresh()

    def _fresh(self) -> None:
        self.rig = build_rig()
        self.invariants = Invariants(self.rig)
        self.events = EventLog(self.rig.line)
        self.rig.line.command_sink = self.events.record_command
        self.tags = TagHistory(self.rig.io)
        self.events.sample(self.rig.plant.time_s)
        self.tags.record(self.rig.plant.time_s)
        self.violation: str | None = None
        self._pending: list[tuple[str, Callable[[], None]]] = []

    # ---- inputs (validated immediately, applied at the next tick) ------

    def command(self, name: str) -> None:
        if name not in COMMANDS:
            raise ValueError(f"unknown command {name!r} (known: {', '.join(COMMANDS)})")
        with self._lock:
            self._pending.append((name, getattr(self.rig.line, name)))

    def stimulus(self, key: str, value: object) -> None:
        kind = STIMULI.get(key)
        if kind is None:
            raise ValueError(f"unknown stimulus {key!r} (known: {', '.join(STIMULI)})")
        if kind == "action" and value is not True:
            raise ValueError(f"{key} is a one-shot action and takes true")
        if kind == "bool" and not isinstance(value, bool):
            raise ValueError(f"{key} takes true/false")
        if kind == "estop" and value not in ("tripped", "healthy"):
            raise ValueError("estop takes 'tripped' or 'healthy'")
        if kind == "pct" and (isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100):
            raise ValueError(f"{key} takes a number from 0 to 100")
        with self._lock:
            self._pending.append((key, lambda: apply_field(self.rig, key, value)))

    def restart(self) -> None:
        with self._lock:
            self._fresh()

    # ---- the scan ------------------------------------------------------

    def step(self) -> None:
        """Advance exactly one tick: apply everything queued since the last
        tick, scan, record telemetry, check invariants. The first
        violation is kept and shown -- the session keeps running (an
        engineer may want to see what happens next), but it's no longer a
        clean run and the banner says so until a restart."""
        with self._lock:
            pending, self._pending = self._pending, []
            for _, apply in pending:
                apply()
            if any(key in LEVEL_STIMULI for key, _ in pending):
                self.invariants.rebaseline()
            tick(self.rig, DT)
            t = self.rig.plant.time_s
            self.events.sample(t)
            self.tags.record(t)
            if self.violation is None:
                try:
                    self.invariants.check()
                except InvariantViolation as e:
                    self.violation = f"t={t:.2f}s: {e}"

    # ---- outputs -------------------------------------------------------

    def snapshot(self, since: int = 0) -> dict:
        """Everything the page needs to redraw, in the same shape as a
        replay frame (t/state/values/alarms), plus the events recorded
        after index `since` so the browser only fetches what's new."""
        with self._lock:
            line, plant = self.rig.line, self.rig.plant
            return {
                "t": plant.time_s,
                "state": line.state.name.lower(),
                "fault_reason": line.fault_reason,
                "last_start_refusal": list(line.last_start_refusal),
                "values": self.tags.samples[-1].values,
                "alarms": [
                    {
                        "id": a.id,
                        "description": a.description,
                        "is_warning": a.is_warning,
                        "active": a.active,
                        "acknowledged": a.acknowledged,
                        "first_out": a.first_out,
                    }
                    for a in sorted(line.alarms.all_alarms, key=lambda a: a.id)
                    if a.latched
                ],
                "events": [{"t": e.t, "type": e.type, **e.data} for e in self.events.events[since:]],
                "event_count": len(self.events.events),
                "injected": {
                    "estop": "tripped" if plant.estop.tripped else "healthy",
                    "conveyor_trip": plant.conveyor.motor.trip_now,
                    "feeder_trip": plant.feeder.motor.trip_now,
                    "conveyor_fail_to_start": plant.conveyor.motor.fail_to_start,
                    "feeder_fail_to_start": plant.feeder.motor.fail_to_start,
                    "gate_stuck": plant.gate.stuck,
                    "belt_slip": plant.conveyor.motion_switch_stuck_false,
                },
                "violation": self.violation,
            }

    def config(self) -> dict:
        return {
            "plant": PLANT,
            "dt": DT,
            "tags": [
                {"name": n, "type": self.rig.io.tag(n).type.name, "units": self.rig.io.tag(n).units,
                 "description": self.rig.io.tag(n).description}
                for n in self.rig.io.names()
            ],
            "commands": list(COMMANDS),
            "stimuli": STIMULI,
        }

    def replay_html(self) -> str:
        with self._lock:
            detail = f"invariant violated {self.violation}" if self.violation else "recorded from the live dashboard"
            replay = build_replay(
                "Live session", list(self.events.events), self.tags, PLANT, meta={"file": "live dashboard", "detail": detail}
            )
        return render_html(replay)


class Pacer(threading.Thread):
    """Steps a LiveSession in real time: one tick every DT/speed wall-clock
    seconds while running. If the host falls more than a second behind
    (a laptop sleeping, a debugger pause) it resynchronizes instead of
    bursting hundreds of catch-up ticks at once."""

    def __init__(self, session: LiveSession, speed: float = 1.0) -> None:
        super().__init__(daemon=True, name="controllab-pacer")
        self.session = session
        self.speed = speed
        self.running = True
        self._halt = threading.Event()

    def run(self) -> None:
        next_at = time.monotonic()
        while not self._halt.is_set():
            now = time.monotonic()
            if now - next_at > 1.0:
                next_at = now
            if self.running:
                self.session.step()
            next_at += DT / self.speed
            self._halt.wait(max(0.0, next_at - time.monotonic()))

    def stop(self) -> None:
        self._halt.set()


SPEEDS = (0.5, 1.0, 2.0, 5.0, 10.0)
ALLOWED_HOSTS = ("127.0.0.1", "localhost")


def make_handler(session: LiveSession, pacer: Pacer) -> type[BaseHTTPRequestHandler]:
    page = assemble("live_template.html").replace(
        "/*__LIVE_CONFIG__*/null", json.dumps(session.config()).replace("</", "<\\/")
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 -- stdlib signature
            pass  # polled 10x a second; the console would be all noise

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return host in ALLOWED_HOSTS

        def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj: object) -> None:
            self._send(status, json.dumps(obj).encode("utf-8"), "application/json")

        def do_GET(self) -> None:  # noqa: N802 -- stdlib name
            if not self._host_ok():
                return self._json(403, {"error": "host not allowed"})
            url = urlparse(self.path)
            if url.path == "/":
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if url.path == "/api/state":
                try:
                    since = int(parse_qs(url.query).get("since", ["0"])[0])
                except ValueError:
                    return self._json(400, {"error": "since must be an integer"})
                state = session.snapshot(max(0, since))
                state.update(running=pacer.running, speed=pacer.speed)
                return self._json(200, state)
            if url.path == "/api/replay":
                return self._send(
                    200, session.replay_html().encode("utf-8"), "text/html; charset=utf-8",
                    {"Content-Disposition": 'attachment; filename="live-session.replay.html"'},
                )
            return self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 -- stdlib name
            if not self._host_ok():
                return self._json(403, {"error": "host not allowed"})
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                return self._json(415, {"error": "Content-Type must be application/json"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(length, 10_000)) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("body must be a JSON object")
                path = urlparse(self.path).path
                if path == "/api/command":
                    session.command(body.get("name"))
                elif path == "/api/stimulus":
                    session.stimulus(body.get("key"), body.get("value"))
                elif path == "/api/run":
                    if "running" in body:
                        pacer.running = bool(body["running"])
                    if "speed" in body:
                        if body["speed"] not in SPEEDS:
                            raise ValueError(f"speed must be one of {SPEEDS}")
                        pacer.speed = float(body["speed"])
                elif path == "/api/restart":
                    session.restart()
                else:
                    return self._json(404, {"error": "not found"})
            except (ValueError, json.JSONDecodeError) as e:
                return self._json(400, {"error": str(e)})
            return self._json(200, {"ok": True})

    return Handler
