"""Manual mode (docs/CONTROL-LAB.md §6.1, completing Phase 2): the operator
commands each device, the sequence is bypassed, the protection is not.

Driven through LineController's own pushbuttons against the real simulated
Plant, with the continuous invariants checked on every tick wherever
material moves -- the same three a scenario run checks.
"""
import pytest

from services.control.line_state import LineMode, LineState, StartInhibit
from services.testing.invariants import Invariants
from services.testing.rig import DT, build_rig, run, tick


def manual_rig(**plant_overrides):
    rig = build_rig(plant_overrides=plant_overrides)
    rig.line.select_manual()
    tick(rig)
    assert rig.line.state == LineState.MANUAL
    return rig


def run_checked(rig, seconds: float, inv: Invariants) -> None:
    for _ in range(round(seconds / DT)):
        tick(rig)
        inv.check()


def outputs(rig) -> tuple[bool, bool, bool]:
    """(conveyor run, gate open, feeder run) as commanded -- the field outputs."""
    return rig.io.read("M-104.RUN"), rig.io.read("XV-102.CMD_OPEN"), rig.io.read("M-103.RUN")


def conveyor_running(rig, inv=None) -> None:
    rig.line.start_conveyor()
    if inv is None:
        run(rig, 0.6)
    else:
        run_checked(rig, 0.6, inv)
    assert rig.line.interlocks.conveyor_confirmed_running


def feeding(rig, inv=None) -> None:
    conveyor_running(rig, inv)
    rig.line.open_gate()
    rig.line.start_feeder()
    if inv is None:
        run(rig, 1.5)
    else:
        run_checked(rig, 1.5, inv)
    assert rig.plant.feeder.current_rate_kg_s() > 0


# ---- mode selection ----------------------------------------------------


def test_auto_is_the_default_mode():
    rig = build_rig()
    assert rig.line.mode == LineMode.AUTO
    assert rig.line.state == LineState.IDLE


def test_manual_selected_from_idle_starts_with_everything_off():
    rig = manual_rig()
    assert rig.line.mode == LineMode.MANUAL
    assert rig.line.start_inhibit == StartInhibit.NONE
    run(rig, 2.0)
    assert outputs(rig) == (False, False, False)
    assert rig.line.state == LineState.MANUAL


def test_mode_change_is_refused_while_the_auto_line_runs():
    rig = build_rig()
    rig.line.start()
    run(rig, 3.0)
    assert rig.line.state == LineState.RUNNING

    rig.line.select_manual()
    tick(rig)
    assert rig.line.state == LineState.RUNNING
    assert rig.line.mode == LineMode.AUTO
    assert rig.line.start_inhibit == StartInhibit.LINE_NOT_IDLE
    assert rig.line.last_start_refusal == ["mode change to manual refused: the line is running"]


def test_mode_change_is_refused_while_a_manual_device_is_on_and_accepted_once_all_are_off():
    rig = manual_rig()
    rig.line.open_gate()
    run(rig, 1.5)

    rig.line.select_auto()
    tick(rig)
    assert rig.line.mode == LineMode.MANUAL
    assert rig.line.state == LineState.MANUAL
    assert rig.line.start_inhibit == StartInhibit.LINE_NOT_IDLE
    assert rig.line.last_start_refusal == ["mode change to auto refused: stop every device first"]

    rig.line.close_gate()
    tick(rig)
    rig.line.select_auto()
    tick(rig)
    assert rig.line.mode == LineMode.AUTO
    assert rig.line.state == LineState.IDLE
    assert rig.line.start_inhibit == StartInhibit.NONE


def test_mode_change_is_refused_while_faulted():
    rig = manual_rig()
    rig.plant.gate.stuck = True
    rig.line.open_gate()
    run(rig, 2.5)
    assert rig.line.state == LineState.FAULTED

    rig.line.select_auto()
    tick(rig)
    assert rig.line.mode == LineMode.MANUAL
    assert rig.line.start_inhibit == StartInhibit.LINE_NOT_IDLE


def test_selecting_the_current_mode_is_accepted_and_changes_nothing():
    rig = manual_rig()
    rig.line.select_manual()
    tick(rig)
    assert rig.line.state == LineState.MANUAL
    assert rig.line.start_inhibit == StartInhibit.NONE


