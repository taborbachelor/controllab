"""Every refusal reported (2026-09-26): a request the controller can't act
on says so, in any state, and never outlives the run it was about.

The refused Reset itself (CAUSE_STANDING, ESTOP_ACTIVE) is proven
declaratively by the recovery scenarios; these are the cases a scenario
can't express, and the command_refused event the event log derives."""
from pathlib import Path

from services.control.line_state import LineState, StartInhibit, inhibit_names
from services.testing.rig import build_rig, run, tick
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario

SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"


def _running():
    rig = build_rig()
    rig.line.start()
    run(rig, 5.0)
    assert rig.line.state == LineState.RUNNING
    return rig


def test_start_while_running_is_refused_not_dropped():
    rig = _running()
    rig.line.start()
    run(rig, 0.2)
    assert rig.line.state == LineState.RUNNING
    assert inhibit_names(rig.line.start_inhibit) == ["LINE_NOT_IDLE"]
    assert rig.line.last_start_refusal == ["line not at rest: running"]


def test_the_report_is_cleared_when_the_line_comes_to_rest():
    """A refusal from the run just ended no longer describes anything."""
    rig = _running()
    rig.line.start()
    run(rig, 0.2)
    rig.line.stop()
    run(rig, 0.2)
    assert rig.line.state == LineState.STOPPING
    assert rig.line.start_inhibit == StartInhibit.LINE_NOT_IDLE  # still describes the stopping line
    run(rig, 20.0)
    assert rig.line.state == LineState.IDLE
    assert (rig.line.start_inhibit, rig.line.last_start_refusal) == (StartInhibit.NONE, [])


def test_a_refused_reset_says_what_is_still_wrong():
    rig = _running()
    rig.plant.feeder.jammed = True
    run(rig, 2.0)
    assert rig.line.fault_reason == "feeder jam"
    rig.line.reset()
    run(rig, 0.2)
    assert rig.line.state == LineState.FAULTED
    assert rig.line.start_inhibit == StartInhibit.CAUSE_STANDING
    assert rig.line.last_start_refusal == ["trip cause still present: feeder jam"]
    assert rig.line.standing_cause() == "feeder jam"


def test_a_reset_with_nothing_to_reset_is_accepted_and_does_nothing():
    rig = build_rig(plant_overrides={"bin_level_kg": 500.0})
    run(rig, 0.2)
    rig.line.start()
    run(rig, 0.2)
    assert rig.line.start_inhibit == StartInhibit.BIN_LOW
    rig.line.reset()
    run(rig, 0.2)
    assert rig.line.state == LineState.IDLE
    assert (rig.line.start_inhibit, rig.line.last_start_refusal) == (StartInhibit.NONE, [])


def test_a_manual_request_in_the_scan_that_trips_is_refused_as_faulted():
    """The trip returns before the requests are acted on; they are still
    reported, so start_inhibit never goes stale behind a consumed request."""
    rig = build_rig()
    rig.line.select_manual()
    run(rig, 0.2)
    rig.line.start_conveyor()
    run(rig, 3.0)
    rig.plant.conveyor.motor.trip_now = True
    tick(rig)  # the plant publishes the overload
    rig.line.start_feeder()
    tick(rig)  # the scan that trips consumes the request
    assert rig.line.fault_reason == "conveyor trip"
    assert rig.line.start_inhibit == StartInhibit.LINE_FAULTED
    assert not rig.line.feeder_ctrl.commanded_run


def test_a_device_start_and_its_stop_in_one_scan_is_reported_accepted():
    rig = build_rig()
    rig.line.select_manual()
    run(rig, 0.2)
    rig.line.start_feeder()  # refused: no belt
    run(rig, 0.2)
    assert StartInhibit.CONVEYOR_NOT_RUNNING in rig.line.start_inhibit
    rig.line.start_feeder()
    rig.line.stop_feeder()  # the stop wins: nothing to refuse
    run(rig, 0.2)
    assert rig.line.start_inhibit == StartInhibit.NONE


def test_the_event_log_records_each_refusal_and_only_refusals():
    result = run_scenario(Scenario.load(SCENARIOS / "faults" / "feeder_jam_recovery.yaml"))
    refused = [e.data for e in result.events if e.type == "command_refused"]
    assert refused == [{"commands": ["reset"], "inhibit": ["CAUSE_STANDING"]}]
    issued = [e for e in result.events if e.type == "command_issued"]
    at = next(i for i, e in enumerate(result.events) if e.type == "command_refused")
    assert result.events[at - 1] in issued  # right after the request it answers, same tick
    assert result.events[at - 1].t == result.events[at].t
