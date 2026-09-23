"""Executes a Scenario (CLAUDE.md §10, docs/CONTROL-LAB.md §7) against a
fresh rig: applies `given`, applies `when`, then polls `expect` every
scan until either satisfied (pass) or `within` elapses (fail) — checking
every continuous invariant (services/testing/invariants.py) along the
way, and failing immediately, harder than a timeout, the instant one
trips.

Two distinct kinds of "not passing," on purpose:

- **ScenarioLoadError** — the scenario FILE is broken (bad YAML, an
  unknown vocabulary key, `given.line_state` asking for something
  unreachable). This is a bug in the test itself and propagates as an
  exception — a malformed scenario should fail loudly, not quietly
  report as "the system failed this check."
- **A failed ScenarioResult** — the scenario ran correctly and the
  *system* didn't do what was expected, or an invariant tripped. This is
  a legitimate finding, not an error, and is what the coverage report
  (Phase 3 step 3) counts.

Conservation is checked against a baseline that's reset after each setup
phase (`given`, then `when`), not the mass the rig started with at raw
construction. `given`/`when` fields like `hopper_level_pct` deliberately
preset a vessel level as a Testing stimulus (docs/CONTROL-LAB.md §3.3) —
that's a legitimate setup action, not a physical event, and checking it
against the pristine starting mass would flag every such scenario as
"material appeared from nowhere." See `Invariants.rebaseline()`.

Every run also records telemetry (Phase 5 step 4): an EventLog with the
line's command sink attached, sampled after every tick this runner
drives -- given's run-up, the settle ticks, and the polling loop alike.
Always on, not opt-in: it's in-memory, cheap, and changes nothing about
the run (tests/integration/test_event_log.py proves the sink leaves
Control's behavior identical). The commissioning report reads exactly
what the run produced this way, instead of re-running scenarios through
a second, separately-maintained collection path that could drift.
A TagHistory of every I/O tag is recorded alongside it, sampled at the
same ticks (Phase 6 step 1) -- the replay viewer needs tag values over
time to animate the line, and reads them from the run's own record for
the same no-second-path reason.
`when_applied_t` marks the boundary between setup and the response
under test: events at or before it came from reaching `given`; events
after it are the system's reaction to `when`.

`execute()` is the runner itself, with the one thing that differs
between execution modes passed in: `step`, which advances the rig by
exactly one DT and samples telemetry. Lockstep (run_scenario) ticks
controller and plant back to back; the real-time runner (Phase 9,
services/testing/realtime.py) paces the plant on the wall clock while
the controller free-runs on its own. Every elapsed time is a count of
steps × DT, so both measure in plant time. `tolerance_s` (0 in
lockstep) extends the polling window past `within` by a stated I/O
latency allowance: expectations met inside it pass with
`within_tolerance=True`, never silently as if on time.

Against an external controller that publishes no status block (Phase 9
step 3), an expectation on a controller field (vocabulary.CONTROLLER_
FIELDS) raises NotObservable. It is then not checked -- neither failed
nor counted as met -- and named in `not_observed`. A scenario whose
observable expectations all hold passes *partly observed*; one with no
observable expectation at all is `not_observable`: not a pass, and not a
failure. `given.line_state: running` is then judged from field evidence
(conveyor running, gate open, feeder running), since the controller's
own state can't be read.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from services.telemetry.events import Event, EventLog
from services.telemetry.tag_history import TagHistory
from services.testing.invariants import InvariantViolation, Invariants
from services.testing.rig import DT, Rig, build_rig, tick
from services.testing.scenario import GivenUnreachable, Scenario, ScenarioLoadError
from services.testing.vocabulary import NotObservable, ScenarioError, apply_field, read_field, values_match

# Generous safety cap for driving `given.line_state` to its target -- if
# a healthy line can't reach RUNNING this fast, the rig itself is
# misconfigured; this is not a timing assertion under test.
MAX_GIVEN_RUNUP_S = 30.0

# Ticks given's effects get before `when` is applied. Two, not one,
# because of the scan order inside tick() (rig.py): Control scans FIRST,
# then the plant publishes its inputs. A precondition written into the
# plant (e.g. hopper_level_pct) is published to the I/O image by tick 1,
# but Control only scans that published value on tick 2. With one tick,
# `given` was settled in the I/O image but not in Control's own state:
# a precondition alarm first activated on the same scan that consumed
# `when` (found via the Phase 5 commissioning report -- see
# docs/CONTROL-LAB.md §10).
SETTLE_TICKS = 2


@dataclass
class ScenarioResult:
    scenario: Scenario
    passed: bool
    elapsed_s: float
    detail: str
    events: list[Event] = field(default_factory=list)
    tags: TagHistory | None = None
    when_applied_t: float | None = None  # None: never got past given
    # Met after `within` but inside the latency tolerance (real-time mode
    # only; always False in lockstep, where the tolerance is 0).
    within_tolerance: bool = False
    # Expectations that couldn't be checked: the controller doesn't publish
    # them (Phase 9 step 3). Non-empty on a pass = passed, partly observed.
    not_observed: tuple[str, ...] = ()
    # No expectation was observable at all: neither passed nor failed.
    not_observable: bool = False


def run_scenario(scenario: Scenario, external: bool = False) -> ScenarioResult:
    """`external=True` runs the same scenario against the reference
    external controller across Modbus (Phase 7 step 3b,
    services/testing/external.py): the rig's `line` is then a RemoteLine,
    so every command below goes out as a latched HMI request and every
    controller field the scenario reads comes back from the published
    status registers. Nothing else in this runner changes."""
    if external:
        from services.testing.external import build_external_rig  # protocols only when asked for

        rig = build_external_rig()
    else:
        rig = build_rig()
    try:
        telemetry = _Telemetry(EventLog(rig.line), TagHistory(rig.io))
        return execute(rig, scenario, lambda: _tick(rig, telemetry), Invariants(rig), telemetry)
    finally:
        if external:
            rig.line.close()


def execute(
    rig: Rig,
    scenario: Scenario,
    step: Callable[[], None],
    invariants: Invariants,
    telemetry: "_Telemetry",
    settle_ticks: int = SETTLE_TICKS,
    tolerance_s: float = 0.0,
) -> ScenarioResult:
    """Runs one scenario on an already-built rig. `step()` must advance
    the plant by exactly one DT and sample `telemetry`; see the module
    docstring for what differs between the modes that call this."""
    rig.line.command_sink = telemetry.events.record_command
    telemetry.sample(rig.plant.time_s)

    setup_failure = _apply_given(rig, scenario, invariants, step)
    result = setup_failure or _run_from_given(rig, scenario, invariants, step, settle_ticks, tolerance_s)
    result.events = telemetry.events.events
    result.tags = telemetry.tags
    return result


@dataclass
class _Telemetry:
    """The two Phase 5 recorders, sampled together at every tick this
    runner drives."""

    events: EventLog
    tags: TagHistory

    def sample(self, t: float) -> None:
        self.events.sample(t)
        self.tags.record(t)


def _tick(rig: Rig, telemetry: _Telemetry) -> None:
    tick(rig, DT)
    telemetry.sample(rig.plant.time_s)


def _run_from_given(
    rig: Rig,
    scenario: Scenario,
    invariants: Invariants,
    step: Callable[[], None],
    settle_ticks: int,
    tolerance_s: float,
) -> ScenarioResult:

    # Settle: settle_ticks (SETTLE_TICKS in lockstep) so given's effects (e.g. a direct level
    # write) are published through the I/O image AND scanned by Control
    # before `when` is applied -- same reasoning as the tick-before-check
    # rule below, one level up.
    for i in range(1, settle_ticks + 1):
        step()
        try:
            invariants.check()
        except InvariantViolation as e:
            return ScenarioResult(scenario, False, i * DT, f"invariant violated settling given: {e}")

    try:
        _apply_when(rig, scenario)
    except ScenarioError as e:
        raise ScenarioLoadError(f"{scenario.path}: {e}") from e

    invariants.rebaseline()  # when's own fields are ALSO deliberate setup, not a violation
    when_applied_t = rig.plant.time_s

    # Tick BEFORE checking, every iteration -- not the reverse. Per
    # docs/CONTROL-LAB.md §3.3's scan cycle, Testing applies a stimulus
    # and Simulation advances within the SAME tick; checking before the
    # first tick observes a moment that exists only in this function's
    # Python call order, not one the real system ever passes through
    # (e.g. estop.trip() sets a flag, but nothing forces motors out of
    # RUNNING until Plant.step() actually runs).
    max_ticks = round((scenario.within_s + tolerance_s) / DT)
    unmet: dict = {}
    not_observed: tuple[str, ...] = ()
    for i in range(1, max_ticks + 1):
        step()

        try:
            invariants.check()
        except InvariantViolation as e:
            return ScenarioResult(
                scenario, False, i * DT, f"invariant violated at t={i * DT:.2f}s: {e}", when_applied_t=when_applied_t
            )

        try:
            unmet, not_observed = _unmet_expectations(rig, scenario)
        except ScenarioError as e:
            raise ScenarioLoadError(f"{scenario.path}: {e}") from e
        if scenario.expect and len(not_observed) == len(scenario.expect):
            return ScenarioResult(
                scenario, False, 0.0,
                f"not observable: every expectation ({', '.join(not_observed)}) needs the controller's "
                "status block, which this controller doesn't publish",
                when_applied_t=when_applied_t, not_observed=not_observed, not_observable=True,
            )
        if not unmet:
            elapsed = round(i * DT, 9)
            met = "all observable expectations met" if not_observed else "all expectations met"
            if not_observed:
                met += f" (not observed: {', '.join(not_observed)})"
            if elapsed <= scenario.within_s + 1e-9:
                return ScenarioResult(
                    scenario, True, elapsed, met, when_applied_t=when_applied_t, not_observed=not_observed
                )
            return ScenarioResult(
                scenario,
                True,
                elapsed,
                f"{met} at {elapsed:.2f}s: over the {scenario.within_s}s limit, "
                f"inside the {tolerance_s}s latency tolerance",
                when_applied_t=when_applied_t,
                within_tolerance=True,
                not_observed=not_observed,
            )

    window = f"{scenario.within_s}s" + (f" (+{tolerance_s}s latency tolerance)" if tolerance_s else "")
    return ScenarioResult(
        scenario,
        False,
        round(scenario.within_s + tolerance_s, 9),
        f"timed out after {window} -- unmet: {unmet}",
        when_applied_t=when_applied_t,
        not_observed=not_observed,
    )


def _apply_given(rig: Rig, scenario: Scenario, invariants: Invariants, step: Callable[[], None]) -> ScenarioResult | None:
    """Returns a failed ScenarioResult if an invariant trips while
    reaching `given` (a real finding -- even the baseline setup is
    broken), or None once `given` is successfully established."""
    given = dict(scenario.given)
    line_state = given.pop("line_state", "idle")

    try:
        for key, value in given.items():
            apply_field(rig, key, value)
    except ScenarioError as e:
        raise ScenarioLoadError(f"{scenario.path}: {e}") from e

    invariants.rebaseline()  # given's own fields are deliberate setup, not a violation

    if line_state == "idle":
        return None
    if line_state != "running":
        raise ScenarioLoadError(f"{scenario.path}: unsupported given.line_state: {line_state!r} (known: idle, running)")

    rig.line.start()
    for i in range(1, round(MAX_GIVEN_RUNUP_S / DT) + 1):
        step()
        try:
            invariants.check()
        except InvariantViolation as e:
            return ScenarioResult(scenario, False, i * DT, f"invariant violated reaching given.line_state=running: {e}")
        if _line_running(rig):
            return None

    raise GivenUnreachable(f"{scenario.path}: given.line_state=running was never reached within {MAX_GIVEN_RUNUP_S}s")


def _apply_when(rig: Rig, scenario: Scenario) -> None:
    for key, value in scenario.when.items():
        apply_field(rig, key, value)


def _line_running(rig: Rig) -> bool:
    """The controller's own word when it publishes one; otherwise the
    field evidence of a running line -- conveyor running, gate open,
    feeder running -- which is what an engineer watching the plant
    without an HMI would go by."""
    try:
        return rig.line.state.name == "RUNNING"
    except NotObservable:
        plant = rig.plant
        return plant.conveyor.motor.running and plant.gate.is_open and plant.feeder.motor.running


def _unmet_expectations(rig: Rig, scenario: Scenario) -> tuple[dict, tuple[str, ...]]:
    """(unmet expectations, keys that couldn't be observed at all)."""
    unmet = {}
    not_observed = []
    for key, expected in scenario.expect.items():
        try:
            actual = read_field(rig, key)
        except NotObservable:
            not_observed.append(key)
            continue
        if not values_match(actual, expected):
            unmet[key] = {"expected": expected, "actual": actual}
    return unmet, tuple(not_observed)