# ---- wrong mode: an operator override during Auto is refused -----------


def test_device_commands_in_auto_are_refused_and_reported():
    rig = build_rig()
    for press in (rig.line.start_conveyor, rig.line.open_gate, rig.line.start_feeder):
        press()
        tick(rig)
        assert rig.line.start_inhibit == StartInhibit.WRONG_MODE
        assert rig.line.last_start_refusal == ["device commands need Manual mode"]
    run(rig, 1.0)
    assert outputs(rig) == (False, False, False)
    assert rig.line.state == LineState.IDLE


def test_device_stop_during_an_auto_run_is_ignored_not_obeyed():
    rig = build_rig()
    rig.line.start()
    run(rig, 3.0)
    assert rig.line.state == LineState.RUNNING

    rig.line.stop_feeder()
    rig.line.stop_conveyor()
    run(rig, 0.5)
    assert rig.line.state == LineState.RUNNING
    assert outputs(rig) == (True, True, True)


def test_line_start_in_manual_is_refused():
    rig = manual_rig()
    rig.line.start()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.WRONG_MODE
    run(rig, 3.0)
    assert rig.line.state == LineState.MANUAL
    assert outputs(rig) == (False, False, False)


# ---- a manual cycle ----------------------------------------------------


def test_manual_cycle_moves_material_conserves_it_and_spills_nothing():
    rig = manual_rig()
    inv = Invariants(rig)

    feeding(rig, inv)
    run_checked(rig, 3.0, inv)  # past the belt transit
    assert rig.plant.hopper.level_kg > 0.0

    # Stop upstream first by hand, let the belt clear, then stop it.
    rig.line.stop_feeder()
    rig.line.close_gate()
    run_checked(rig, 3.0, inv)
    assert rig.plant.conveyor.mass_on_belt_kg == pytest.approx(0.0, abs=1e-9)
    rig.line.stop_conveyor()
    run_checked(rig, 1.0, inv)

    assert outputs(rig) == (False, False, False)
    assert rig.line.state == LineState.MANUAL
    assert rig.plant.spilled_kg == 0.0

    rig.line.select_auto()
    tick(rig)
    assert rig.line.state == LineState.IDLE


def test_manual_cycle_is_deterministic():
    def cycle():
        rig = manual_rig()
        feeding(rig)
        run(rig, 2.0)
        rig.line.stop()
        run(rig, 1.0)
        return rig.plant.hopper.level_kg, rig.plant.bin.level_kg, rig.plant.conveyor.mass_on_belt_kg, rig.line.state

    assert cycle() == cycle()


def test_gate_strokes_on_its_own_as_a_limit_switch_check():
    rig = manual_rig()
    rig.line.open_gate()
    run(rig, 1.5)
    assert rig.io.read("ZSO-102") and not rig.io.read("ZSC-102")
    rig.line.close_gate()
    run(rig, 1.5)
    assert rig.io.read("ZSC-102") and not rig.io.read("ZSO-102")
    assert rig.line.state == LineState.MANUAL
    assert rig.plant.bin.level_kg == 2_000.0  # a gate alone moves nothing


def test_line_stop_in_manual_stops_every_device():
    rig = manual_rig()
    feeding(rig)
    rig.line.stop()
    tick(rig)
    assert outputs(rig) == (False, False, False)
    assert rig.line.state == LineState.MANUAL


def test_a_stop_and_a_start_in_the_same_scan_leave_the_device_stopped():
    rig = manual_rig()
    rig.line.start_conveyor()
    rig.line.stop_conveyor()
    run(rig, 1.0)
    assert outputs(rig) == (False, False, False)


# ---- protection still enforced ------------------------------------------


def test_feeder_start_is_refused_without_the_conveyor_proven():
    rig = manual_rig()
    rig.line.open_gate()
    run(rig, 1.5)
    rig.line.start_feeder()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.CONVEYOR_NOT_RUNNING
    assert rig.line.last_start_refusal == ["conveyor not proven running"]
    run(rig, 1.0)
    assert not rig.io.read("M-103.RUN")
    assert rig.plant.spilled_kg == 0.0


