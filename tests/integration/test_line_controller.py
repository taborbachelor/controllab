"""Full-line scenarios driven entirely through LineController against a
real simulated Plant -- the first tests in the repo where nothing calls
Plant's devices, or even the I/O image, directly to make things happen.
Only Testing-style stimuli (fault injection, forcing a level) touch Plant
directly, exactly as docs/CONTROL-LAB.md §3.3 says Testing may.

Every interlock in docs/CONTROL-LAB.md §6.3 gets a test that trips it
(§7, item 4) -- ahead of Phase 3's formal coverage matrix, but no less
real for that.
"""
import pytest

from services.control.line_state import LineState, StartStep
from services.simulation.engine.plant_io import scan as plant_scan
from services.simulation.equipment.gate import GateState
from services.simulation.equipment.motor import MotorState
from services.testing.rig import DT, build_rig


def make_rig(**plant_overrides):
    """Thin wrapper preserving this file's existing (plant, io, line)
    tuple-unpacking shape across all its tests -- the actual rig
    construction and config now live in services/testing/rig.py, shared
    with the Phase 3 scenario runner, so there's one canonical rig
    definition instead of two that could quietly drift apart."""
    rig = build_rig(plant_overrides=plant_overrides)
    return rig.plant, rig.io, rig.line


def tick(plant, io, line, dt: float = DT) -> None:
    line.scan(dt)
    plant_scan(plant, io, dt)


def run(plant, io, line, seconds: float, dt: float = DT) -> None:
    for _ in range(round(seconds / dt)):
        tick(plant, io, line, dt)


# ---- normal cycle -----------------------------------------------------


def test_full_normal_cycle_conserves_material():
    plant, io, line = make_rig()
    starting_total = plant.total_mass_kg()

    line.start()
    run(plant, io, line, 3.0)
    assert line.state == LineState.RUNNING

    run(plant, io, line, 5.0)  # let material actually reach the hopper
    assert plant.hopper.level_kg > 0.0
    assert plant.spilled_kg == 0.0
    assert plant.accounted_mass_kg() == pytest.approx(starting_total)

    line.stop()
    run(plant, io, line, 5.0)  # purge_time_s=2.0 on this rig, plenty of margin
    assert line.state == LineState.IDLE
    assert plant.conveyor.motor.running is False
    assert plant.spilled_kg == 0.0
    assert plant.accounted_mass_kg() == pytest.approx(starting_total)


def test_full_cycle_is_deterministic():
    def run_scenario():
        plant, io, line = make_rig()
        line.start()
        run(plant, io, line, 3.0)
        run(plant, io, line, 5.0)
        line.stop()
        run(plant, io, line, 5.0)
        return plant.hopper.level_kg, plant.spilled_kg, plant.bin.level_kg, line.state

    assert run_scenario() == run_scenario()


def test_start_sequence_is_downstream_first():
    plant, io, line = make_rig()
    line.start()
    tick(plant, io, line)
    assert line.start_step == StartStep.CONVEYOR
    assert plant.conveyor.motor.run_command is True
    assert plant.gate.open_command is False
    assert plant.feeder.motor.run_command is False


# ---- start permissives (docs/CONTROL-LAB.md §6.3) ----------------------


def test_start_refused_when_bin_low():
    plant, io, line = make_rig(bin_level_kg=500.0)  # 5% of 10,000 kg -- under the 10% threshold
    line.start()
    tick(plant, io, line)
    assert line.state == LineState.IDLE
    assert "bin low" in line.last_start_refusal
    assert plant.conveyor.motor.run_command is False


def test_start_refused_when_hopper_high_high():
    plant, io, line = make_rig()
    plant.hopper.level_kg = 1_950.0  # 97.5% -- above the 95% high-high threshold
    tick(plant, io, line)  # publish this reading before requesting a start
    line.start()
    tick(plant, io, line)
    assert line.state == LineState.IDLE
    assert "hopper at high-high" in line.last_start_refusal


