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
from services.testing.scenario import GivenUnreachable, Scenario, ScenarioLoadError, Stage
from services.testing.vocabulary import (
    NotObservable,
    ScenarioError,
    StatusWithheld,
    apply_field,
    read_field,
    values_match,
)

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
    # Multi-stage scenarios (`then:`): each stage's response, in order.
    # elapsed_s stays the first stage's, the response to `when`.
    stage_elapsed: tuple[float, ...] = ()
    # Where a failed run departed from the scenario, structured (for reports
    # and for AI run analysis, which must not have to parse `detail`):
    # the stage (1-based), the plant time its `when` was applied, and each
    # expectation still unmet at its deadline as {key: {expected, actual}}.
    failed_stage: int | None = None
    failed_stage_applied_t: float | None = None
    unmet: dict = field(default_factory=dict)


def run_scenario(scenario: Scenario, external: bool = False, status: bool = True, line_cls=None) -> ScenarioResult:
    """`external=True` runs the same scenario against the reference
    external controller across Modbus (Phase 7 step 3b,
    services/testing/external.py): the rig's `line` is then a RemoteLine,
    so every command below goes out as a latched HMI request and every
    controller field the scenario reads comes back from the published
    status registers. Nothing else in this runner changes.

    `status=False` withholds the controller's status (vocabulary.
    StatusWithheld): the scenario is judged on field evidence alone, as
    against a controller that publishes no status block -- deterministic,
    in lockstep, for the suite and the review gate.

    `line_cls` builds a different controller class in-process: only the
    deliberate-regression fixtures (services/testing/regressions.py) use it."""
    if line_cls is not None and external:
        raise ValueError("a regression fixture runs in-process only (line_cls with external=True)")
    if external:
        from services.testing.external import build_external_rig  # protocols only when asked for

        rig = build_external_rig()
    else:
        rig = build_rig(line_cls=line_cls) if line_cls is not None else build_rig()
    try:
        if not status:
            rig.line = StatusWithheld(rig.line)
        telemetry = _Telemetry(EventLog(rig.line, controller_state=status), TagHistory(rig.io))
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
    progress: Callable[[dict], None] | None = None,
) -> ScenarioResult:
    """Runs one scenario on an already-built rig. `step()` must advance
    the plant by exactly one DT and sample `telemetry`; see the module
    docstring for what differs between the modes that call this.

    `progress`, if given, is told as each stage is applied
    ({"event": "stage", "n", "applied_t"}) and as each one passes
    ({"event": "passed", "n", "elapsed"}), so a live view can follow the
    run. It only observes: the run and its result are identical without it."""
    rig.line.command_sink = telemetry.events.record_command
    telemetry.sample(rig.plant.time_s)

    setup_failure = _apply_given(rig, scenario, invariants, step)
    result = setup_failure or _run_from_given(rig, scenario, invariants, step, settle_ticks, tolerance_s,
                                              progress or (lambda _: None))
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
    progress: Callable[[dict], None],
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

    when_applied_t = None
    stages = scenario.stages
    elapsed_by_stage: list[float] = []
    not_observed_all: list[str] = []
    within_tolerance = False
    for n, stage in enumerate(stages, start=1):
        label = f"stage {n}/{len(stages)}: " if len(stages) > 1 else ""
        try:
            for key, value in stage.when.items():
                apply_field(rig, key, value)
        except ScenarioError as e:
            raise ScenarioLoadError(f"{scenario.path}: {label}{e}") from e
        invariants.rebaseline()  # when's own fields are ALSO deliberate setup, not a violation
        if when_applied_t is None:
            when_applied_t = rig.plant.time_s

        stage_applied_t = rig.plant.time_s
        progress({"event": "stage", "n": n, "applied_t": stage_applied_t})
        outcome = _poll_stage(rig, scenario, stage, invariants, step, tolerance_s)
        for key in outcome.not_observed:
            if key not in not_observed_all:
                not_observed_all.append(key)
        common = dict(when_applied_t=when_applied_t, not_observed=tuple(not_observed_all))
        if outcome.not_observable:
            return ScenarioResult(
                scenario, False, 0.0,
                f"{label}not observable: every expectation ({', '.join(outcome.not_observed)}) needs the "
                "controller's status block, which this controller doesn't publish",
                not_observable=True, **common,
            )
        if not outcome.passed:
            return ScenarioResult(
                scenario, False, elapsed_by_stage[0] if elapsed_by_stage else outcome.elapsed,
                label + outcome.detail, failed_stage=n, failed_stage_applied_t=stage_applied_t,
                unmet=outcome.unmet, stage_elapsed=tuple(elapsed_by_stage), **common,
            )
        elapsed_by_stage.append(outcome.elapsed)
        progress({"event": "passed", "n": n, "elapsed": outcome.elapsed})
        within_tolerance = within_tolerance or outcome.within_tolerance

    met = "all observable expectations met" if not_observed_all else "all expectations met"
    if not_observed_all:
        met += f" (not observed: {', '.join(not_observed_all)})"
    first = elapsed_by_stage[0]
    if len(stages) > 1:
        met += " -- stage responses " + ", ".join(
            f"{t:.2f}s/{st.within_s}s" for t, st in zip(elapsed_by_stage, stages)
        )
    elif within_tolerance:
        met += f" at {first:.2f}s: over the {scenario.within_s}s limit, inside the {tolerance_s}s latency tolerance"
    return ScenarioResult(
        scenario, True, first, met, when_applied_t=when_applied_t, within_tolerance=within_tolerance,
        not_observed=tuple(not_observed_all), stage_elapsed=tuple(elapsed_by_stage),
    )


