"""Sensor failure end to end (Phase 4 completion)."""
import dataclasses
from pathlib import Path

from services.control.line_state import LineState, StartInhibit
from services.protocols import controller_status
from services.testing.rig import build_rig, run
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario

REPO = Path(__file__).resolve().parents[2]
FAULTS = REPO / "scenarios" / "faults"


def test_a_legitimate_zero_and_a_failed_signal_read_the_same_and_only_the_diagnostic_differs():
    empty, failed = build_rig(), build_rig()
    failed.plant.instruments.fail("WT-105")
    run(empty, 0.2)
    run(failed, 0.2)
    assert empty.io.read("WT-105") == failed.io.read("WT-105") == 0.0
    assert (empty.io.read("WT-105.FLT"), failed.io.read("WT-105.FLT")) == (False, True)
    for rig in (empty, failed):
        rig.line.start()
    run(empty, 0.2)
    run(failed, 0.2)
    assert empty.line.state == LineState.STARTING         # an empty hopper is a fine place to start
    assert failed.line.state == LineState.IDLE            # an unknown hopper is not
    assert StartInhibit.SENSOR_FAILED in failed.line.start_inhibit


def test_a_stuck_transmitter_keeps_reporting_while_the_plant_changes():
    rig = build_rig()
    rig.plant.hopper.level_kg = 500.0
    run(rig, 0.1)
    rig.plant.instruments.stick("WT-105")
    rig.plant.hopper.level_kg = 1500.0
    run(rig, 1.0)
    assert rig.io.read("WT-105") == 500.0 and rig.plant.hopper.level_kg == 1500.0
    assert rig.io.read("WT-105.FLT") is False  # a stuck instrument reports nothing about itself


def test_without_the_injected_fault_each_sensor_scenario_fails():
    for name in ("hopper_weight_failure_trips_running", "hopper_weight_failure_blocks_start",
                 "hopper_weight_failure_recovery"):
        s = Scenario.load(FAULTS / f"{name}.yaml")
        assert run_scenario(s).passed
        given = {k: v for k, v in s.given.items() if k != "sensor_failed"}
        when = {k: v for k, v in s.when.items() if k != "sensor_failed"}
        assert not run_scenario(dataclasses.replace(s, given=given, when=when)).passed, name


def test_without_sticking_the_transmitter_the_stuck_scenario_fails_on_the_reading():
    s = Scenario.load(FAULTS / "hopper_weight_stuck_high_high_still_trips.yaml")
    unstuck = run_scenario(dataclasses.replace(s, when={"hopper_level_pct": 97.5}))
    assert not unstuck.passed and "hopper_weight_agrees" in unstuck.detail


def test_telemetry_and_the_status_block_carry_the_failure():
    result = run_scenario(Scenario.load(FAULTS / "hopper_weight_failure_trips_running.yaml"))
    response = [e for e in result.events if e.t > result.when_applied_t]
    assert ("WT-105.FAIL", True) in [(e.data["alarm_id"], e.data["first_out"]) for e in response
                                     if e.type == "alarm_activated"]
    assert any(e.type == "state_changed" and e.data["fault_reason"] == "hopper weight signal failed"
               for e in response)
    assert controller_status.FAULT_REASONS.index("hopper weight signal failed") == 11
    assert [a[0] for a in controller_status.ALARMS].index("WT-105.FAIL") == 10
    assert int(StartInhibit.SENSOR_FAILED) == 32
    blocked = run_scenario(Scenario.load(FAULTS / "hopper_weight_failure_blocks_start.yaml"), external=True)
    assert blocked.passed, blocked.detail  # the inhibit bit, read back over Modbus
