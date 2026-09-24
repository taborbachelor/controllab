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

from services.protocols.line_map import LINE_REGISTER_MAP
from services.telemetry.events import Event, EventLog
from services.telemetry.tag_history import TagHistory
from services.simulation.equipment.instruments import InstrumentFault
from services.testing.invariants import InvariantViolation, Invariants
from services.testing.regressions import REGRESSIONS
from services.testing.runner import _Telemetry, execute
from services.testing.rig import DEFAULT_PLANT_CONFIG, DT, build_rig, tick
from services.testing.vocabulary import apply_field
from services.visualization import verify, walkthroughs
from services.visualization.narrate import narrate
from services.visualization.page import assemble
from services.visualization.replay import build_replay, render_html

# Every operator command, in the HMI request word's bit order: the four line
# commands, then Manual mode's mode select and device pushbuttons.
COMMANDS = tuple(LINE_REGISTER_MAP.commands)

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
    "gate_b_stuck": "bool",
    "gate_c_stuck": "bool",
    "gate_b_reset": "action",
    "outlet_stuck": "bool",
    "outlet_plugged": "bool",
    "outlet_reset": "action",
    "gate_c_reset": "action",
    "bin_b_level_pct": "pct",
    "bin_c_level_pct": "pct",
    "belt_slip": "bool",
    "conveyor_jam": "bool",
    "bin_bridged": "bool",
    "feeder_jam": "bool",
    "feeder_drive_reset": "action",  # field resets: true only, one-shot
    "conveyor_overload_reset": "action",
    "gate_reset": "action",
    "hopper_level_pct": "pct",
    "bin_level_pct": "pct",
    # Instrument faults (the value is an input tag): what a field
    # instrument reports, not what the process is doing.
    "sensor_stuck": "instrument",
    "sensor_failed": "instrument",
    "sensor_restored": "instrument",
    # Degraded instruments: {tag, <parameter>} (vocabulary._degraded_action).
    "sensor_noise": "degraded",
    "sensor_drift": "degraded",
    "sensor_slow": "degraded",
}
# Directly setting a level is a deliberate setup action, not a physical
# event -- the conservation invariant is rebaselined after it, exactly as
# the scenario runner does for given/when (see Invariants.rebaseline()).
LEVEL_STIMULI = {"hopper_level_pct", "bin_level_pct", "bin_b_level_pct", "bin_c_level_pct"}

# External-controller mode (Phase 7 step 3): if no controller output
# write arrives for this long (simulated seconds), every output is forced
# off -- the comm-loss fault action real remote I/O is configured with, so
# a crashed or disconnected external controller cannot leave a conveyor
# running forever.
WATCHDOG_S = 1.0

PLANT = {
    key: DEFAULT_PLANT_CONFIG[key]
    for key in ("hopper_capacity_kg", "hopper_high_pct", "hopper_high_high_pct", "bin_capacity_kg")
}