def test_start_refusal_reports_multiple_reasons_together():
    plant, io, line = make_rig(bin_level_kg=500.0)
    plant.hopper.level_kg = 1_950.0
    tick(plant, io, line)
    line.start()
    tick(plant, io, line)
    assert line.state == LineState.IDLE
    # "hopper at high-high" is Interlocks' own direct permissive; the WT-105
    # alarm shows up too, since it latched (and hasn't been acknowledged)
    # the same tick -- both are accurate, not a bug (docs/CONTROL-LAB.md
    # §10's Phase 4 step 2 entry).
    assert set(line.last_start_refusal) == {
        "bin low",
        "hopper at high-high",
        "unacknowledged alarm: WT-105.HIGH_HIGH",
    }


# ---- no-op requests -----------------------------------------------------


def test_stop_while_idle_is_a_noop():
    plant, io, line = make_rig()
    line.stop()
    tick(plant, io, line)
    assert line.state == LineState.IDLE


def test_start_while_already_running_is_a_noop():
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 3.0)
    assert line.state == LineState.RUNNING

    line.start()
    tick(plant, io, line)
    assert line.state == LineState.RUNNING


# ---- hopper hysteresis (RUNNING only) -----------------------------------


def test_hysteresis_pauses_and_resumes_the_feeder_while_running():
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 3.0)
    assert line.state == LineState.RUNNING

    # Forcing the level directly tests the hysteresis DECISION, not fill
    # physics -- that's already covered by the Phase 1 conservation tests.
    plant.hopper.level_kg = 1_700.0  # 85% -- above LSH-105's 80%
    tick(plant, io, line)  # this tick: scan() still sees the OLD reading;
    #                        plant_scan() publishes the new one at the end
    assert io.read("LSH-105") is False  # fail-safe: the switch opens at its point
    tick(plant, io, line)  # NOW scan() reacts to it
    assert plant.feeder.motor.run_command is False
    assert plant.conveyor.motor.running is True  # conveyor keeps running
    assert plant.gate.is_open is True  # gate stays open

    plant.hopper.level_kg = 1_000.0  # 50% -- below the 60% restart point
    tick(plant, io, line)
    tick(plant, io, line)
    assert io.read("LSH-105") is True  # closed again: below the switch point
    assert plant.feeder.motor.run_command is True
    assert line.state == LineState.RUNNING  # never left RUNNING for any of this


# ---- STARTING faults ----------------------------------------------------


def test_stop_during_starting_aborts_the_sequence():
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 0.5)
    assert line.state == LineState.STARTING
    assert line.start_step == StartStep.GATE  # conveyor already proven, gate opening

    line.stop()
    tick(plant, io, line)
    assert line.state == LineState.STOPPING

    run(plant, io, line, 3.0)  # purge_time_s=2.0 on this rig
    assert line.state == LineState.IDLE
    assert plant.conveyor.motor.running is False


def test_starting_fault_conveyor_fails_to_prove_running():
    plant, io, line = make_rig()
    plant.conveyor.motor.fail_to_start = True
    line.start()
    run(plant, io, line, 3.0)  # conveyor_proof_timeout_s=1.0
    assert line.state == LineState.FAULTED
    assert line.fault_reason == "conveyor failed to prove running"

    # The actual proof for the "spillage from wrong order" scenario
    # (docs/CONTROL-LAB.md's original Phase 1 test): even when the
    # conveyor never proves running at all, the gate and feeder are
    # NEVER commanded -- not "commanded, then dropped," never touched.
    # There's no code path in LineController that can reach StartStep.GATE
    # or StartStep.FEEDER without StartStep.CONVEYOR succeeding first, so
    # "feeder runs onto an unconfirmed conveyor" isn't a race to lose --
    # it's structurally unreachable. See
    # test_wrong_order_spillage_is_structurally_unreachable_through_control
    # for the direct, deliberate demonstration of the same claim.
    assert plant.gate.state == GateState.CLOSED
    assert plant.feeder.motor.state == MotorState.STOPPED


