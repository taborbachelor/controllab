"""Running commissioning scenarios against a FREE-RUNNING external
controller, in real time (docs/CONTROL-LAB.md §10, Phase 9 step 1).

Phase 7's external suite (services/testing/external.py) steps our own
controller in lockstep, in-process. A real PLC can't be stepped: it scans
on its own clock and polls its remote I/O whenever it likes. So here the
plant is the thing that keeps time. RealtimePlant serves a plant-only
rig over Modbus on the port the controller is configured to poll, and
run_realtime() advances it one DT per `DT / speed` wall seconds while the
controller runs free. The scenario runner, vocabulary, invariants,
EventLog and scenario files are the same ones every other mode uses
(runner.execute() with a paced `step`).

What changes, and why each is explicit rather than hidden:

- **Limits are still in plant time, plus a stated tolerance.** Every
  hand-off now waits for a Modbus poll and a controller scan, real I/O
  latency the lockstep suite deliberately lacks. `latency_s` is that
  allowance, in plant seconds: the polling window runs to `within` +
  `latency_s`, and a result met only inside the extra window is
  reported `within_tolerance`, never as on time.
- **The settle before `when` is the same allowance** (lockstep's two
  ticks came from its own scan order; here a precondition reaches the
  controller only after its next poll and scan), and so is the
  feeder-onto-an-unproven-conveyor invariant's grace (Invariants,
  `feeder_grace_ticks`).
- **Every scenario starts from a known state:** a fresh plant, a cold
  restart of the controller (`ControllerUnderTest.restart()`), and the
  operator procedure (acknowledge, reset) until the controller reports a
  clean IDLE. A controller's memory would otherwise leak from one
  scenario into the next: a latched alarm, or `start_inhibit`, which
  holds the outcome of the most recent start request.
- **A run that can't be trusted says so instead of passing or failing
  on the logic.** If the controller stops writing its outputs, the run
  stops there; if the plant falls behind the wall clock (which silently
  speeds up a PLC's wall-clock timers relative to the plant), the run is
  invalid. Either way the result fails with that reason as its detail.
  And a `given.line_state: running` the controller never reaches is a
  failed result about the controller, not a broken scenario file
  (GivenUnreachable).

`speed` above 1 is only valid for a controller whose timers follow the
plant (our reference controller counts DT per scan). A real PLC's timers
run on wall time, so a real PLC runs at 1.
"""
from __future__ import annotations

import itertools
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol

from services.protocols import external_controller
from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.modbus import ModbusClient, ModbusServer
from services.protocols.register_map import HmiHandshake, IOImageDataStore, ModbusIOSync, RegisterMap
from services.simulation.engine.plant_io import scan as plant_scan
from services.telemetry.events import EventLog
from services.telemetry.tag_history import TagHistory
from services.testing.external import ObservedLine
from services.testing.invariants import Invariants
from services.testing.rig import DT, Rig, build_rig
from services.testing.runner import ScenarioResult, _Telemetry, execute
from services.testing.scenario import GivenUnreachable, Scenario

# Default I/O latency allowance, in plant seconds: a Modbus poll plus a
# controller scan on each side of a hand-off. OpenPLC's measured trip
# response was 0.19-0.29 s against lockstep's 0.20 s (examples/openplc).
LATENCY_S = 0.5

# No output write for this long (wall seconds) while a scenario runs: the
# controller is gone, and nothing after that says anything about its logic.
CONTROLLER_SILENCE_S = 1.0

# The plant may fall behind the wall clock by at most this much (wall
# seconds, one tick at 1x) before the run's timing is declared invalid.
MAX_LAG_S = 0.1

# Wall-clock cap on reaching a clean IDLE after a controller restart.
READY_TIMEOUT_S = 15.0


class ControllerUnderTest(Protocol):
    """Whatever runs the control logic. ControlLab reaches it only over
    Modbus; this handle exists solely to cold-restart it between
    scenarios, as a commissioning engineer power-cycles a PLC."""

    name: str

    def restart(self) -> None: ...

    def close(self) -> None: ...


class ReferenceController:
    """ControlLab's own LineController as a free-running external
    controller (services/protocols/external_controller.run), in a thread.
    A restart is a new controller: fresh program state, as after a power
    cycle. `scan_s` above DT models a slower PLC task cycle, and so gives
    the tests genuine I/O latency without a PLC runtime."""

    name = "reference controller (services/protocols/external_controller.py), free-running"

    def __init__(self, port: int, host: str = "127.0.0.1", speed: float = 1.0, scan_s: float = DT) -> None:
        self.host, self.port, self.speed, self.scan_s = host, port, speed, scan_s
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None

    def restart(self) -> None:
        self.close()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=external_controller.run, args=(self.host, self.port, self.speed, self._stop, self.scan_s),
            daemon=True, name="controllab-reference-controller",
        )
        self._thread.start()

    def close(self) -> None:
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=5)
            self._thread = None