def test_feeder_start_is_refused_while_the_conveyor_is_still_proving():
    rig = manual_rig()
    rig.line.start_conveyor()
    rig.line.start_feeder()  # the same scan: the belt can't be proven yet
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.CONVEYOR_NOT_RUNNING
    assert rig.io.read("M-104.RUN") and not rig.io.read("M-103.RUN")


def test_stopping_the_conveyor_takes_the_feeder_with_it_without_a_trip():
    rig = manual_rig()
    inv = Invariants(rig)
    feeding(rig, inv)

    rig.line.stop_conveyor()
    tick(rig)
    inv.check()
    assert outputs(rig) == (False, True, False)  # feeder dropped in the same scan
    run_checked(rig, 2.0, inv)
    assert rig.line.state == LineState.MANUAL
    assert rig.line.fault_reason is None


def test_feeder_start_is_refused_at_bin_low():
    rig = manual_rig(bin_level_kg=500.0)  # 5 %
    conveyor_running(rig)
    rig.line.start_feeder()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.BIN_LOW
    assert not rig.io.read("M-103.RUN")


def test_the_high_switch_stops_a_manual_feeder_and_refuses_its_restart_without_a_trip():
    rig = manual_rig()
    feeding(rig)
    rig.plant.hopper.level_kg = 1_700.0  # 85 %: past LSH-105, under high-high
    run(rig, 0.3)
    assert rig.line.state == LineState.MANUAL
    assert rig.io.read("M-104.RUN") and not rig.io.read("M-103.RUN")  # conveyor keeps running

    rig.line.start_feeder()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.HOPPER_HIGH
    assert rig.line.last_start_refusal == ["hopper at the high switch"]
    assert not rig.io.read("M-103.RUN")


def test_manual_has_no_level_control_the_feeder_stays_stopped_below_the_restart_point():
    rig = manual_rig()
    feeding(rig)
    rig.plant.hopper.level_kg = 1_700.0
    run(rig, 0.3)
    rig.plant.hopper.level_kg = 500.0  # 25 %: Auto would restart below 60 %
    run(rig, 1.0)
    assert not rig.io.read("M-103.RUN")


def test_high_high_at_rest_refuses_starts_but_does_not_trip():
    rig = manual_rig()
    rig.plant.hopper.level_kg = 1_950.0  # 97.5 %
    run(rig, 0.3)
    assert rig.line.state == LineState.MANUAL

    rig.line.start_conveyor()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.HOPPER_HIGH_HIGH | StartInhibit.UNACKNOWLEDGED_ALARM
    assert not rig.io.read("M-104.RUN")


def test_an_unacknowledged_trip_alarm_refuses_motor_starts_but_not_a_gate_stroke():
    rig = manual_rig()
    rig.plant.hopper.level_kg = 1_950.0
    run(rig, 0.3)
    rig.plant.hopper.level_kg = 1_000.0  # cleared, but the alarm is still unacknowledged
    run(rig, 0.3)

    rig.line.start_conveyor()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.UNACKNOWLEDGED_ALARM
    rig.line.open_gate()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.NONE
    assert rig.io.read("XV-102.CMD_OPEN") and not rig.io.read("M-104.RUN")

    rig.line.acknowledge()
    rig.line.start_conveyor()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.NONE
    assert rig.io.read("M-104.RUN")


def test_conveyor_start_is_refused_with_the_hopper_weight_failed():
    rig = manual_rig()
    rig.plant.instruments.fail("WT-105")
    run(rig, 0.3)
    rig.line.acknowledge()
    rig.line.start_conveyor()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.SENSOR_FAILED
    assert not rig.io.read("M-104.RUN")


# ---- trips from MANUAL go to FAULTED, exactly as in Auto ------------------


def test_belt_slip_in_manual_trips_the_line():
    rig = manual_rig()
    feeding(rig)
    rig.plant.conveyor.motion_switch_stuck_false = True
    run(rig, 0.3)
    assert rig.line.state == LineState.FAULTED
    assert rig.line.fault_reason == "conveyor lost confirmation"
    assert outputs(rig) == (False, False, False)


