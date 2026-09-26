"""LineController.preview(): what a request would get, asked before the
press (the frontend redesign's permissive preview). The contract, tested
over every scenario in the suite:

- at every point a refusable request is issued, the preview taken then
  (between scans, as an HMI would) equals the outcome the controller
  reports once it consumes the request: accepted or not, the same inhibit
  bits, the same reasons;
- previewing every command leaves the controller bit-for-bit unchanged.
"""
from enum import Enum
from pathlib import Path

import pytest

from services.control.line_controller import COMMANDS, LineController
from services.control.line_state import LineState, Preview, StartInhibit
from services.telemetry.events import REFUSABLE
from services.testing.rig import build_rig, run
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario

SCENARIOS = Scenario.discover(Path(__file__).resolve().parents[2] / "scenarios")


def _freeze(obj, seen=None):
    """A comparable fingerprint of an object graph's data (callables skipped)."""
    seen = set() if seen is None else seen
    if obj is None or isinstance(obj, (bool, int, float, str, Enum)):
        return obj
    if isinstance(obj, (list, tuple, set, frozenset)):
        items = [_freeze(v, seen) for v in obj]
        return tuple(sorted(items, key=repr)) if isinstance(obj, (set, frozenset)) else tuple(items)
    if isinstance(obj, dict):
        return tuple(sorted((repr(k), _freeze(v, seen)) for k, v in obj.items()))
    if callable(obj) or not hasattr(obj, "__dict__"):
        return "<opaque>"
    if id(obj) in seen:
        return "<seen>"
    seen.add(id(obj))
    return (type(obj).__name__, tuple(sorted((k, _freeze(v, seen)) for k, v in vars(obj).items())))


class PreviewRecorder(LineController):
    """The production controller, checking its own previews as it runs."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.pending: list[tuple[str, Preview]] = []
        self.compared = 0
        self.mismatches: list[str] = []
        self.side_effects: list[str] = []

    def _emit_command(self, command: str) -> None:
        if command in REFUSABLE:
            before = _freeze(self)
            previews = {c: self.preview(c) for c in sorted(COMMANDS) if not (c == "select_batch" and self.outlet_ctrl is None)}
            if _freeze(self) != before:
                self.side_effects.append(command)
            self.pending.append((command, previews[command]))
        super()._emit_command(command)

    def scan(self, dt: float) -> None:
        super().scan(dt)
        if len(self.pending) == 1:  # two requests in one scan report one combined outcome
            command, preview = self.pending[0]
            outcome = Preview(accepted=not self.last_start_refusal, inhibit=self.start_inhibit,
                              reasons=tuple(self.last_start_refusal))
            self.compared += 1
            if preview != outcome:
                self.mismatches.append(f"{command}: preview {preview} != outcome {outcome}")
        self.pending.clear()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_the_preview_equals_the_outcome_and_changes_nothing(scenario):
    recorders: list[PreviewRecorder] = []

    class Recorder(PreviewRecorder):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            recorders.append(self)

    result = run_scenario(scenario, line_cls=Recorder)
    assert result.passed, result.detail  # recording changes nothing about the run
    (line,) = recorders
    assert line.mismatches == []
    assert line.side_effects == []


def test_the_suite_exercises_the_comparison():
    """Not vacuous: the scenarios issue refusable requests, refused ones among them."""
    compared = refused = 0
    for scenario in SCENARIOS:
        recorders: list[PreviewRecorder] = []

        class Recorder(PreviewRecorder):
            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, **kwargs)
                recorders.append(self)

            def scan(self, dt: float) -> None:
                nonlocal refused
                refused += sum(1 for _, p in self.pending if not p.accepted) if len(self.pending) == 1 else 0
                super().scan(dt)

        run_scenario(scenario, line_cls=Recorder)
        compared += recorders[0].compared
    assert compared > 100 and refused > 20, (compared, refused)


def test_a_preview_names_what_a_reset_is_waiting_for():
    rig = build_rig()
    rig.line.start()
    run(rig, 5.0)
    rig.plant.feeder.jammed = True
    run(rig, 2.0)
    assert rig.line.state == LineState.FAULTED
    assert rig.line.preview("reset") == Preview(False, StartInhibit.CAUSE_STANDING,
                                                ("trip cause still present: feeder jam",))
    assert rig.line.preview("start") == Preview(False, StartInhibit.LINE_FAULTED, ("line faulted: feeder jam",))
    assert rig.line.preview("acknowledge").accepted
    rig.plant.feeder.jammed = False
    run(rig, 1.0)
    assert rig.line.preview("reset").accepted


def test_an_unknown_command_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="no operator command"):
        build_rig().line.preview("launch")