class LiveSession:
    """`external=True` runs the plant with NO built-in controller (Phase 7
    step 3): an external controller owns the outputs over Modbus, operator
    commands become HMI requests (`self.handshake`, a request/ack word
    pair) for it to pick up, line state and alarms live in that
    controller (so the snapshot reports state "external" and no alarms),
    and a comm-loss watchdog de-energizes every output if the controller
    stops writing."""

    def __init__(self, external: bool = False) -> None:
        # Re-entrant because the Modbus server (Phase 7 step 2) holds this
        # same lock while serving a request, and an HMI coil write calls
        # back into command() from inside that request -- a plain Lock
        # would deadlock there.
        self._lock = threading.RLock()
        self.external = external
        # Created once, not per session: the Modbus data store holds this
        # object, so restart() resets it instead of replacing it.
        self.handshake = LINE_REGISTER_MAP.handshake()
        # A scenario verification owns the line while it runs (run_live):
        # the pacer's ticks and every manual input are refused meanwhile.
        self.verifying: str | None = None
        self._fresh()

    @property
    def lock(self) -> threading.RLock:
        """Shared with anything else serving this session's I/O image
        (the Modbus server), so it never observes a half-applied scan."""
        return self._lock

    @property
    def io(self):
        """The current I/O image -- replaced on restart(), so callers
        should ask for it each time rather than keep a reference."""
        return self.rig.io

    def _fresh(self, line_cls=None) -> None:
        self.rig = (build_rig(with_controller=not self.external) if line_cls is None
                    else build_rig(line_cls=line_cls))
        self.invariants = Invariants(self.rig)
        self.tags = TagHistory(self.rig.io)
        self.tags.record(self.rig.plant.time_s)
        if self.external:
            # No LineController to diff, so EventLog cannot run; commands
            # and watchdog trips are recorded directly as the same Event type.
            self.events = None
            self._external_events: list[Event] = []
            self.handshake.reset()
        else:
            self.events = EventLog(self.rig.line)
            self.rig.line.command_sink = self.events.record_command
            self.events.sample(self.rig.plant.time_s)
        self.violation: str | None = None
        self._pending: list[tuple[str, Callable[[], None]]] = []
        self._last_controller_write_t = 0.0
        self._watchdog_tripped = False
        # The active guided walkthrough (walkthroughs.py), or None:
        # {"id", "index", "mark" (event count when the step began), "then"}.
        self.tour: dict | None = None

    def _event_list(self) -> list[Event]:
        return self._external_events if self.external else self.events.events

    def note_controller_write(self) -> None:
        """Called by the Modbus data store whenever the external controller
        writes an output -- the watchdog heartbeat."""
        with self._lock:
            self._last_controller_write_t = self.rig.plant.time_s
            self._watchdog_tripped = False

    # ---- inputs (validated immediately, applied at the next tick) ------

    def _refuse_while_verifying(self) -> None:
        if self.verifying:
            raise ValueError(f"a scenario verification is running ({self.verifying}); wait for its result")

    def command(self, name: str) -> None:
        self._refuse_while_verifying()
        if name not in COMMANDS:
            raise ValueError(f"unknown command {name!r} (known: {', '.join(COMMANDS)})")
        with self._lock:
            if self.external:
                self._pending.append((name, lambda: self.handshake.request(name)))
            else:
                self._pending.append((name, getattr(self.rig.line, name)))

    def setpoint(self, name: str, value: object) -> None:
        """An HMI setpoint: the source bin ("A" / "B" / "C"), a recipe weight
        (recipe_a_kg / recipe_b_kg / recipe_c_kg, kg) or the batch hold
        (hold_s). Applied at the next tick like a command; in external mode
        it's entered into the setpoint register the external controller reads."""
        self._refuse_while_verifying()
        if name == "source_bin":
            if value not in ("A", "B", "C"):
                raise ValueError("source_bin takes 'A', 'B' or 'C'")
            raw = "ABC".index(value) + 1
            apply = lambda: self.rig.line.select_source(value)  # noqa: E731
        elif name in ("recipe_a_kg", "recipe_b_kg", "recipe_c_kg", "hold_s"):
            limit = 3_600 if name == "hold_s" else PLANT["hopper_capacity_kg"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= limit:
                raise ValueError(f"{name} takes a number from 0 to {limit:g}")
            raw = round(value)
            if name == "hold_s":
                apply = lambda: self.rig.line.set_hold(value)  # noqa: E731
            else:
                apply = lambda: self.rig.line.set_recipe(name[7].upper(), value)  # noqa: E731
        else:
            raise ValueError(f"unknown setpoint {name!r}")
        label = f"{name} {value}"
        with self._lock:
            if self.external:
                self._pending.append((label, lambda: self.handshake.set_setpoint(name, raw)))
            else:
                self._pending.append((label, apply))

    def setpoint_raw(self, name: str, raw: int) -> None:
        """A setpoint written over Modbus (built-in mode's HMI registers)."""
        if name == "source_bin":
            if raw not in (1, 2, 3):
                raise ValueError(f"setpoint {name}: {raw} is not a bin code (1-3)")
            self.setpoint(name, "ABC"[raw - 1])
        else:
            self.setpoint(name, raw)

    def setpoint_values(self) -> dict[str, int]:
        line = self.rig.line
        return {"source_bin": "ABC".index(line.source_bin) + 1,
                **{f"recipe_{b.lower()}_kg": round(line.recipe[b]) for b in "ABC"}, "hold_s": round(line.hold_s)}

    def stimulus(self, key: str, value: object) -> None:
        self._refuse_while_verifying()
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
        if kind == "instrument":
            # Checked here, not when the tick applies it: a bad request is the
            # caller's error, and must not surface inside the scan.
            io = self.rig.io
            if not isinstance(value, str) or value not in io or not io.tag(value).type.is_input:
                raise ValueError(f"{key} takes an input tag")
            if key == "sensor_failed" and value not in self.rig.plant.instruments.diagnosed \
                    and not isinstance(io.read(value), bool):
                raise ValueError(f"{value} has no channel diagnostic, so it can only stick")
        if kind == "degraded":
            param = {"sensor_noise": "amplitude", "sensor_drift": "rate_per_s", "sensor_slow": "seconds"}[key]
            io = self.rig.io
            if not isinstance(value, dict) or set(value) != {"tag", param}:
                raise ValueError(f"{key} takes {{tag, {param}}}")
            tag, number = value["tag"], value[param]
            if not isinstance(tag, str) or tag not in io or not io.tag(tag).type.is_input:
                raise ValueError(f"{key} takes an input tag")
            if isinstance(number, bool) or not isinstance(number, (int, float)) or (key != "sensor_drift" and number <= 0) \
                    or number == 0:
                raise ValueError(f"{key}: {param} must be a non-zero number (positive, except a drift rate)")
            if key != "sensor_slow" and isinstance(io.read(tag), bool):
                raise ValueError(f"{tag} is a switch: {key} applies to an analog reading")
        with self._lock:
            self._pending.append((key, lambda: apply_field(self.rig, key, value)))

    def restart(self) -> None:
        self._refuse_while_verifying()
        with self._lock:
            self._fresh()

    # ---- scenario verification on the live line -----------------------

    def run_live(self, scenario, pace: Callable[[], None] = lambda: None, line_cls=None, progress=None):
        """Run `scenario` through the real scenario runner (runner.execute) on
        this session's own line, so the picture shows the verification as it
        happens. The rig is built exactly as run_scenario() builds it, so the
        result is the run the test suite would record (tests assert the event
        logs are identical). `pace()` is called before every tick: the server
        passes one that follows Run/Pause and the speed selector; tests pass
        nothing and run at full speed."""
        if self.external:
            raise ValueError("live verification needs the built-in controller")
        with self._lock:
            self._refuse_while_verifying()
            self._fresh(line_cls)
            self.verifying = scenario.name
            # Unsampled recorders: execute() takes the first sample itself.
            self.events = EventLog(self.rig.line)
            self.tags = TagHistory(self.rig.io)
        telemetry = _Telemetry(self.events, self.tags)

        def step() -> None:
            pace()
            with self._lock:
                tick(self.rig, DT)
                telemetry.sample(self.rig.plant.time_s)

        try:
            return execute(self.rig, scenario, step, Invariants(self.rig), telemetry, progress=progress)
        finally:
            with self._lock:
                self.invariants = Invariants(self.rig)
                self.verifying = None

    # ---- guided walkthroughs --------------------------------------------

    def start_tour(self, tour_id: str) -> None:
        """Start a walkthrough on a fresh line, so every one begins from the
        same known state."""
        self._refuse_while_verifying()
        if self.external:
            raise ValueError("walkthroughs need the built-in controller")
        if tour_id not in walkthroughs.BY_ID:
            raise ValueError(f"unknown walkthrough {tour_id!r}")
        with self._lock:
            self._fresh()
            self.tour = {"id": tour_id, "index": 0, "mark": len(self._event_list()), "then": ""}

    def tour_do(self) -> None:
        """"Do it for me": queue the current step's actions through the same
        validated command()/stimulus() path every button uses."""
        with self._lock:
            step = self._tour_step()
            if step is None:
                raise ValueError("no walkthrough step to do")
            for key, value in step.do:
                if key in COMMANDS:
                    self.command(key)
                else:
                    self.stimulus(key, value)

    def exit_tour(self) -> None:
        with self._lock:
            self.tour = None

    def _tour_step(self):
        if self.tour is None:
            return None
        steps = walkthroughs.BY_ID[self.tour["id"]].steps
        return steps[self.tour["index"]] if self.tour["index"] < len(steps) else None

    def _advance_tour(self) -> None:
        """Called after every tick: complete the current step if the line has
        actually reached its condition."""
        step = self._tour_step()
        if step is None:
            return
        events = [{"t": e.t, "type": e.type, **e.data} for e in self._event_list()[self.tour["mark"]:]]
        if step.until(self.snapshot(since=len(self._event_list())), events):
            self.tour.update(index=self.tour["index"] + 1, mark=len(self._event_list()), then=step.then)

    def _tour_view(self) -> dict | None:
        if self.tour is None:
            return None
        w = walkthroughs.BY_ID[self.tour["id"]]
        step = self._tour_step()
        return {
            "id": w.id,
            "title": w.title,
            "index": self.tour["index"],
            "total": len(w.steps),
            "then": self.tour["then"],
            "done": step is None,
            "say": step.say if step else "",
            "target": step.target if step else None,
            "can_do": bool(step and step.do),
            "levels": {k: v for k, v in (step.do if step else ()) if k in LEVEL_STIMULI},
        }

    # ---- the scan ------------------------------------------------------

    def step(self) -> None:
        """Advance exactly one tick: apply everything queued since the last
        tick, scan, record telemetry, check invariants. The first
        violation is kept and shown -- the session keeps running (an
        engineer may want to see what happens next), but it's no longer a
        clean run and the banner says so until a restart."""
        with self._lock:
            if self.verifying:
                return  # the verification run is advancing the line itself
            pending, self._pending = self._pending, []
            for _, apply in pending:
                apply()
            if any(key in LEVEL_STIMULI for key, _ in pending):
                self.invariants.rebaseline()
            if self.external:
                self._watchdog()
            tick(self.rig, DT)
            t = self.rig.plant.time_s
            if self.external:
                for key, _ in pending:
                    if key in COMMANDS or key.split(" ")[0] in ("source_bin", "recipe_a_kg", "recipe_b_kg",
                                                                 "recipe_c_kg", "hold_s"):
                        self._external_events.append(Event(t, "command_issued", {"command": key}))
            else:
                self.events.sample(t)
            self.tags.record(t)
            if self.tour is not None:
                self._advance_tour()
            if self.violation is None:
                try:
                    self.invariants.check()
                except InvariantViolation as e:
                    self.violation = f"t={t:.2f}s: {e}"

    def _watchdog(self) -> None:
        io = self.rig.io
        outputs = [n for n in io.names() if not io.tag(n).type.is_input]
        # Only the discrete run/open commands count as "energized": a speed
        # reference left at 100 % with the run command off drives nothing,
        # and counting it made the watchdog trip on an already-stopped line.
        energized = any(io.read(n) for n in outputs if io.tag(n).type.is_discrete)
        if energized and self.rig.plant.time_s - self._last_controller_write_t > WATCHDOG_S:
            for n in outputs:
                io.write_output(n, False if io.tag(n).type.is_discrete else 0.0)
            if not self._watchdog_tripped:
                self._watchdog_tripped = True
                self._external_events.append(
                    Event(self.rig.plant.time_s, "controller_watchdog", {"timeout_s": WATCHDOG_S})
                )

    # ---- outputs -------------------------------------------------------

    def snapshot(self, since: int = 0) -> dict:
        """Everything the page needs to redraw, in the same shape as a
        replay frame (t/state/values/alarms), plus the events recorded
        after index `since` so the browser only fetches what's new."""
        with self._lock:
            line, plant = self.rig.line, self.rig.plant
            events = self._event_list()
            if self.external:
                controller = {
                    "mode": "external", "state": "external", "fault_reason": None,
                    "last_start_refusal": [], "alarms": [], "start_step": None, "line_mode": None,
                    "source_bin": "ABC"[self.handshake.setpoints.get("source_bin", 1) - 1], "active_bin": None,
                    "batch": None,
                }
            else:
                controller = {
                    "mode": "builtin",
                    "state": line.state.name.lower(),
                    # Auto / Manual (docs/CONTROL-LAB.md §6.1). "mode" above is
                    # which controller runs the line, built-in or external.
                    "line_mode": line.mode.name.lower(),
                    "source_bin": line.source_bin,
                    "active_bin": line.active_bin,
                    # Batch mode (master specification, item 7).
                    "batch": {
                        "recipe": dict(line.recipe), "hold_s": line.hold_s,
                        "step": line.batch_step.name.lower() if line.batch_step else None,
                        "loaded_kg": line.batch_loaded_kg, "target_kg": line.batch_target_kg,
                        "completed": line.batches_completed,
                    },
                    "fault_reason": line.fault_reason,
                    "last_start_refusal": list(line.last_start_refusal),
                    "start_step": line.start_step.name.lower() if line.start_step else None,
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
                }
            return {
                **controller,
                "t": plant.time_s,
                "values": self.tags.samples[-1].values,
                "events": [{"t": e.t, "type": e.type, **e.data} for e in events[since:]],
                "event_count": len(events),
                "pending_hmi": self.handshake.outstanding() if self.external else [],
                # inputs queued for the next tick -- visible so a paused line
                # doesn't swallow button presses without a word
                "pending": [key for key, _ in self._pending],
                "injected": {
                    "estop": "tripped" if plant.estop.tripped else "healthy",
                    "conveyor_trip": plant.conveyor.motor.trip_now,
                    "feeder_trip": plant.feeder.motor.trip_now,
                    "conveyor_fail_to_start": plant.conveyor.motor.fail_to_start,
                    "feeder_fail_to_start": plant.feeder.motor.fail_to_start,
                    "gate_stuck": plant.gate.stuck,
                    "gate_b_stuck": plant.gate_b.stuck,
                    "outlet_stuck": plant.outlet.stuck,
                    "outlet_plugged": plant.outlet_plugged,
                    "gate_c_stuck": plant.gate_c.stuck,
                    "belt_slip": plant.conveyor.motion_switch_stuck_false,
                    "conveyor_jam": plant.conveyor.jammed,
                    "bin_bridged": plant.bin.bridged,
                    "feeder_jam": plant.feeder.jammed,
                    # {tag: "stuck" | "failed"} for every unhealthy instrument
                    "instruments": {
                        name: fault.name.lower()
                        for name in self.rig.io.names()
                        if self.rig.io.tag(name).type.is_input
                        and (fault := plant.instruments.fault(name)) is not InstrumentFault.HEALTHY
                    },
                },
                "violation": self.violation,
                "tour": self._tour_view(),
                "verifying": self.verifying,
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
            "walkthroughs": walkthroughs.catalog(),
        }

    def replay_html(self) -> str:
        with self._lock:
            detail = f"invariant violated {self.violation}" if self.violation else "recorded from the live dashboard"
            title = "Live session (external controller)" if self.external else "Live session"
            replay = build_replay(
                title, list(self._event_list()), self.tags, PLANT,
                meta={"file": "live dashboard", "detail": detail},
                initial_state="external" if self.external else "idle",
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
    verifier = verify.Verifier(session, pacer)
    config = session.config() | {"showcase": verify.showcase(), "regressions": verify.regressions(),
                                 "scenario_count": len(list(verify.SCENARIOS_DIR.rglob("*.yaml")))}
    page = assemble("live_template.html").replace(
        "/*__LIVE_CONFIG__*/null", json.dumps(config).replace("</", "<\\/")
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
                state.update(running=pacer.running, speed=pacer.speed, verification=verifier.view())
                state["story"] = narrate(state)
                return self._json(200, state)
            if url.path == "/api/replay/latest":
                if verifier.latest_result is None:
                    return self._json(404, {"error": "no verification has run yet"})
                scenario, result = verifier.latest_result
                first = verifier.latest["runs"][0]
                reg = REGRESSIONS.get(first["regression"]) if first["regression"] else None
                replay = build_replay(scenario.name, result.events, result.tags, PLANT, meta={
                    "passed": result.passed, "file": scenario.path.name, "detail": result.detail,
                    "when_applied_t": result.when_applied_t, "regression_change": reg.change if reg else None},
                    summary=first)
                return self._send(200, render_html(replay).encode("utf-8"), "text/html; charset=utf-8")
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
                elif path == "/api/setpoint":
                    session.setpoint(body.get("name"), body.get("value"))
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
                elif path == "/api/verify":
                    verifier.start(body.get("file"), body.get("runtime") or "python", body.get("regression") or None,
                                   bool(body.get("compare")))
                elif path == "/api/tour":
                    action = body.get("action")
                    if action == "start":
                        session.start_tour(body.get("id"))
                        pacer.running = True  # a walkthrough on a paused line would just sit there
                    elif action == "do":
                        session.tour_do()
                    elif action == "exit":
                        session.exit_tour()
                    else:
                        raise ValueError("action must be start, do or exit")
                else:
                    return self._json(404, {"error": "not found"})
            except (ValueError, json.JSONDecodeError) as e:
                return self._json(400, {"error": str(e)})
            return self._json(200, {"ok": True})

    return Handler
