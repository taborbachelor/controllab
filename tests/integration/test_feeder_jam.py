"""The feeder jam end to end (Phase 4 completion): causality of each claim,
and what telemetry and the Modbus status block record."""
import dataclasses
from pathlib import Path

from services.protocols import controller_status
from services.testing.candidates import review
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario, Stage

REPO = Path(__file__).resolve().parents[2]
TRIP = REPO / "scenarios" / "faults" / "feeder_jam_trips_running.yaml"
RECOVERY = REPO / "scenarios" / "faults" / "feeder_jam_recovery.yaml"


def test_without_the_jam_the_detection_scenario_fails():
    s = Scenario.load(TRIP)
    assert run_scenario(s).passed
    without = run_scenario(dataclasses.replace(s, when={}))
    assert not without.passed and "feeder_flowing" in without.detail


def test_the_review_gate_finds_the_jam_scenarios_non_vacuous():
    for path in (TRIP, RECOVERY):
        result = review(path, [])
        assert result.verdict == "READY FOR REVIEW", [f.message for f in result.findings]


def test_the_refused_reset_is_caused_by_the_jam():
    """Stage 2 claims reset is refused while the chute is plugged. Clear the
    jam in the same press instead, and the very same reset succeeds -- so the
    refusal is the jam's doing, not a reset that never works."""
    s = Scenario.load(RECOVERY)
    cleared_first = dataclasses.replace(s, then=(
        Stage({"feeder_jam": False}, {"latched_alarm_ids": ["LSH-103.JAM"]}, 1.0),  # alarm still unacked
        Stage({"acknowledge": True, "reset": True}, {"line_state": "idle"}, 1.0),
    ))
    assert run_scenario(cleared_first).passed
    still_jammed = dataclasses.replace(s, then=(
        Stage({"acknowledge": True, "reset": True}, {"line_state": "idle"}, 1.0),
    ))
    assert not run_scenario(still_jammed).passed


def test_telemetry_records_the_jam_as_first_out_and_the_fault_with_its_reason():
    result = run_scenario(Scenario.load(TRIP))
    response = [e for e in result.events if e.t > result.when_applied_t]
    activated = [e for e in response if e.type == "alarm_activated"]
    assert [(e.data["alarm_id"], e.data["first_out"]) for e in activated] == [("LSH-103.JAM", True)]
    faulted = [e for e in response if e.type == "state_changed" and e.data["to"] == "faulted"]
    assert faulted and faulted[0].data["fault_reason"] == "feeder jam"


def test_the_status_block_publishes_the_jam_code_and_alarm_bit():
    assert controller_status.FAULT_REASONS.index("feeder jam") == 10
    assert [a[0] for a in controller_status.ALARMS].index("LSH-103.JAM") == 9
    external = run_scenario(Scenario.load(RECOVERY), external=True)  # every expectation read over Modbus
    assert external.passed, external.detail