def test_wrong_order_spillage_is_structurally_unreachable_through_control():
    """The direct contrast for the "spillage from wrong order" scenario
    docs/CONTROL-LAB.md's Phase 1 tests (test_plant.py, test_plant_io.py)
    both demonstrate: real physical spillage when the feeder runs onto a
    stopped conveyor. LineController doesn't prevent that by checking for
    it -- it prevents it by never being ABLE to produce that command
    sequence. Its only public entry points are start()/stop()/reset();
    nothing lets a caller ask it to open the gate or run the feeder ahead
    of the conveyor proving running.

    Proven two ways: (1) start() run to completion, however Testing
    prods it, always reaches RUNNING with zero spillage -- covered by
    every other test in this file that calls start(). (2) reaching around
    LineController and driving the SAME device-control objects it owns
    directly -- exactly what a hostile or buggy caller bypassing it might
    do -- reproduces the spillage instantly. That contrast is the actual
    proof the sequencing is real, not a fluke of the happy path never
    having tried anything else.
    """
    plant, io, line = make_rig()
    line.gate_ctrl.command_open(True)
    line.feeder_ctrl.command_run(True)
    line.feeder_ctrl.command_speed(100.0)
    for _ in range(20):
        line.gate_ctrl.scan(DT)
        line.feeder_ctrl.scan(DT)
        line.conveyor_ctrl.scan(DT)  # never commanded -- conveyor stays stopped
        plant_scan(plant, io, DT)

    assert plant.spilled_kg > 0.0
    assert plant.hopper.level_kg == 0.0


def test_starting_fault_gate_travel_timeout():
    plant, io, line = make_rig()
    plant.gate.stuck = True
    line.start()
    run(plant, io, line, 5.0)  # gate_ctrl travel_timeout_s=2.0
    assert line.state == LineState.FAULTED
    assert line.fault_reason == "gate failed to prove open"
    assert plant.conveyor.motor.run_command is False  # was running -- proves the drop, not just "never was on"


def test_starting_fault_feeder_fails_to_prove_running():
    plant, io, line = make_rig()
    plant.feeder.motor.fail_to_start = True
    line.start()
    run(plant, io, line, 5.0)  # conveyor + gate succeed first, then feeder proof times out
    assert line.state == LineState.FAULTED
    assert line.fault_reason == "feeder failed to prove running"
    # By now conveyor was running and the gate was open -- prove
    # _enter_faulted() actually dropped them, not that they were never on.
    assert plant.conveyor.motor.run_command is False
    assert plant.gate.open_command is False
    assert plant.feeder.motor.run_command is False


def test_starting_fault_trip_mid_sequence():
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 0.5)
    assert line.start_step == StartStep.GATE  # conveyor already proven, gate opening

    plant.conveyor.motor.trip_now = True
    run(plant, io, line, 0.2)
    assert line.state == LineState.FAULTED
    assert line.fault_reason == "conveyor trip"


# ---- RUNNING faults -----------------------------------------------------


def test_running_fault_hopper_high_high():
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 3.0)
    assert line.state == LineState.RUNNING

    plant.hopper.level_kg = 1_950.0  # 97.5% -- above 95%
    run(plant, io, line, 0.3)
    assert line.state == LineState.FAULTED
    assert line.fault_reason == "hopper high-high"
    assert plant.feeder.motor.run_command is False
    assert plant.gate.open_command is False


def test_running_fault_feeder_trip():
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 3.0)
    assert line.state == LineState.RUNNING

    plant.feeder.motor.trip_now = True
    run(plant, io, line, 0.3)
    assert line.state == LineState.FAULTED
    assert line.fault_reason == "feeder trip"


def test_running_fault_conveyor_trip():
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 3.0)
    assert line.state == LineState.RUNNING

    plant.conveyor.motor.trip_now = True
    run(plant, io, line, 0.3)
    assert line.state == LineState.FAULTED
    assert line.fault_reason == "conveyor trip"


