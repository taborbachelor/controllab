"""runner.execute()'s latency tolerance (Phase 9 step 1), checked on the
deterministic lockstep rig so the classification itself is exact: the
real-time runner only supplies a different `step`."""
from pathlib import Path

from services.telemetry.events import EventLog
from services.telemetry.tag_history import TagHistory
from services.testing.invariants import Invariants
from services.testing.rig import build_rig
from services.testing.runner import _Telemetry, _tick, execute
from services.testing.scenario import Scenario


def start_needs_running_within(within_s):
    # A healthy line reaches RUNNING 1.5 s after start (lockstep, test rig).
    return Scenario(
        name="start with a tight limit", path=Path("tight.yaml"), given={},
        when={"start": True}, expect={"line_state": "running"}, within_s=within_s,
    )


def run(scenario, tolerance_s):
    rig = build_rig()
    telemetry = _Telemetry(EventLog(rig.line), TagHistory(rig.io))
    return execute(rig, scenario, lambda: _tick(rig, telemetry), Invariants(rig), telemetry, tolerance_s=tolerance_s)


def test_met_inside_the_limit_is_on_time():
    result = run(start_needs_running_within(3.0), tolerance_s=0.5)
    assert result.passed and not result.within_tolerance
    assert result.elapsed_s == 1.5


def test_met_only_inside_the_tolerance_is_reported_as_such():
    result = run(start_needs_running_within(1.0), tolerance_s=0.5)
    assert result.passed and result.within_tolerance
    assert result.elapsed_s == 1.5
    assert "over the 1.0s limit, inside the 0.5s latency tolerance" in result.detail


def test_beyond_limit_plus_tolerance_fails_and_names_both():
    result = run(start_needs_running_within(0.5), tolerance_s=0.5)
    assert not result.passed and not result.within_tolerance
    assert result.detail.startswith("timed out after 0.5s (+0.5s latency tolerance)")


def test_zero_tolerance_is_the_lockstep_behavior():
    result = run(start_needs_running_within(1.0), tolerance_s=0.0)
    assert not result.passed
    assert result.detail.startswith("timed out after 1.0s --")
