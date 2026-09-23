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
"""
from __future__ import annotations

from dataclasses import dataclass, field

from services.telemetry.events import Event, EventLog
from services.telemetry.tag_history import TagHistory
from services.testing.invariants import InvariantViolation, Invariants
from services.testing.rig import DT, Rig, build_rig, tick
from services.testing.scenario import Scenario, ScenarioLoadError
from services.testing.vocabulary import ScenarioError, apply_field, read_field, values_match

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
        invariants = Invariants(rig)
        telemetry = _Telemetry(EventLog(rig.line), TagHistory(rig.io))
        rig.line.command_sink = telemetry.events.record_command
        telemetry.sample(rig.plant.time_s)

        setup_failure = _apply_given(rig, scenario, invariants, telemetry)
        result = setup_failure or _run_from_given(rig, scenario, invariants, telemetry)
        result.events = telemetry.events.events
        result.tags = telemetry.tags
        return result
    finally:
        if external:
            rig.line.close()


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


def _run_from_given(rig: Rig, scenario: Scenario, invariants: Invariants, telemetry: _Telemetry) -> ScenarioResult:

    # Settle: SETTLE_TICKS so given's effects (e.g. a direct level
    # write) are published through the I/O image AND scanned by Control
    # before `when` is applied -- same reasoning as the tick-before-check
    # rule below, one level up.
    for i in range(1, SETTLE_TICKS + 1):
        _tick(rig, telemetry)
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
    max_ticks = round(scenario.within_s / DT)
    unmet: dict = {}
    for i in range(1, max_ticks + 1):
        _tick(rig, telemetry)

        try:
            invariants.check()
        except InvariantViolation as e:
            return ScenarioResult(
                scenario, False, i * DT, f"invariant violated at t={i * DT:.2f}s: {e}", when_applied_t=when_applied_t
            )

        try:
            unmet = _unmet_expectations(rig, scenario)
        except ScenarioError as e:
            raise ScenarioLoadError(f"{scenario.path}: {e}") from e
        if not unmet:
            return ScenarioResult(scenario, True, i * DT, "all expectations met", when_applied_t=when_applied_t)

    return ScenarioResult(
        scenario,
        False,
        scenario.within_s,
        f"timed out after {scenario.within_s}s -- unmet: {unmet}",
        when_applied_t=when_applied_t,
    )


def _apply_given(rig: Rig, scenario: Scenario, invariants: Invariants, telemetry: _Telemetry) -> ScenarioResult | None:
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
        _tick(rig, telemetry)
        try:
            invariants.check()
        except InvariantViolation as e:
            return ScenarioResult(scenario, False, i * DT, f"invariant violated reaching given.line_state=running: {e}")
        if rig.line.state.name == "RUNNING":
            return None

    raise ScenarioLoadError(f"{scenario.path}: given.line_state=running was never reached within {MAX_GIVEN_RUNUP_S}s")


def _apply_when(rig: Rig, scenario: Scenario) -> None:
    for key, value in scenario.when.items():
        apply_field(rig, key, value)


def _unmet_expectations(rig: Rig, scenario: Scenario) -> dict:
    unmet = {}
    for key, expected in scenario.expect.items():
        actual = read_field(rig, key)
        if not values_match(actual, expected):
            unmet[key] = {"expected": expected, "actual": actual}
    return unmet
