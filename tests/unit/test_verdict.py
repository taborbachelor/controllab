"""Run summaries (services/testing/verdict.py) report only what the runner
recorded: checked here against real passing and failing runs."""
from pathlib import Path

import pytest

from services.control.line_controller import LineController
from services.testing.regressions import REGRESSIONS
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario, ScenarioLoadError
from services.testing.verdict import (LABELS, classify, describe_action, describe_setup, event_signature, render_text,
                                      summarize)
from services.testing.vocabulary import APPLY_ACTIONS, READ_FIELDS

SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"
JAM = SCENARIOS / "faults" / "feeder_jam_recovery.yaml"


def test_every_read_field_has_a_plain_label_and_every_action_a_kind():
    assert set(LABELS) == set(READ_FIELDS)
    for key in APPLY_ACTIONS:
        for value in (True, False, "tripped", "healthy", "WT-105", 50):
            try:
                assert classify(key, value) in ("operator", "fault", "repair", "process")
                break
            except KeyError:
                pytest.fail(f"{key} is not classified")


def test_every_action_reads_as_a_plain_sentence():
    """The replay page narrates stages with these; a new vocabulary key
    without a phrase fails here, not as a KeyError on someone's page."""
    degraded = {"sensor_noise": {"tag": "WT-105", "amplitude": 30}, "sensor_drift": {"tag": "WT-105", "rate_per_s": -10},
                "sensor_slow": {"tag": "ZSS-104", "seconds": 1.5}, "recipe": {"A": 300, "B": 200},
                "hold_s": 5, "source_bin": "B", "bin_b_level_pct": 30, "bin_c_level_pct": 30}
    for key in APPLY_ACTIONS:
        for value in ((degraded[key],) if key in degraded
                      else (True, False) if key not in ("estop", "sensor_stuck", "sensor_failed", "sensor_restored",
                                                        "hopper_level_pct", "bin_level_pct")
                      else ("tripped", "healthy") if key == "estop" else (50,) if key.endswith("_pct") else ("WT-105",)):
            text = describe_action(key, value)
            assert text and "_" not in text, (key, value, text)
    assert describe_action("feeder_jam", True) != describe_action("feeder_jam", False)
    assert describe_setup({"line_state": "running", "bin_level_pct": 5.0}) == [
        "The line is started and running", "The bin is at 5 % full"]


def test_a_passing_multistage_run():
    scenario = Scenario.load(JAM)
    s = summarize(scenario, run_scenario(scenario), "Python controller", root=SCENARIOS)
    assert s.verdict == "PASS" and s.passed and s.qualifier == ""
    assert [st.status for st in s.stages] == ["passed"] * 6
    assert s.checks_passed == s.checks_evaluated == s.checks_total == 15
    assert s.first_out == "LSH-103.JAM"  # from the event log
    assert s.invariants == "held on every tick" and s.first_divergence is None
    assert s.stages[1].title == "Reset is refused while the chute is still plugged"
    assert s.stages[1].actions[1]["text"] == "Operator presses Reset"
    assert s.setup_text == ["The line is started and running"]
    # stage start times chain: each stage begins when the previous one's checks all held
    for a, b in zip(s.stages, s.stages[1:]):
        assert b.applied_t == pytest.approx(a.applied_t + a.response_s)


def test_a_failing_run_reports_the_real_actual_values_and_the_first_divergence():
    scenario = Scenario.load(JAM)
    result = run_scenario(scenario, line_cls=REGRESSIONS["reset-ignores-jam"].cls)
    s = summarize(scenario, result, "Python controller", regression="reset-ignores-jam")
    assert s.verdict == "FAIL"
    assert [st.status for st in s.stages] == ["passed", "failed", "not_run", "not_run", "not_run", "not_run"]
    failed = s.stages[1]
    by_key = {c.key: c for c in failed.checks}
    assert by_key["line_state"].status == "mismatch" and by_key["line_state"].actual == "idle"  # reset was taken
    assert by_key["any_unacknowledged_trip"].status == "match"  # held at the deadline
    d = s.first_divergence
    assert d["stage"] == 2 and d["t"] == pytest.approx(result.failed_stage_applied_t + 1.0)
    assert {u["key"] for u in d["unmet"]} == set(result.unmet)
    text = render_text(s)
    assert text.startswith("REGRESSION FAILURE") and "Failure detected at: stage 2" in text


