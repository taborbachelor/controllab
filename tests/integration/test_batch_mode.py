"""Batch mode (completing the master specification, item 7): a recipe across
the three bins, Load -> Process -> Discharge -> Cleanout, the outlet gate,
and the batch over Modbus. The declarative scenarios are in scenarios/batch/;
these pin what they can't: accuracy across recipes, mode changes, trips mid-
batch, and the recipe crossing the wire."""
import pytest

from services.control.line_state import LineMode, LineState, StartInhibit
from services.protocols import controller_status
from services.testing.external import build_external_rig
from services.testing.invariants import Invariants
from services.testing.rig import DT, build_rig, run, tick


def batch_rig(**recipe):
    rig = build_rig()
    rig.line.select_batch()
    tick(rig)
    for bin_, kg in recipe.items():
        rig.line.set_recipe(bin_, kg)
    rig.line.set_hold(1)
    return rig


def run_batch(rig, limit_s=1200.0):  # 1,200 kg: 240 s to load, 400 s to discharge at 3 kg/s
    inv = Invariants(rig)
    rig.line.start()
    for _ in range(round(limit_s / DT)):
        tick(rig)
        inv.check()
        if rig.line.state == LineState.IDLE and rig.line.batches_completed:
            return
    raise AssertionError(f"batch didn't finish: {rig.line.state.name} {rig.line.fault_reason}")


@pytest.mark.parametrize("recipe", [{"A": 300, "B": 200}, {"C": 150}, {"A": 50, "B": 50, "C": 50}, {"B": 1200}])
def test_a_batch_weighs_in_within_tolerance_and_draws_each_bin_its_share(recipe):
    rig = batch_rig(**recipe)
    before = {b: rig.plant.bins[b][0].level_kg for b in "ABC"}
    run_batch(rig)
    line = rig.line
    target = sum(recipe.values())
    assert abs(line.batch_loaded_kg - target) <= line.batch_tolerance_kg
    for b in "ABC":
        drawn = before[b] - rig.plant.bins[b][0].level_kg
        assert drawn == pytest.approx(recipe.get(b, 0), abs=line.batch_tolerance_kg)
    assert rig.plant.hopper.level_kg <= line.batch_empty_kg
    # No trip and no tolerance warning; a big draw can leave its bin low (a warning).
    assert rig.plant.spilled_kg == 0.0 and not line.alarms.any_unacknowledged_trip()
    assert not line.alarms.get("BATCH.TOLERANCE").latched
    assert rig.plant.outlet.is_closed and line.mode == LineMode.BATCH


def test_batches_count_up_and_a_second_batch_needs_no_reset():
    rig = batch_rig(A=100)
    run_batch(rig)
    run_batch(rig)
    assert rig.line.batches_completed == 2


def test_the_mode_changes_between_auto_manual_and_batch_only_at_rest():
    rig = batch_rig(A=300)
    rig.line.select_manual()
    tick(rig)
    assert rig.line.mode == LineMode.MANUAL
    rig.line.select_batch()
    tick(rig)
    rig.line.start()
    run(rig, 2.0)
    assert rig.line.state == LineState.LOADING
    rig.line.select_auto()
    tick(rig)
    assert rig.line.mode == LineMode.BATCH and rig.line.start_inhibit == StartInhibit.LINE_NOT_IDLE


def test_a_batch_start_is_refused_when_a_recipe_bin_is_low_but_not_for_a_bin_it_doesnt_use():
    rig = build_rig(plant_overrides={"bin_c_level_kg": 500.0})  # bin C at 5 %
    rig.line.select_batch()
    tick(rig)
    rig.line.set_recipe("A", 100)
    rig.line.set_recipe("C", 100)
    rig.line.start()
    tick(rig)
    assert StartInhibit.BIN_LOW in rig.line.start_inhibit
    rig.line.set_recipe("C", 0)
    rig.line.start()
    tick(rig)
    assert rig.line.state == LineState.LOADING


