"""Proves the device control modules against a real simulated Plant,
through the I/O image — not a bare tag table like the unit tests, and
not Plant's devices directly. This is the shape line control (Phase 2
step 3) will drive: Control scans first (issuing/supervising commands),
then plant_io.scan() applies them and advances physics.
"""
from services.control.gate_control import GateControl
from services.control.motor_control import MotorControl
from services.simulation.engine.plant_io import build_line_io_image, publish_plant_inputs
from services.simulation.engine.plant_io import scan as plant_scan
from services.simulation.equipment.plant import Plant, PlantConfig

DT = 0.1


def make_rig(**overrides):
    cfg = PlantConfig(
        bin_level_kg=1_000.0,
        gate_travel_time_s=1.0,
        feeder_start_delay_s=0.2,
        conveyor_start_delay_s=0.2,
        conveyor_length_m=4.0,
        conveyor_speed_m_s=2.0,
        hopper_draw_rate_kg_s=0.0,
        **overrides,
    )
    plant = Plant(cfg)
    io = build_line_io_image()
    publish_plant_inputs(plant, io)  # seed with real starting state

    conveyor_ctrl = MotorControl(io, "M-104.RUN", "M-104.RUNNING", "M-104.OL", start_proof_timeout_s=1.0)
    feeder_ctrl = MotorControl(
        io, "M-103.RUN", "M-103.RUNNING", "M-103.FAULT", speed_tag="SC-103", start_proof_timeout_s=1.0
    )
    gate_ctrl = GateControl(io, "XV-102.CMD_OPEN", "ZSO-102", "ZSC-102", travel_timeout_s=2.0)

    return plant, io, conveyor_ctrl, feeder_ctrl, gate_ctrl


def tick(plant, io, controls, dt: float) -> None:
    for c in controls:
        c.scan(dt)
    plant_scan(plant, io, dt)


def test_motor_control_drives_a_real_simulated_motor():
    plant, io, conv, feeder, gate = make_rig()
    controls = [conv, feeder, gate]

    conv.command_run(True)
    for _ in range(5):
        tick(plant, io, controls, DT)

    assert conv.running is True
    assert plant.conveyor.motor.running is True  # the real device, not just the tag


def test_gate_control_drives_the_real_gate_open():
    plant, io, conv, feeder, gate = make_rig()
    controls = [conv, feeder, gate]

    gate.command_open(True)
    for _ in range(15):  # gate_travel_time_s=1.0
        tick(plant, io, controls, DT)

    assert gate.is_open is True
    assert plant.gate.is_open is True


def test_start_proof_fault_when_simulation_injects_a_real_fail_to_start():
    plant, io, conv, feeder, gate = make_rig()
    controls = [conv, feeder, gate]

    plant.feeder.motor.fail_to_start = True  # simulation-side fault injection
    feeder.command_run(True)
    feeder.command_speed(100.0)
    for _ in range(15):  # feeder_ctrl start_proof_timeout_s=1.0
        tick(plant, io, controls, DT)

    assert feeder.start_proof_fault is True
    assert feeder.running is False


def test_faulted_reflects_a_real_trip():
    plant, io, conv, feeder, gate = make_rig()
    controls = [conv, feeder, gate]

    conv.command_run(True)
    for _ in range(5):
        tick(plant, io, controls, DT)
    assert conv.running is True

    plant.conveyor.motor.trip_now = True  # simulation-side fault injection
    tick(plant, io, controls, DT)

    assert conv.faulted is True
    assert conv.running is False


def test_travel_fault_when_simulation_injects_a_real_stuck_gate():
    plant, io, conv, feeder, gate = make_rig()
    controls = [conv, feeder, gate]

    plant.gate.stuck = True  # simulation-side fault injection
    gate.command_open(True)
    for _ in range(25):  # gate_ctrl travel_timeout_s=2.0
        tick(plant, io, controls, DT)

    assert gate.travel_fault is True
    assert gate.is_open is False


def test_feeder_speed_command_reaches_the_real_device_clamped():
    plant, io, conv, feeder, gate = make_rig()
    controls = [conv, feeder, gate]

    feeder.command_run(True)
    feeder.command_speed(150.0)  # out of range on purpose
    for _ in range(5):
        tick(plant, io, controls, DT)

    assert plant.feeder.speed_pct == 100.0  # Feeder's own clamp still applies
