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
"""
from __future__ import annotations

from dataclasses import dataclass

from services.testing.invariants import InvariantViolation, Invariants
from services.testing.rig import DT, Rig, build_rig, tick
from services.testing.scenario import Scenario, ScenarioLoadError
from services.testing.vocabulary import ScenarioError, apply_field, read_field, values_match

# Generous safety cap for driving `given.line_state` to its target -- if
# a healthy line can't reach RUNNING this fast, the rig itself is
# misconfigured; this is not a timing assertion under test.
MAX_GIVEN_RUNUP_S = 30.0


@dataclass
class ScenarioResult:
    scenario: Scenario
    passed: bool
    elapsed_s: float
    detail: str


def run_scenario(scenario: Scenario) -> ScenarioResult:
    rig = build_rig()
    invariants = Invariants(rig)

    setup_failure = _apply_given(rig, scenario, invariants)
    if setup_failure is not None:
        return setup_failure

    # Settle: one tick so given's effects (e.g. a direct level write)
    # are fully published through the I/O image before `when` is
    # applied and before anything polls for it -- same reasoning as the
    # tick-before-check rule below, one level up.
    tick(rig, DT)
    try:
        invariants.check()
    except InvariantViolation as e:
        return ScenarioResult(scenario, False, DT, f"invariant violated settling given: {e}")

    try:
        _apply_when(rig, scenario)
    except ScenarioError as e:
        raise ScenarioLoadError(f"{scenario.path}: {e}") from e

    invariants.rebaseline()  # when's own fields are ALSO deliberate setup, not a violation

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
        tick(rig, DT)

        try:
            invariants.check()
        except InvariantViolation as e:
            return ScenarioResult(scenario, False, i * DT, f"invariant violated at t={i * DT:.2f}s: {e}")

        try:
            unmet = _unmet_expectations(rig, scenario)
        except ScenarioError as e:
            raise ScenarioLoadError(f"{scenario.path}: {e}") from e
        if not unmet:
            return ScenarioResult(scenario, True, i * DT, "all expectations met")

    return ScenarioResult(
        scenario, False, scenario.within_s, f"timed out after {scenario.within_s}s -- unmet: {unmet}"
    )


def _apply_given(rig: Rig, scenario: Scenario, invariants: Invariants) -> ScenarioResult | None:
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
        tick(rig, DT)
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