def test_running_fault_conveyor_confirmation_loss():
    """Belt slip (docs/CONTROL-LAB.md §5.4): the motor itself is fine,
    but the belt isn't moving. The one fault that specifically proves
    Interlocks.conveyor_confirmed_running's ZSS-104 combination is real,
    not just running-only."""
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 3.0)
    assert line.state == LineState.RUNNING

    plant.conveyor.motion_switch_stuck_false = True
    run(plant, io, line, 0.3)
    assert line.state == LineState.FAULTED
    assert line.fault_reason == "conveyor lost confirmation"
    assert plant.conveyor.motor.fault is False  # the motor itself never tripped
    assert plant.feeder.motor.run_command is False


# ---- STOPPING faults ------------------------------------------------------


def test_stopping_fault_trip_during_purge():
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 3.0)
    assert line.state == LineState.RUNNING

    line.stop()
    tick(plant, io, line)
    assert line.state == LineState.STOPPING

    plant.conveyor.motor.trip_now = True
    run(plant, io, line, 0.3)
    assert line.state == LineState.FAULTED
    assert line.fault_reason == "conveyor trip"


# ---- reset (docs/CONTROL-LAB.md §6.2: cause cleared AND an operator reset) --


def test_reset_refused_while_cause_still_active():
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 3.0)
    plant.hopper.level_kg = 1_950.0
    run(plant, io, line, 0.3)
    assert line.state == LineState.FAULTED

    line.reset()
    tick(plant, io, line)
    assert line.state == LineState.FAULTED  # still high-high -- refused
    assert line.fault_reason == "hopper high-high"


def test_reset_succeeds_once_a_passthrough_cause_clears():
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 3.0)
    plant.feeder.motor.trip_now = True
    run(plant, io, line, 0.3)
    assert line.state == LineState.FAULTED

    # Fixing a real trip means both: the root cause (trip_now) AND the
    # device's own fault latch (clear_fault()) -- clearing only one and
    # not the other would either re-trip immediately or never publish
    # as cleared.
    plant.feeder.motor.trip_now = False
    plant.feeder.motor.clear_fault()
    tick(plant, io, line)  # let the cleared fault tag publish

    line.reset()
    run(plant, io, line, 0.3)
    assert line.state == LineState.IDLE
    assert line.fault_reason is None


def test_reset_from_a_latched_fault_gives_a_fresh_chance_but_a_persistent_problem_refaults():
    """A latched timing diagnostic (gate travel_fault) has no independent
    "still broken" signal Control can check -- reset() clears it
    unconditionally, and if the underlying problem is still there, the
    next start attempt simply fails again on its own. Proves reset()
    doesn't silently paper over a persistent problem."""
    plant, io, line = make_rig()
    plant.gate.stuck = True
    line.start()
    run(plant, io, line, 5.0)
    assert line.state == LineState.FAULTED
    assert line.fault_reason == "gate failed to prove open"

    line.reset()
    run(plant, io, line, 0.3)
    assert line.state == LineState.IDLE

    # reset() and acknowledge() are deliberately separate (docs/CONTROL-LAB.md
    # §10's Phase 4 step 2 entry) -- without this, the retry below would be
    # refused outright by the new "no unacknowledged alarm" permissive,
    # never reaching STARTING to re-fault on its own.
    line.acknowledge()
    line.start()
    run(plant, io, line, 5.0)
    assert line.state == LineState.FAULTED
    assert line.fault_reason == "gate failed to prove open"


