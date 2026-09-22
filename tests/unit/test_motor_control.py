"""Unit tests against a bare IOImage (no Plant) — proof MotorControl is
generic, not hardcoded to this line's tag names. The integration test
wiring it to a real simulated motor lives in
tests/integration/test_device_control.py.
"""
import pytest

from services.control.errors import ControlError
from services.control.motor_control import MotorControl
from services.simulation.engine.io_image import IOImage, TagType

DT = 0.1


def make_io(with_speed: bool = False) -> IOImage:
    io = IOImage()
    io.define("RUN", TagType.DO)
    io.define("RUNNING", TagType.DI)
    io.define("FAULT", TagType.DI)
    if with_speed:
        io.define("SPEED", TagType.AO)
    return io


def run(mc: MotorControl, seconds: float) -> None:
    for _ in range(round(seconds / DT)):
        mc.scan(DT)


def test_command_run_writes_the_do_tag():
    io = make_io()
    mc = MotorControl(io, "RUN", "RUNNING", "FAULT")
    mc.command_run(True)
    assert io.read("RUN") is True
    assert mc.commanded_run is True


def test_running_and_faulted_reflect_feedback_tags():
    io = make_io()
    mc = MotorControl(io, "RUN", "RUNNING", "FAULT")
    io.write_input("RUNNING", True)
    io.write_input("FAULT", True)
    assert mc.running is True
    assert mc.faulted is True


def test_no_start_proof_fault_while_confirmed_running():
    io = make_io()
    mc = MotorControl(io, "RUN", "RUNNING", "FAULT", start_proof_timeout_s=1.0)
    mc.command_run(True)
    io.write_input("RUNNING", True)  # confirms immediately in this test
    run(mc, 5.0)
    assert mc.start_proof_fault is False


def test_start_proof_fault_after_timeout_without_confirmation():
    io = make_io()
    mc = MotorControl(io, "RUN", "RUNNING", "FAULT", start_proof_timeout_s=1.0)
    mc.command_run(True)
    run(mc, 0.9)
    assert mc.start_proof_fault is False
    run(mc, 0.2)
    assert mc.start_proof_fault is True


def test_dropping_the_run_command_clears_the_fault():
    io = make_io()
    mc = MotorControl(io, "RUN", "RUNNING", "FAULT", start_proof_timeout_s=0.5)
    mc.command_run(True)
    run(mc, 1.0)
    assert mc.start_proof_fault is True
    mc.command_run(False)
    mc.scan(DT)
    assert mc.start_proof_fault is False


def test_clear_fault_gives_one_more_window():
    io = make_io()
    mc = MotorControl(io, "RUN", "RUNNING", "FAULT", start_proof_timeout_s=0.5)
    mc.command_run(True)
    run(mc, 1.0)
    assert mc.start_proof_fault is True

    mc.clear_fault()
    assert mc.start_proof_fault is False
    run(mc, 0.3)
    assert mc.start_proof_fault is False  # window not elapsed yet

    io.write_input("RUNNING", True)
    run(mc, 0.1)
    assert mc.start_proof_fault is False  # confirmed in time this round


def test_late_confirmation_does_not_clear_an_already_raised_fault():
    """Once start-proof has already fired, the motor confirming running
    late (still commanded, no clear_fault() call) does NOT erase it --
    something legitimately took longer than expected, worth keeping
    visible. Only clear_fault() or dropping the command clears it."""
    io = make_io()
    mc = MotorControl(io, "RUN", "RUNNING", "FAULT", start_proof_timeout_s=0.5)
    mc.command_run(True)
    run(mc, 1.0)
    assert mc.start_proof_fault is True

    io.write_input("RUNNING", True)  # confirms late, command never dropped
    run(mc, 0.1)
    assert mc.start_proof_fault is True  # still raised
    assert mc.running is True


def test_speed_command_requires_a_configured_speed_tag():
    io = make_io(with_speed=False)
    mc = MotorControl(io, "RUN", "RUNNING", "FAULT")
    with pytest.raises(ControlError):
        mc.command_speed(50.0)


def test_speed_command_writes_the_ao_tag_when_configured():
    io = make_io(with_speed=True)
    mc = MotorControl(io, "RUN", "RUNNING", "FAULT", speed_tag="SPEED")
    mc.command_speed(42.0)
    assert io.read("SPEED") == 42.0


def test_construction_validates_tag_directions():
    io = make_io()
    with pytest.raises(ControlError):
        MotorControl(io, "RUNNING", "RUN", "FAULT")  # run_tag must be DO
    with pytest.raises(ControlError):
        MotorControl(io, "RUN", "FAULT", "RUN")  # fault_fb_tag must be DI


def test_construction_validates_speed_tag_type():
    io = make_io(with_speed=False)
    with pytest.raises(ControlError):
        MotorControl(io, "RUN", "RUNNING", "FAULT", speed_tag="RUN")  # DO, not AO
