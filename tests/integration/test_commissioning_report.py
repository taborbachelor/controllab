"""The runner's always-on telemetry and the Markdown report, end to end
against the real scenarios/ directory."""
from pathlib import Path

from services.testing.commissioning_report import render_markdown
from services.testing.report import build_report
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario

SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "scenarios"


def run_all():
    return [(s, run_scenario(s)) for s in Scenario.discover(SCENARIOS_DIR)]


def test_run_scenario_records_setup_and_response_events():
    scenario = Scenario.load(SCENARIOS_DIR / "faults" / "hopper_high_high_trips_running.yaml")
    result = run_scenario(scenario)
    assert result.passed

    setup = [e for e in result.events if e.t <= result.when_applied_t]
    response = [e for e in result.events if e.t > result.when_applied_t]
    assert [e.type for e in setup] == ["command_issued", "state_changed", "state_changed"]
    assert setup[-1].data["to"] == "running"
    assert {(e.type, e.data.get("alarm_id") or e.data.get("to")) for e in response} == {
        ("state_changed", "faulted"),
        ("alarm_activated", "WT-105.HIGH_HIGH"),
    }


def test_the_report_is_byte_identical_across_runs():
    """docs/CONTROL-LAB.md §7 item 3 -- and what makes a committed report
    diffable: a changed line must mean changed behavior."""
    first = render_markdown(build_report(run_all()), SCENARIOS_DIR)
    second = render_markdown(build_report(run_all()), SCENARIOS_DIR)
    assert first == second


def test_the_report_covers_every_scenario_and_passes_today():
    results = run_all()
    md = render_markdown(build_report(results), SCENARIOS_DIR)
    assert "**Overall: PASS**" in md
    for scenario, _ in results:
        assert f"### {scenario.name} — PASS" in md


def test_a_given_precondition_is_seen_by_control_before_when_is_applied():
    """runner.SETTLE_TICKS: a precondition must be in Control's own state
    (here, a latched alarm) during setup, not first appear on the same
    scan that consumes `when`. With a single settle tick this alarm was
    logged as a response event at the tick of the start command."""
    scenario = Scenario.load(SCENARIOS_DIR / "faults" / "hopper_high_high_blocks_start.yaml")
    result = run_scenario(scenario)
    assert result.passed

    activated = [e for e in result.events if e.type == "alarm_activated"]
    assert [e.data["alarm_id"] for e in activated] == ["WT-105.HIGH_HIGH"]
    assert activated[0].t <= result.when_applied_t