def test_start_is_refused_after_reset_until_the_alarm_is_acknowledged():
    """Phase 4 step 2 (docs/CONTROL-LAB.md §6.3, "No active latched
    alarms"): reset() alone clears FAULTED, but the alarm it left behind
    still blocks a fresh start on its own -- an operator has to have
    actually acknowledged what tripped, not just cleared the state
    machine. Once acknowledged, a start is allowed to proceed -- and, gate
    still stuck, re-faults on its own exactly like the reset()-only test
    above, just reached the long way round."""
    plant, io, line = make_rig()
    plant.gate.stuck = True
    line.start()
    run(plant, io, line, 5.0)
    assert line.state == LineState.FAULTED

    line.reset()
    run(plant, io, line, 0.3)
    assert line.state == LineState.IDLE
    assert line.alarms.get("XV-102.TRAVEL_FAULT").latched is True

    line.start()
    tick(plant, io, line)
    assert line.state == LineState.IDLE  # refused -- never even reaches STARTING
    assert any(r.startswith("unacknowledged alarm") for r in line.last_start_refusal)

    line.acknowledge()
    tick(plant, io, line)
    assert line.alarms.get("XV-102.TRAVEL_FAULT").latched is False

    line.start()
    run(plant, io, line, 5.0)
    assert line.state == LineState.FAULTED  # gate is still stuck


def test_acknowledge_is_one_shot_and_does_not_suppress_a_later_alarm():
    """acknowledge() is a one-shot request, like start()/stop()/reset()
    (LineController's own class docstring) -- it must not keep silently
    re-acknowledging every alarm that latches afterward."""
    plant, io, line = make_rig()
    plant.gate.stuck = True
    line.start()
    run(plant, io, line, 5.0)
    assert line.state == LineState.FAULTED

    line.reset()
    line.acknowledge()
    run(plant, io, line, 0.3)
    assert line.alarms.get("XV-102.TRAVEL_FAULT").latched is False

    # A second, independent trip afterward must latch fresh -- unacknowledged
    # -- not be silently pre-acked by the earlier one-shot request.
    plant.hopper.level_kg = 1_950.0  # 97.5% -- above the 95% high-high threshold
    run(plant, io, line, 0.2)
    assert line.alarms.get("WT-105.HIGH_HIGH").acknowledged is False


def test_unacknowledged_warning_alarm_does_not_block_a_start():
    """Bin low is a warning, not a trip (docs/CONTROL-LAB.md §6.3: "warning
    only while running") -- it already has its own direct permissive row
    for while it's genuinely low (test_interlocks.py::
    test_start_permissives_refused_on_bin_low). The new alarm-based
    permissive must not turn a recovered-but-unacknowledged warning into a
    second, redundant hard block once the bin is no longer actually low."""
    plant, io, line = make_rig()
    plant.bin.level_kg = 100.0  # well under the 10% low threshold
    run(plant, io, line, 0.2)
    assert line.alarms.get("LSL-101.LOW").latched is True

    plant.bin.level_kg = 5_000.0  # recovers -- comfortably above low
    run(plant, io, line, 0.2)
    assert line.alarms.get("LSL-101.LOW").active is False
    assert line.alarms.get("LSL-101.LOW").latched is True  # still unacknowledged

    line.start()
    run(plant, io, line, 5.0)
    assert line.state == LineState.RUNNING  # the warning alone never refuses a start


# ---- E-stop (docs/CONTROL-LAB.md §6.2: from any state; needs release AND reset) --


def test_estop_from_idle():
    plant, io, line = make_rig()
    plant.estop.trip()
    # Two ticks: the first is when plant_scan()'s publish step makes the
    # trip visible on ES-001 (it runs after line.scan() within a tick);
    # the second is when line.scan() actually reacts to it.
    run(plant, io, line, 0.2)
    assert line.state == LineState.ESTOPPED
    assert line.fault_reason == "e-stop"


def test_estop_during_starting_aborts_the_sequence():
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 0.5)
    assert line.state == LineState.STARTING

    plant.estop.trip()
    run(plant, io, line, 0.2)  # one tick for ES-001 to publish, one to react
    assert line.state == LineState.ESTOPPED
    assert line.start_step is None


def test_start_while_estopped_does_nothing():
    plant, io, line = make_rig()
    plant.estop.trip()
    run(plant, io, line, 0.2)  # one tick for ES-001 to publish, one to react
    assert line.state == LineState.ESTOPPED

    line.start()
    tick(plant, io, line)
    assert line.state == LineState.ESTOPPED  # e-stop still tripped


