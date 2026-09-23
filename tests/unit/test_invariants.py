import pytest

from services.simulation.equipment.motor import MotorState
from services.testing.invariants import InvariantViolation, Invariants
from services.testing.rig import build_rig


def test_passes_on_a_freshly_built_rig():
    rig = build_rig()
    Invariants(rig).check()  # must not raise


def test_material_conservation_detects_material_appearing_from_nowhere():
    rig = build_rig()
    inv = Invariants(rig)
    inv.check()  # fine so far

    rig.plant.bin.level_kg += 100.0  # material appears out of nowhere
    with pytest.raises(InvariantViolation):
        inv.check()


def test_rebaseline_accepts_a_deliberate_precondition_without_raising():
    """A scenario's given/when can preset a vessel level as a Testing
    stimulus (services/testing/vocabulary.py's hopper_level_pct/
    bin_level_pct) -- that's a legitimate setup action, not a physical
    event. Without rebaseline(), this would look identical to the
    "material appeared from nowhere" case above."""
    rig = build_rig()
    inv = Invariants(rig)
    inv.check()

    rig.plant.hopper.level_kg += 500.0  # a deliberate precondition, not a physics event
    inv.rebaseline()
    inv.check()  # must not raise -- the new total is now the accepted baseline


def test_rebaseline_does_not_mask_a_real_violation_afterward():
    rig = build_rig()
    inv = Invariants(rig)
    rig.plant.hopper.level_kg += 500.0
    inv.rebaseline()
    inv.check()

    rig.plant.bin.level_kg += 100.0  # a second, un-baselined change -- this one's real
    with pytest.raises(InvariantViolation):
        inv.check()


def test_material_conservation_is_unaffected_by_legitimate_transfer():
    """Moving mass between bin/belt/hopper/spilled without changing the
    total must NOT trip the check -- only an actual imbalance should."""
    rig = build_rig()
    inv = Invariants(rig)
    rig.plant.bin.level_kg -= 50.0
    rig.plant.hopper.level_kg += 50.0
    inv.check()  # must not raise


def test_feeder_unconfirmed_tolerates_exactly_one_tick():
    rig = build_rig()
    inv = Invariants(rig)
    rig.plant.feeder.motor.state = MotorState.RUNNING  # force it, bypassing normal sequencing
    # ZSS-104/conveyor never confirmed -- interlocks.conveyor_confirmed_running is False
    inv.check()  # one violating tick: tolerated


def test_feeder_unconfirmed_beyond_one_tick_raises():
    rig = build_rig()
    inv = Invariants(rig)
    rig.plant.feeder.motor.state = MotorState.RUNNING
    inv.check()  # tick 1: tolerated
    with pytest.raises(InvariantViolation):
        inv.check()  # tick 2, still violating: not tolerated


def test_feeder_unconfirmed_counter_resets_once_confirmed():
    rig = build_rig()
    inv = Invariants(rig)
    rig.plant.feeder.motor.state = MotorState.RUNNING

    inv.check()  # violating tick 1 -- tolerated

    # Conveyor becomes genuinely confirmed in between.
    rig.plant.conveyor.motor.state = MotorState.RUNNING
    rig.io.write_input("ZSS-104", True)
    rig.io.write_input("M-104.RUNNING", True)
    inv.check()  # not violating -- counter resets

    rig.plant.conveyor.motor.state = MotorState.STOPPED
    rig.io.write_input("ZSS-104", False)
    rig.io.write_input("M-104.RUNNING", False)
    inv.check()  # violating again, but counter restarted at 1 -- tolerated


def test_no_motor_energized_during_estop_passes_when_healthy():
    rig = build_rig()
    rig.plant.feeder.motor.state = MotorState.RUNNING
    Invariants(rig).check()  # estop healthy -- running is fine


def test_no_motor_energized_during_estop_detects_violation():
    rig = build_rig()
    rig.plant.estop.trip()
    rig.plant.feeder.motor.state = MotorState.RUNNING  # forced, bypassing Plant.step()'s own enforcement
    with pytest.raises(InvariantViolation):
        Invariants(rig).check()


def test_no_motor_energized_during_estop_checks_conveyor_too():
    rig = build_rig()
    rig.plant.estop.trip()
    rig.plant.conveyor.motor.state = MotorState.RUNNING
    with pytest.raises(InvariantViolation):
        Invariants(rig).check()


def test_feeder_unconfirmed_grace_is_configurable_for_real_io_latency():
    """Against a free-running controller over real I/O (Phase 9) the
    reaction also waits for a poll and a scan, so the grace is the stated
    latency allowance in ticks, not lockstep's one scan."""
    rig = build_rig()
    inv = Invariants(rig, feeder_grace_ticks=3)
    rig.plant.feeder.motor.state = MotorState.RUNNING
    for _ in range(3):
        inv.check()  # ticks 1-3: inside the allowance
    with pytest.raises(InvariantViolation, match="more than 3 scans"):
        inv.check()


def test_rebaselining_after_a_spill_keeps_the_spill_accounted_for():
    """Found running the conveyor-trip recovery scenario on OpenPLC: after the
    trip, the feeder ran one more real-time scan and spilled 0.5 kg onto the
    stopped belt (physically genuine, inside the stated latency allowance).
    The next stage's rebaseline then set the baseline to the material still
    IN the system, while the check counts material that has left it too, so
    the already-spilled 0.5 kg read as a conservation failure. The baseline
    must be the accounted total."""
    from services.testing.invariants import Invariants
    from services.testing.rig import build_rig

    rig = build_rig()
    inv = Invariants(rig)
    rig.plant.bin.level_kg -= 0.5  # half a kilogram leaves the bin...
    rig.plant.spilled_kg += 0.5  # ...and lands on the floor
    inv.check()  # conserved: it's accounted as spilled
    inv.rebaseline()  # a later stage's setup
    inv.check()  # still conserved: the spill didn't vanish from the books