class _IgnoresBeltSlip(LineController):
    """Local to this test: never trips while running, so a slipping belt keeps
    being fed -- the runner's feeder invariant has to stop the run."""

    def _running_trip_reason(self):
        return None


def test_an_invariant_failure_marks_the_stage_checks_not_reached(tmp_path):
    p = tmp_path / "slip.yaml"
    p.write_text("name: Slip\ngiven: {line_state: running}\nwhen: {belt_slip: true}\n"
                 "expect: {line_state: faulted}\nwithin: {seconds: 2.0}\n", encoding="utf-8")
    scenario = Scenario.load(p)
    result = run_scenario(scenario, line_cls=_IgnoresBeltSlip)
    assert "invariant violated" in result.detail
    s = summarize(scenario, result, "x")
    assert s.stages[0].status == "failed" and s.stages[0].checks[0].status == "not_reached"
    assert s.invariants.startswith("violated") and s.first_divergence["kind"] == "invariant violated"
    assert s.checks_evaluated == 0  # nothing claimed as matched


def test_status_withheld_checks_are_not_observed_never_matched():
    scenario = Scenario.load(JAM)
    s = summarize(scenario, run_scenario(scenario, status=False), "blind")
    observed = [c for st in s.stages for c in st.checks if c.key == "line_state"]
    assert observed and all(c.status in ("not_observed", "not_run") for c in observed)


def test_the_same_scenario_over_modbus_records_an_identical_event_log():
    scenario = Scenario.load(JAM)
    assert event_signature(run_scenario(scenario)) == event_signature(run_scenario(scenario, external=True))


def test_stage_titles_load_and_unknown_stage_keys_are_still_refused(tmp_path):
    p = tmp_path / "x.yaml"
    p.write_text("name: X\ntitle: first\nwhen: {start: true}\nexpect: {line_state: running}\nwithin: {seconds: 3}\n"
                 "then:\n  - title: second\n    when: {stop: true}\n    expect: {line_state: idle}\n"
                 "    within: {seconds: 3}\n", encoding="utf-8")
    assert [st.title for st in Scenario.load(p).stages] == ["first", "second"]
    p.write_text(p.read_text(encoding="utf-8").replace("  - title: second", "  - titel: second"), encoding="utf-8")
    with pytest.raises(ScenarioLoadError):
        Scenario.load(p)


def test_the_plan_is_the_summary_without_outcomes_and_progress_only_observes():
    """A live view renders plan() before the run and follows execute()'s
    progress; neither may change the run."""
    from services.testing.invariants import Invariants
    from services.testing.rig import build_rig
    from services.testing.runner import _Telemetry, _tick, execute
    from services.telemetry.events import EventLog
    from services.telemetry.tag_history import TagHistory
    from services.testing.verdict import plan

    scenario = Scenario.load(JAM)
    p = plan(scenario, root=SCENARIOS)
    s = summarize(scenario, run_scenario(scenario), "Python controller", root=SCENARIOS)
    assert p["file"] == s.file and p["setup_text"] == s.setup_text
    assert [(st["title"], st["actions"], st["within_s"]) for st in p["stages"]] == [
        (st.title, st.actions, st.within_s) for st in s.stages]
    assert [[c["label"] for c in st["checks"]] for st in p["stages"]] == [[c.label for c in st.checks] for st in s.stages]

    rig = build_rig()
    telemetry = _Telemetry(EventLog(rig.line), TagHistory(rig.io))
    seen = []
    result = execute(rig, scenario, lambda: _tick(rig, telemetry), Invariants(rig), telemetry, progress=seen.append)
    assert [(e["event"], e["n"]) for e in seen] == [(ev, n) for n in range(1, 7) for ev in ("stage", "passed")]
    assert [e["applied_t"] for e in seen if e["event"] == "stage"] == [st.applied_t for st in s.stages]
    assert event_signature(result) == event_signature(run_scenario(scenario))
