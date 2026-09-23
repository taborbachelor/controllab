"""RepeatedRuns.combined() (Phase 9 step 2): N real-time passes of one
scenario collapse to the verdict the coverage matrix and report use."""
from pathlib import Path

from services.testing.realtime import RepeatedRuns
from services.testing.runner import ScenarioResult
from services.testing.scenario import Scenario

SC = Scenario(name="s", path=Path("s.yaml"), given={}, when={}, expect={}, within_s=0.5)


def result(passed, elapsed, detail="all expectations met", tol=False):
    return ScenarioResult(SC, passed, elapsed, detail, within_tolerance=tol)


def test_all_passing_reports_the_slowest_pass():
    combined = RepeatedRuns(SC, [result(True, 0.2), result(True, 0.4), result(True, 0.3)]).combined()
    assert combined.passed and combined.elapsed_s == 0.4


def test_any_pass_inside_the_tolerance_marks_the_whole_scenario():
    combined = RepeatedRuns(SC, [result(True, 0.3), result(True, 0.2, tol=True)]).combined()
    assert combined.passed and combined.within_tolerance


def test_one_failed_pass_fails_the_scenario_and_says_which():
    runs = RepeatedRuns(SC, [result(True, 0.2), result(False, 0.5, "timed out"), result(False, 0.5, "other")])
    combined = runs.combined()
    assert not combined.passed
    assert combined.detail == "failed 2/3 runs; first failure (run 2): timed out"
    assert runs.responses == [0.2, None, None]


def test_a_single_run_keeps_its_own_detail():
    assert RepeatedRuns(SC, [result(False, 0.5, "timed out")]).combined().detail == "timed out"
