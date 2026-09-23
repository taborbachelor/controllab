"""Dashboard scenario verification (services/visualization/verify.py and
LiveSession.run_live): the live run IS the suite's run, results are real,
and comparisons say exactly what was compared."""
import pytest

from services.testing.runner import run_scenario
from services.testing.scenario import Scenario
from services.testing.verdict import event_signature
from services.visualization.live import LiveSession
from services.visualization.narrate import narrate
from services.visualization.verify import SCENARIOS_DIR, SHOWCASE, Verifier, showcase

NO_PLC = "http://127.0.0.1:9"  # nothing listens here: OpenPLC "not reachable"


@pytest.mark.parametrize("file", [f for f, _, _ in SHOWCASE])
def test_a_live_verification_records_exactly_the_suites_run(file):
    scenario = Scenario.load(SCENARIOS_DIR / file)
    live = LiveSession().run_live(scenario)
    suite = run_scenario(scenario)
    assert live.passed and suite.passed
    assert event_signature(live) == event_signature(suite)
    assert live.stage_elapsed == suite.stage_elapsed


def test_the_showcase_scenarios_all_explain_themselves():
    for card in showcase():
        assert card["description"] and card["title"] and card["stages"] >= 1
        scenario = Scenario.load(SCENARIOS_DIR / card["file"])
        if len(scenario.stages) > 1:
            assert all(st.title for st in scenario.stages), card["file"]


def test_manual_inputs_are_refused_while_a_verification_owns_the_line():
    s = LiveSession()
    s.verifying = "x"
    for call in (lambda: s.command("start"), lambda: s.stimulus("feeder_trip", True), s.restart,
                 lambda: s.start_tour("normal")):
        with pytest.raises(ValueError, match="verification is running"):
            call()
    t = s.snapshot()["t"]
    s.step()  # the pacer's tick is ignored: the verification advances the line itself
    assert s.snapshot()["t"] == t


def test_a_verification_result_on_the_python_runtime():
    v = Verifier(LiveSession(), plc_url=NO_PLC)
    v.start("faults/feeder_jam_recovery.yaml", background=False)
    (run,) = v.latest["runs"]
    assert run["verdict"] == "PASS" and run["checks_passed"] == run["checks_evaluated"] == 15
    assert run["first_out"] == "LSH-103.JAM" and run["runtime_id"] == "python" and v.busy is None


def test_a_regression_build_fails_with_the_real_divergence():
    v = Verifier(LiveSession(), plc_url=NO_PLC)
    v.start("faults/feeder_jam_recovery.yaml", regression="reset-ignores-jam", background=False)
    (run,) = v.latest["runs"]
    assert run["verdict"] == "FAIL" and run["regression"] == "reset-ignores-jam"
    assert run["first_divergence"]["stage"] == 2


def test_comparing_runtimes_says_what_was_compared_and_what_was_not():
    v = Verifier(LiveSession(), plc_url=NO_PLC)
    v.start("faults/feeder_jam_recovery.yaml", compare=True, background=False)
    rows = v.latest["comparison"]["rows"]
    assert [r["runtime_id"] for r in rows] == ["python", "modbus"]
    assert "identical" in rows[1]["how"] and rows[1]["agrees"] is True
    assert v.latest["comparison"]["all_agree"] is True
    assert v.latest["not_compared"] and "OpenPLC" in v.latest["not_compared"][0]


def test_bad_requests_are_refused():
    v = Verifier(LiveSession(), plc_url=NO_PLC)
    for kwargs in ({"file": "nope.yaml"}, {"file": "../pyproject.toml"}, {"file": SHOWCASE[0][0], "runtime": "cobol"},
                   {"file": SHOWCASE[0][0], "regression": "nope"},
                   {"file": SHOWCASE[0][0], "regression": "jam-trip-removed", "runtime": "modbus"},
                   {"file": SHOWCASE[0][0], "runtime": "openplc"}):
        with pytest.raises(ValueError):
            v.start(background=False, **kwargs)
    assert v.busy is None


def test_the_story_card_says_a_verification_is_running():
    s = LiveSession()
    story = narrate({**s.snapshot(), "running": True,
                     "verification": {"busy": {"scenario": "X", "runtime": "Python controller", "step": 1, "of": 1}}})
    assert story["headline"] == "Verifying: X" and "Manual controls are locked" in story["detail"]


def test_a_live_run_publishes_its_plan_and_follows_it_stage_by_stage():
    """What the dashboard's test view renders while a scenario runs: the plan
    up front, then each stage as it starts and passes."""
    import json

    v = Verifier(LiveSession(), plc_url=NO_PLC)
    seen = []
    run_live = v.session.run_live

    def spy(scenario, pace, line_cls=None, progress=None):
        def follow(e):
            progress(e)
            seen.append(json.loads(json.dumps(v.busy)))  # exactly what /api/state would carry
        return run_live(scenario, pace, line_cls=line_cls, progress=follow)

    v.session.run_live = spy
    v.start("faults/feeder_jam_recovery.yaml", background=False)
    assert seen[0]["plan"]["stages"][1]["title"] == "Reset is refused while the chute is still plugged"
    assert seen[0]["progress"]["stage"] == 1 and seen[0]["progress"]["passed"] == {}
    assert seen[-1]["progress"]["passed"].keys() == {str(n) for n in range(1, 7)}
    assert v.busy is None and v.latest["id"] == seen[0]["id"]  # the result lands under the same run id
