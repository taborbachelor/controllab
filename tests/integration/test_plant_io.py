"""Full-line scenarios driven purely through the I/O image boundary,
via plant_io.scan() — proof that Control (Phase 2, not yet built) will
have everything it needs without ever touching Plant's devices directly.
These mirror tests/integration/test_plant.py, which drives the same
scenarios by calling Plant's devices by hand.

There's no I/O tag for resetting the E-stop or a motor fault (docs/
CONTROL-LAB.md §3.2: Reset is an HMI tag, not field I/O — it doesn't
exist until the mode manager, Phase 2 step 3). Those two calls are the
only place these tests touch Plant directly.
"""
import pytest

from services.simulation.engine.plant_io import build_line_io_image, publish_plant_inputs, scan
from services.simulation.equipment.motor import MotorState
from services.simulation.equipment.plant import Plant, PlantConfig

DT = 0.1


def make_rig(**overrides):
    cfg = PlantConfig(
        bin_capacity_kg=10_000.0,
        bin_level_kg=1_000.0,
        gate_travel_time_s=1.0,
        feeder_max_rate_kg_s=5.0,
        feeder_start_delay_s=0.0,
        conveyor_length_m=4.0,
        conveyor_speed_m_s=2.0,
        conveyor_start_delay_s=0.0,
        hopper_capacity_kg=2_000.0,
        hopper_draw_rate_kg_s=0.0,
        **overrides,
    )
    plant = Plant(cfg)
    io = build_line_io_image()
    publish_plant_inputs(plant, io)  # seed with real starting state
    return plant, io


def run(plant, io, seconds: float) -> None:
    for _ in range(round(seconds / DT)):
        scan(plant, io, DT)


def test_normal_start_sequence_via_io_image_avoids_spillage():
    plant, io = make_rig()

    io.write_output("M-104.RUN", True)
    io.write_output("M-103.RUN", False)
    io.write_output("SC-103", 0.0)
    io.write_output("XV-102.CMD_OPEN", False)
    run(plant, io, 0.2)
    assert io.read("M-104.RUNNING") is True

    io.write_output("XV-102.CMD_OPEN", True)
    run(plant, io, 1.2)
    assert io.read("ZSO-102") is True

    io.write_output("M-103.RUN", True)
    io.write_output("SC-103", 100.0)
    run(plant, io, 3.0)

    assert plant.spilled_kg == 0.0
    assert io.read("WT-105") > 0.0


def test_feeding_onto_a_stopped_conveyor_spills_via_io_image():
    plant, io = make_rig()

    io.write_output("XV-102.CMD_OPEN", True)
    io.write_output("M-103.RUN", False)
    io.write_output("SC-103", 0.0)
    io.write_output("M-104.RUN", False)
    run(plant, io, 1.2)
    assert io.read("ZSO-102") is True

    io.write_output("M-103.RUN", True)
    io.write_output("SC-103", 100.0)
    run(plant, io, 2.0)  # conveyor never commanded

    assert plant.spilled_kg > 0.0
    assert io.read("WT-105") == 0.0


def test_material_conservation_holds_driven_through_io_image():
    plant, io = make_rig()
    starting_total = plant.total_mass_kg()

    io.write_output("M-104.RUN", True)
    io.write_output("XV-102.CMD_OPEN", True)
    io.write_output("M-103.RUN", True)
    io.write_output("SC-103", 100.0)

    for _ in range(200):  # 20s simulated
        scan(plant, io, DT)
        assert plant.accounted_mass_kg() == pytest.approx(starting_total)

    assert io.read("WT-105") > 0.0
    assert plant.spilled_kg == 0.0


def test_estop_via_io_image_holds_motors_until_explicit_reset():
    """Demonstrates the gap at THIS layer alone (I/O image + Plant, no
    line control): Plant.step() brings a motor's STATE back to STOPPED
    automatically the instant the physical E-stop releases (a real safety
    relay re-arms the starters on its own — see plant.py), but that says
    nothing about what's still asserted in the I/O image. Nothing at this
    layer clears a stale run command, so if one's still sitting there,
    the motor restarts the moment it becomes available again.

    That's exactly the gap Phase 2 step 3 closes: LineController.ESTOPPED
    continuously holds every command at False, so this can't happen once
    it's driving the line — see
    tests/integration/test_line_controller.py::
    test_estop_holds_everything_off_and_requires_explicit_restart.
    """
    plant, io = make_rig()
    io.write_output("M-104.RUN", True)
    io.write_output("XV-102.CMD_OPEN", True)
    io.write_output("M-103.RUN", True)
    io.write_output("SC-103", 100.0)
    run(plant, io, 1.5)
    assert io.read("M-104.RUNNING") is True

    plant.estop.trip()  # the physical button — no I/O tag drives this
    scan(plant, io, DT)

    assert io.read("ES-001") is False
    assert plant.conveyor.motor.state == MotorState.ESTOP
    assert plant.feeder.motor.state == MotorState.ESTOP

    # Commands re-asserted through the I/O image while tripped have no effect.
    run(plant, io, 1.0)
    assert plant.conveyor.motor.state == MotorState.ESTOP
    assert plant.feeder.motor.state == MotorState.ESTOP

    # The run commands are still asserted True in the I/O image — nothing
    # at this layer has cleared them. Releasing the E-stop alone is
    # enough to bring the motor STATE back to STOPPED automatically, but
    # the stale command is still sitting there, so the very next scan
    # restarts it. The I/O image has no opinion about whether that's
    # safe — it just reflects whatever's asserted in it.
    plant.estop.reset()  # no I/O tag for this either — see module docstring
    scan(plant, io, DT)

    assert io.read("ES-001") is True
    assert plant.conveyor.motor.state == MotorState.RUNNING  # stale command wins, at this layer
    assert plant.feeder.motor.state == MotorState.RUNNING