@dataclass
class _StageOutcome:
    passed: bool
    elapsed: float
    detail: str = ""
    within_tolerance: bool = False
    not_observed: tuple[str, ...] = ()
    not_observable: bool = False
    unmet: dict = field(default_factory=dict)


def _poll_stage(
    rig: Rig, scenario: Scenario, stage: Stage, invariants: Invariants, step: Callable[[], None], tolerance_s: float
) -> _StageOutcome:
    # Tick BEFORE checking, every iteration -- not the reverse. Per
    # docs/CONTROL-LAB.md §3.3's scan cycle, Testing applies a stimulus
    # and Simulation advances within the SAME tick; checking before the
    # first tick observes a moment that exists only in this function's
    # Python call order, not one the real system ever passes through
    # (e.g. estop.trip() sets a flag, but nothing forces motors out of
    # RUNNING until Plant.step() actually runs).
    max_ticks = round((stage.within_s + tolerance_s) / DT)
    unmet: dict = {}
    not_observed: tuple[str, ...] = ()
    for i in range(1, max_ticks + 1):
        step()
        try:
            invariants.check()
        except InvariantViolation as e:
            return _StageOutcome(False, i * DT, f"invariant violated at t={i * DT:.2f}s: {e}")
        try:
            unmet, not_observed = _unmet_expectations(rig, stage.expect)
        except ScenarioError as e:
            raise ScenarioLoadError(f"{scenario.path}: {e}") from e
        if stage.expect and len(not_observed) == len(stage.expect):
            return _StageOutcome(False, 0.0, not_observed=not_observed, not_observable=True)
        if not unmet:
            elapsed = round(i * DT, 9)
            return _StageOutcome(True, elapsed, within_tolerance=elapsed > stage.within_s + 1e-9, not_observed=not_observed)
    window = f"{stage.within_s}s" + (f" (+{tolerance_s}s latency tolerance)" if tolerance_s else "")
    return _StageOutcome(
        False, round(stage.within_s + tolerance_s, 9), f"timed out after {window} -- unmet: {unmet}",
        not_observed=not_observed, unmet=unmet,
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


def _unmet_expectations(rig: Rig, expect: dict) -> tuple[dict, tuple[str, ...]]:
    """(unmet expectations, keys that couldn't be observed at all)."""
    unmet = {}
    not_observed = []
    for key, expected in expect.items():
        try:
            actual = read_field(rig, key)
        except NotObservable:
            not_observed.append(key)
            continue
        if not values_match(actual, expected):
            unmet[key] = {"expected": expected, "actual": actual}
    return unmet, tuple(not_observed)
