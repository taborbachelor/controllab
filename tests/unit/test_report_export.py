"""The JSON and print-ready HTML commissioning reports
(services/testing/report_export.py): the summary counts the master
specification's report layout asks for, the build stamp, escaping, and that
the HTML is rendered only from the JSON's data."""
import json
from dataclasses import dataclass, field
from pathlib import Path

from services.telemetry.events import Event
from services.testing.commissioning_report import RealtimeConditions
from services.testing.report import build_report
from services.testing.report_export import BuildInfo, build_info, render_html, report_dict
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario

ROOT = Path("/somewhere/on/a/build/machine/scenarios")
SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"


@dataclass
class FakeScenario:
    name: str
    within_s: float = 1.0
    interlock: str | None = None
    path: Path = ROOT / "faults" / "fake.yaml"
    then: tuple = ()
    given: dict = field(default_factory=dict)
    description: str = ""


@dataclass
class FakeResult:
    passed: bool
    elapsed_s: float = 0.3
    detail: str = "all expectations met"
    events: list[Event] = field(default_factory=list)
    when_applied_t: float | None = 1.0
    within_tolerance: bool = False
    not_observable: bool = False
    not_observed: tuple = ()
    stage_elapsed: tuple = ()
    failed_stage: int | None = None
    unmet: dict = field(default_factory=dict)


def data(*pairs, **kw) -> dict:
    return report_dict(build_report(list(pairs)), ROOT, **kw)


def test_the_summary_counts_passes_failures_warnings_and_not_observable_apart():
    d = data(
        (FakeScenario("ok"), FakeResult(True)),
        (FakeScenario("late"), FakeResult(True, within_tolerance=True)),
        (FakeScenario("partial"), FakeResult(True, not_observed=("line_state",))),
        (FakeScenario("bad"), FakeResult(False, detail="timed out", failed_stage=2,
                                         unmet={"line_state": {"expected": "faulted", "actual": "idle"}})),
        (FakeScenario("blind"), FakeResult(False, not_observable=True)),
    )
    assert d["summary"] == {"total": 5, "passed": 3, "failed": 1, "warnings": 2, "not_observable": 1}
    assert d["overall"] == "FAIL"
    assert [f["scenario"] for f in d["critical_failures"]] == ["bad"]  # not observable is not a failure
    assert d["critical_failures"][0]["failed_stage"] == 2
    assert [s["result"] for s in d["scenarios"]] == ["pass", "pass_within_tolerance", "pass", "fail", "not_observable"]


def test_paths_are_relative_and_the_data_is_plain_json():
    d = data((FakeScenario("ok", path=ROOT / "manual" / "x.yaml", given={"line_state": "manual"}), FakeResult(True)))
    assert d["scenarios"][0]["file"] == "manual/x.yaml" and d["scenarios"][0]["mode"] == "Manual"
    text = json.dumps(d)
    assert "somewhere" not in text
    assert json.loads(text) == d


def test_the_build_stamp_says_which_commit_and_whether_it_was_clean():
    assert BuildInfo("0.1.0").label == "controllab 0.1.0"
    assert BuildInfo("0.1.0", "abc1234").label == "controllab 0.1.0, git abc1234"
    assert BuildInfo("0.1.0", "abc1234", dirty=True).label == "controllab 0.1.0, git abc1234 + uncommitted changes"
    d = data((FakeScenario("ok"), FakeResult(True)), build=BuildInfo("0.1.0", "abc1234"))
    assert d["build"]["commit"] == "abc1234"
    assert "Build:</strong> controllab 0.1.0, git abc1234" in render_html(d)


def test_outside_a_git_checkout_the_stamp_has_no_commit(tmp_path):
    """Found writing this test: tmp_path sat inside another git repository,
    and the first version stamped that repository's commit."""
    assert build_info(tmp_path).commit is None


def test_in_this_checkout_the_stamp_has_its_commit():
    info = build_info(SCENARIOS.parent)
    assert info.commit and len(info.commit) >= 7


def test_html_escapes_everything_it_prints_and_runs_no_script():
    d = data((FakeScenario("<script>alert(1)</script> & co"), FakeResult(False, detail="<b>bad</b>")))
    page = render_html(d)
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "<b>bad</b>" not in page


def test_html_follows_the_master_layout_and_prints_to_pdf():
    page = render_html(data((FakeScenario("ok"), FakeResult(True))))
    assert "Tests: 1 total | 1 passed | 0 failed | 0 warnings" in page
    assert "Critical failure summary" in page and "None: no scenario failed." in page
    assert "Operating modes validated" in page and "Auto: 1/1 passed" in page
    assert "@media print" in page and "break-inside: avoid" in page


def test_an_unmet_expectation_is_shown_as_expected_versus_actual_not_a_dict():
    page = render_html(data((FakeScenario("bad"), FakeResult(
        False, failed_stage=2, unmet={"line_state": {"expected": "faulted", "actual": "idle"}}))))
    assert "Line state: expected faulted, actual idle" in page
    assert "{&#x27;" not in page


def test_realtime_conditions_and_each_pass_appear():
    rt = RealtimeConditions(latency_s=0.5, speed=1.0, passes=3, responses={ROOT / "faults" / "fake.yaml": [0.2, 0.3, 0.2]})
    d = data((FakeScenario("ok"), FakeResult(True)), realtime=rt)
    assert d["realtime"] == {"latency_tolerance_s": 0.5, "speed": 1.0, "passes": 3}
    assert d["scenarios"][0]["responses_per_pass_s"] == [0.2, 0.3, 0.2]
    assert "0.20, 0.30, 0.20" in render_html(d)


def test_a_real_run_exports_deterministically_with_readable_events():
    scenarios = [Scenario.load(SCENARIOS / "faults" / "feeder_jam_recovery.yaml"),
                 Scenario.load(SCENARIOS / "manual" / "manual_operation.yaml")]

    def export():
        return report_dict(build_report([(s, run_scenario(s)) for s in scenarios]), SCENARIOS)

    first = export()
    assert json.dumps(first) == json.dumps(export())
    events = first["scenarios"][0]["events"]
    assert events and all("**" not in e["text"] for e in events)
    assert {e["phase"] for e in events} == {"setup", "response"}
    assert render_html(first) == render_html(export())