def test_conveyor_that_never_proves_running_in_manual_trips():
    rig = manual_rig()
    rig.plant.conveyor.motor.fail_to_start = True
    rig.line.start_conveyor()
    run(rig, 1.5)
    assert rig.line.state == LineState.FAULTED
    assert rig.line.fault_reason == "conveyor failed to prove running"
    assert not rig.io.read("M-104.RUN")


def test_conveyor_that_runs_but_never_proves_motion_in_manual_trips():
    rig = manual_rig()
    rig.plant.conveyor.motion_switch_stuck_false = True
    rig.line.start_conveyor()
    run(rig, 1.5)
    assert rig.line.state == LineState.FAULTED
    assert rig.line.fault_reason == "conveyor failed to prove running"


def test_gate_stroke_that_never_arrives_trips():
    rig = manual_rig()
    rig.plant.gate.stuck = True
    rig.line.open_gate()
    run(rig, 2.5)
    assert rig.line.state == LineState.FAULTED
    assert rig.line.fault_reason == "gate travel fault"


def test_high_high_while_conveying_in_manual_trips_and_stops_the_conveyor_at_once():
    rig = manual_rig()
    feeding(rig)
    rig.plant.hopper.level_kg = 1_950.0
    run(rig, 0.3)
    assert rig.line.state == LineState.FAULTED
    assert rig.line.fault_reason == "hopper high-high"
    assert outputs(rig) == (False, False, False)


def test_feeder_trip_in_manual_clears_the_belt_then_resets_to_manual_with_nothing_running():
    rig = manual_rig()
    inv = Invariants(rig)
    feeding(rig, inv)

    rig.plant.feeder.motor.trip_now = True
    run_checked(rig, 0.3, inv)
    assert rig.line.state == LineState.FAULTED
    assert rig.line.fault_reason == "feeder trip"
    assert rig.line.clearing_belt  # upstream trip: the conveyor clears the belt
    assert outputs(rig) == (True, False, False)
    run_checked(rig, 2.5, inv)
    assert not rig.io.read("M-104.RUN")

    rig.plant.feeder.motor.trip_now = False
    rig.plant.feeder.motor.clear_fault()
    run(rig, 0.3)
    rig.line.acknowledge()
    rig.line.reset()
    run(rig, 0.3)
    assert rig.line.state == LineState.MANUAL
    assert rig.line.mode == LineMode.MANUAL
    run(rig, 1.0)
    assert outputs(rig) == (False, False, False)
    assert rig.plant.spilled_kg == 0.0


def test_device_starts_while_faulted_in_manual_mode_are_refused_as_faulted():
    rig = manual_rig()
    rig.plant.gate.stuck = True
    rig.line.open_gate()
    run(rig, 2.5)
    rig.line.start_conveyor()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.LINE_FAULTED
    assert not rig.io.read("M-104.RUN")


# ---- E-stop -------------------------------------------------------------


def test_estop_in_manual_holds_everything_off_and_reset_returns_to_manual():
    rig = manual_rig()
    inv = Invariants(rig)
    feeding(rig, inv)

    rig.plant.estop.trip()
    run_checked(rig, 0.3, inv)
    assert rig.line.state == LineState.ESTOPPED
    assert outputs(rig) == (False, False, False)

    rig.line.start_conveyor()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.ESTOP_ACTIVE

    rig.plant.estop.reset()
    run(rig, 0.2)
    rig.line.acknowledge()
    rig.line.reset()
    run(rig, 0.3)
    assert rig.line.state == LineState.MANUAL
    assert rig.line.mode == LineMode.MANUAL
    run(rig, 1.0)
    assert outputs(rig) == (False, False, False)


# ---- audit trail ----------------------------------------------------------


def test_every_manual_pushbutton_reaches_the_command_sink():
    rig = build_rig()
    pressed = []
    rig.line.command_sink = pressed.append
    for press in (
        rig.line.select_manual, rig.line.start_conveyor, rig.line.open_gate, rig.line.start_feeder,
        rig.line.stop_feeder, rig.line.close_gate, rig.line.stop_conveyor, rig.line.select_auto,
    ):
        press()
    assert pressed == [
        "select_manual", "start_conveyor", "open_gate", "start_feeder",
        "stop_feeder", "close_gate", "stop_conveyor", "select_auto",
    ]