class RealtimePlant:
    """The plant side of a real-time run: a plant-only rig served over
    Modbus TCP (outputs writable, HMI commands through the request/ack
    handshake) on the fixed port the controller polls. `fresh()` swaps in
    a new rig without restarting the server, so the controller's
    connection survives from one scenario to the next."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5020, register_map: RegisterMap = LINE_REGISTER_MAP) -> None:
        self.map = register_map
        self.lock = threading.RLock()
        self.handshake = HmiHandshake(register_map.commands)
        self.rig = build_rig(with_controller=False)
        self.writes = 0
        self.last_write = time.monotonic()
        store = IOImageDataStore(
            register_map, lambda: self.rig.io, outputs_writable=True,
            handshake=self.handshake, on_output_write=self._note_write,
        )
        self.server = ModbusServer(store, host=host, port=port, lock=self.lock)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    @property
    def host(self) -> str:
        return self.server.server_address[0]

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def _note_write(self) -> None:  # called under the server's lock
        self.writes += 1
        self.last_write = time.monotonic()

    def fresh(self) -> Rig:
        with self.lock:
            self.rig = build_rig(with_controller=False)
            self.handshake.reset()
            return self.rig

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class _Pacer:
    """The real-time `step`: one plant tick per DT/speed wall seconds.
    Refreshes the controller's published status first (the position a
    lockstep controller scan has in rig.tick()), then advances the plant
    and samples telemetry under the server's lock, so the controller never
    reads a half-applied tick. Never bursts to catch up silently: lag is
    measured, and judged by run_realtime()."""

    def __init__(self, plant: RealtimePlant, rig: Rig, speed: float) -> None:
        self.plant, self.rig = plant, rig
        self.period = DT / speed
        self.telemetry: _Telemetry | None = None
        self.max_lag = 0.0
        self.watching = False  # silence is judged only once the controller is up
        self._next = time.monotonic()

    def ready(self) -> None:
        """The controller is up: from here on, judge the scenario, not the
        power-up. Resync the clock too, or a slow power-up would leave the
        next deadline in the past and the scenario would burst-tick to
        catch up."""
        self.watching, self.max_lag = True, 0.0
        self._next = time.monotonic()

    def step(self) -> None:
        self._next += self.period
        delay = self._next - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            self.max_lag = max(self.max_lag, -delay)
        self.rig.line.refresh()
        with self.plant.lock:
            plant_scan(self.rig.plant, self.rig.io, DT)
            if self.telemetry is not None:
                self.telemetry.sample(self.rig.plant.time_s)
            silent = time.monotonic() - self.plant.last_write > CONTROLLER_SILENCE_S
        if silent and self.watching:
            raise _ControllerSilent(self.rig.plant.time_s)


class _ControllerSilent(Exception):
    def __init__(self, t: float) -> None:
        super().__init__(f"controller stopped writing its outputs (none for {CONTROLLER_SILENCE_S}s) by t={t:.2f}s")


def run_realtime(
    scenario: Scenario,
    plant: RealtimePlant,
    controller: ControllerUnderTest,
    speed: float = 1.0,
    latency_s: float = LATENCY_S,
    ready_timeout_s: float = READY_TIMEOUT_S,
) -> ScenarioResult:
    rig = plant.fresh()
    controller.restart()
    rig.line = ObservedLine(plant.handshake, ModbusIOSync(ModbusClient(plant.host, plant.port), plant.map, rig.io), plant.lock)
    try:
        pacer = _Pacer(plant, rig, speed)
        not_ready = _bring_to_clean_idle(plant, rig, pacer, ready_timeout_s)
        if not_ready is not None:
            return ScenarioResult(scenario, False, 0.0, not_ready)

        latency_ticks = math.ceil(latency_s / DT - 1e-9)
        invariants = Invariants(rig, feeder_grace_ticks=max(1, latency_ticks))
        pacer.telemetry = _Telemetry(EventLog(rig.line), TagHistory(rig.io))
        try:
            result = execute(
                rig, scenario, pacer.step, invariants, pacer.telemetry,
                settle_ticks=max(1, latency_ticks), tolerance_s=latency_s,
            )
        except _ControllerSilent as e:
            result = _invalid(scenario, pacer, str(e))
        except GivenUnreachable:
            result = ScenarioResult(
                scenario, False, 0.0,
                f"controller never reached RUNNING for given.line_state within the runner's run-up cap "
                f"(state {rig.line.state.name}, fault {rig.line.fault_reason!r})",
                events=pacer.telemetry.events.events, tags=pacer.telemetry.tags,
            )
        return _judge_timing(result, pacer)
    finally:
        rig.line.close()


def _bring_to_clean_idle(plant: RealtimePlant, rig: Rig, pacer: _Pacer, timeout_s: float) -> str | None:
    """After a cold restart: wait for the controller's first full scan of
    writes (the status registers read 0 = IDLE until it has written
    anything, so nothing before that is its state), then acknowledge and
    reset, as an operator would, until it reports IDLE with nothing
    latched. A PLC may legitimately boot ESTOPPED, if it scans before its
    first I/O poll (examples/openplc). Returns why it failed, or None.
    Not recorded as part of the scenario: it's the known starting state,
    not the test."""
    with plant.lock:
        writes_at_restart = plant.writes
    deadline = time.monotonic() + timeout_s
    while True:
        with plant.lock:
            # Two writes per scan (coils, then the holding range carrying
            # the status block): > +1 means at least one complete scan.
            written = plant.writes > writes_at_restart + 1
        if written:
            break
        if time.monotonic() > deadline:
            return "controller under test never wrote its outputs after restart -- is it running and polling this plant?"
        pacer.step()
    rig.line.refresh()

    line = rig.line
    for command in itertools.cycle(("acknowledge", "reset")):
        for _ in range(round(0.5 / DT)):
            if line.state.name == "IDLE" and not line.alarms.latched_alarms and not line.handshake.outstanding():
                pacer.ready()
                return None
            if time.monotonic() > deadline:
                latched = sorted(a.id for a in line.alarms.latched_alarms)
                return f"controller never reached a clean IDLE after restart: state {line.state.name}, latched {latched}"
            pacer.step()
        getattr(line, command)()
    raise AssertionError("unreachable")


def _invalid(scenario: Scenario, pacer: _Pacer, why: str) -> ScenarioResult:
    return ScenarioResult(
        scenario, False, 0.0, f"run invalid, not a verdict on the logic: {why}",
        events=pacer.telemetry.events.events, tags=pacer.telemetry.tags,
    )


def _judge_timing(result: ScenarioResult, pacer: _Pacer) -> ScenarioResult:
    if pacer.max_lag > MAX_LAG_S:
        result.passed = False
        result.detail = (
            f"run invalid, not a verdict on the logic: the plant fell {pacer.max_lag:.3f}s behind real time "
            f"(limit {MAX_LAG_S}s), so a wall-clock controller's timers ran fast against it (was: {result.detail})"
        )
    return result


@dataclass
class RepeatedRuns:
    """One scenario run N times against a free-running controller (Phase 9
    step 2). Real time isn't bit-exact, so repeatability is measured: the
    spread of response times, and whether every run passed."""

    scenario: Scenario
    runs: list[ScenarioResult]

    @property
    def responses(self) -> list[float | None]:
        """Response time of each run in order; None where it failed."""
        return [r.elapsed_s if r.passed else None for r in self.runs]

    def combined(self) -> ScenarioResult:
        """One result for the coverage matrix and the report: passed only
        if every run passed. It carries the worst run's record -- the
        first failure, or else the slowest pass -- so what the report
        shows is the case that needs looking at, never the best one."""
        failures = [(i, r) for i, r in enumerate(self.runs, 1) if not r.passed]
        if failures:
            i, first = failures[0]
            detail = first.detail
            if len(self.runs) > 1:
                detail = f"failed {len(failures)}/{len(self.runs)} runs; first failure (run {i}): {detail}"
            return replace(first, detail=detail)
        slowest = max(self.runs, key=lambda r: r.elapsed_s)
        return replace(slowest, within_tolerance=any(r.within_tolerance for r in self.runs))


def run_suite_realtime(
    scenarios: list[Scenario],
    plant: RealtimePlant,
    controller: ControllerUnderTest,
    repeat: int = 1,
    speed: float = 1.0,
    latency_s: float = LATENCY_S,
    on_result: Callable[[int, Scenario, ScenarioResult], None] | None = None,
) -> list[RepeatedRuns]:
    """The whole suite, `repeat` times over (each pass complete before the
    next starts, so the passes are independent), every scenario from its
    own restarted controller. `on_result(pass_number, scenario, result)`
    reports progress; a real PLC takes several seconds per scenario."""
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    collected = [RepeatedRuns(s, []) for s in scenarios]
    for n in range(1, repeat + 1):
        for entry in collected:
            result = run_realtime(entry.scenario, plant, controller, speed=speed, latency_s=latency_s)
            entry.runs.append(result)
            if on_result is not None:
                on_result(n, entry.scenario, result)
    return collected


__all__ = [
    "CONTROLLER_SILENCE_S", "ControllerUnderTest", "LATENCY_S", "MAX_LAG_S",
    "RealtimePlant", "ReferenceController", "RepeatedRuns", "run_realtime", "run_suite_realtime",
]