def test_a_feeder_trip_mid_batch_faults_clears_the_belt_and_resets_to_batch_mode():
    rig = batch_rig(A=300)
    rig.line.start()
    run(rig, 5.0)
    rig.plant.feeder.motor.trip_now = True
    run(rig, 0.3)
    assert (rig.line.state, rig.line.fault_reason) == (LineState.FAULTED, "feeder trip")
    assert rig.line.clearing_belt  # an upstream trip: the conveyor clears the belt
    rig.plant.feeder.motor.trip_now = False
    rig.plant.feeder.motor.clear_fault()
    run(rig, 3.0)
    rig.line.acknowledge()
    rig.line.reset()
    run(rig, 0.3)
    assert rig.line.state == LineState.IDLE and rig.line.mode == LineMode.BATCH
    rig.line.start()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.HOPPER_NOT_EMPTY  # the partial batch has to go first


def test_the_outlet_in_manual_drains_the_hopper_and_is_refused_in_auto():
    rig = build_rig()
    rig.plant.hopper.level_kg = 200.0
    rig.line.open_outlet()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.WRONG_MODE
    rig.line.select_manual()
    tick(rig)
    rig.line.open_outlet()
    run(rig, 75.0)  # 200 kg at the consumer's 3 kg/s
    assert rig.plant.hopper.level_kg == 0.0
    rig.line.close_outlet()
    run(rig, 1.5)
    assert rig.plant.outlet.is_closed


def test_a_line_without_an_outlet_has_no_batch_mode():
    rig = build_rig()
    line = rig.line
    solo = type(line)(rig.io, line.feeder_ctrl, line.conveyor_ctrl, line.gate_ctrl, hopper_capacity_kg=2_000.0)
    solo.select_batch()
    with pytest.raises(ValueError, match="no hopper outlet gate"):
        solo.scan(DT)


def test_recipe_setpoints_are_validated_and_recorded_once():
    rig = build_rig()
    seen = []
    rig.line.command_sink = seen.append
    rig.line.set_recipe("B", 250)
    rig.line.set_recipe("B", 250)
    rig.line.set_hold(12)
    assert seen == ["recipe B 250 kg", "hold 12 s"]
    with pytest.raises(ValueError):
        rig.line.set_recipe("D", 1)
    with pytest.raises(ValueError):
        rig.line.set_recipe("A", -1)


def test_the_batch_status_round_trips_through_the_status_block():
    rig = batch_rig(A=120)
    run_batch(rig)
    status = controller_status.decode(controller_status.encode(rig.line))
    assert status.batches_completed == 1
    assert status.batch_loaded_kg == pytest.approx(round(rig.line.batch_loaded_kg))
    assert status.mode == LineMode.BATCH


def test_a_recipe_reaches_an_external_controller_and_runs_a_batch_across_modbus():
    rig = build_external_rig()
    try:
        rig.line.select_batch()
        rig.line.set_recipe("B", 100)
        rig.line.set_hold(1)
        for _ in range(3):
            tick(rig)
        controller = rig.line.controller.line
        assert controller.mode == LineMode.BATCH and controller.recipe["B"] == 100 and controller.hold_s == 1
        rig.line.start()
        for _ in range(3000):
            tick(rig)
            if rig.line.batches_completed:
                break
        assert rig.line.batches_completed == 1 and rig.line.state == LineState.IDLE
        assert abs(rig.line.batch_loaded_kg - 100) <= 5
    finally:
        rig.line.close()


def test_a_device_pushbutton_in_batch_mode_is_the_wrong_mode_not_a_fault():
    """Found porting Batch to the PLC: the refusal checked for Auto alone, so
    in Batch mode at rest a device start was reported as 'line faulted'."""
    rig = batch_rig()
    rig.line.start_conveyor()
    tick(rig)
    assert rig.line.start_inhibit == StartInhibit.WRONG_MODE and rig.line.last_start_refusal == [
        "device commands need Manual mode"]