def test_reset_alone_does_not_recover_from_estopped_without_the_estop_released():
    """docs/CONTROL-LAB.md §6.2's diagram requires BOTH: "E-stop released
    + Reset". reset() before the physical E-stop is released must be a
    no-op, not just "released before reset" (the order
    test_estop_holds_everything_off_and_requires_explicit_restart already
    covers) -- this is the reverse order, and the more likely mistake for
    an impatient operator to make."""
    plant, io, line = make_rig()
    plant.estop.trip()
    run(plant, io, line, 0.2)
    assert line.state == LineState.ESTOPPED

    line.reset()  # pressed before the E-stop button is released
    run(plant, io, line, 0.5)
    assert line.state == LineState.ESTOPPED  # refused -- e-stop still tripped
    assert plant.conveyor.motor.run_command is False

    plant.estop.reset()  # now release it -- reset() was already consumed as a one-shot...
    run(plant, io, line, 0.5)
    assert line.state == LineState.ESTOPPED  # ...so it does NOT recover on its own

    line.reset()  # a fresh reset() is required
    tick(plant, io, line)
    assert line.state == LineState.IDLE


def test_estop_holds_everything_off_and_requires_explicit_restart():
    """Proves LineController closes the gap demonstrated in
    tests/integration/test_plant_io.py::
    test_estop_via_io_image_holds_motors_until_explicit_reset: at the raw
    I/O-image layer, a stale run command restarts a motor the instant
    it's reset. Here, with LineController actually driving the line, it
    can't -- ESTOPPED holds every command at False continuously."""
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 3.0)
    assert line.state == LineState.RUNNING
    assert plant.conveyor.motor.running is True

    plant.estop.trip()
    run(plant, io, line, 0.2)  # one tick for ES-001 to publish, one to react
    assert line.state == LineState.ESTOPPED
    assert plant.conveyor.motor.state == MotorState.ESTOP
    assert plant.feeder.motor.state == MotorState.ESTOP

    # Releasing the E-stop alone brings the motors back to STOPPED
    # (Plant's own auto-reset -- see plant.py) but must NOT restart them.
    plant.estop.reset()
    run(plant, io, line, 1.0)
    assert line.state == LineState.ESTOPPED  # no reset() yet
    assert plant.conveyor.motor.state == MotorState.STOPPED  # available again...
    assert plant.conveyor.motor.run_command is False  # ...but not commanded -- this is the fix
    assert plant.feeder.motor.run_command is False

    line.reset()
    tick(plant, io, line)
    assert line.state == LineState.IDLE

    # Recovering does NOT auto-restart -- a fresh start() is required.
    run(plant, io, line, 1.0)
    assert line.state == LineState.IDLE
    assert plant.conveyor.motor.running is False

    # reset() and acknowledge() are deliberately separate (docs/CONTROL-LAB.md
    # §10's Phase 4 step 2 entry) -- the ES-001.TRIP alarm is still latched
    # and unacknowledged, which would otherwise refuse this start outright.
    line.acknowledge()
    line.start()
    run(plant, io, line, 5.0)
    assert line.state == LineState.RUNNING


def test_bin_low_while_running_stays_a_warning_for_the_whole_run():
    """The sustained half of scenarios/faults/bin_low_while_running_warns_only.yaml.
    A declarative scenario passes the moment its expectations first hold,
    so it can't prove the line doesn't trip a few seconds later; this
    checks every tick for 10 s of feeding from a low bin."""
    plant, io, line = make_rig()
    line.start()
    run(plant, io, line, 5.0)
    assert line.state == LineState.RUNNING

    plant.bin.level_kg = 500.0  # 5% -- under the 10% low threshold
    for _ in range(100):
        tick(plant, io, line)
        assert line.state == LineState.RUNNING, line.fault_reason
    warning = line.alarms.get("LSL-101.LOW")
    assert warning.active and warning.is_warning
    assert not line.alarms.any_unacknowledged_trip()
    assert plant.bin.level_kg < 500.0  # it really was feeding from the low bin, not idling
