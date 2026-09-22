"""Unit tests against a bare IOImage (no Plant). The integration test
wiring this to a real simulated gate lives in
tests/integration/test_device_control.py.
"""
import pytest

from services.control.errors import ControlError
from services.control.gate_control import GateControl
from services.simulation.engine.io_image import IOImage, TagType

DT = 0.1


def make_io() -> IOImage:
    io = IOImage()
    io.define("CMD", TagType.DO)
    io.define("OPEN_FB", TagType.DI)
    io.define("CLOSED_FB", TagType.DI)
    return io


def run(gc: GateControl, seconds: float) -> None:
    for _ in range(round(seconds / DT)):
        gc.scan(DT)


def test_command_open_writes_the_do_tag():
    io = make_io()
    gc = GateControl(io, "CMD", "OPEN_FB", "CLOSED_FB")
    gc.command_open(True)
    assert io.read("CMD") is True
    assert gc.commanded_open is True


def test_no_travel_fault_once_target_reached():
    io = make_io()
    gc = GateControl(io, "CMD", "OPEN_FB", "CLOSED_FB", travel_timeout_s=1.0)
    gc.command_open(True)
    io.write_input("OPEN_FB", True)
    run(gc, 5.0)
    assert gc.travel_fault is False


def test_travel_fault_after_timeout_without_reaching_target():
    io = make_io()
    gc = GateControl(io, "CMD", "OPEN_FB", "CLOSED_FB", travel_timeout_s=1.0)
    gc.command_open(True)
    run(gc, 0.9)
    assert gc.travel_fault is False
    run(gc, 0.2)
    assert gc.travel_fault is True


def test_reversing_command_resets_the_timer_and_fault():
    io = make_io()
    gc = GateControl(io, "CMD", "OPEN_FB", "CLOSED_FB", travel_timeout_s=1.0)
    gc.command_open(True)
    run(gc, 1.2)
    assert gc.travel_fault is True

    gc.command_open(False)
    gc.scan(DT)
    assert gc.travel_fault is False

    io.write_input("CLOSED_FB", True)
    run(gc, 0.1)
    assert gc.travel_fault is False


def test_clear_fault_gives_one_more_window():
    io = make_io()
    gc = GateControl(io, "CMD", "OPEN_FB", "CLOSED_FB", travel_timeout_s=0.5)
    gc.command_open(True)
    run(gc, 1.0)
    assert gc.travel_fault is True

    gc.clear_fault()
    assert gc.travel_fault is False

    io.write_input("OPEN_FB", True)
    run(gc, 0.1)
    assert gc.travel_fault is False


def test_late_arrival_does_not_clear_an_already_raised_fault():
    """Same latching choice as MotorControl.start_proof_fault -- see its
    identical test for the reasoning."""
    io = make_io()
    gc = GateControl(io, "CMD", "OPEN_FB", "CLOSED_FB", travel_timeout_s=0.5)
    gc.command_open(True)
    run(gc, 1.0)
    assert gc.travel_fault is True

    io.write_input("OPEN_FB", True)  # arrives late, command never dropped
    run(gc, 0.1)
    assert gc.travel_fault is True  # still raised
    assert gc.is_open is True


def test_construction_validates_tag_directions():
    io = make_io()
    with pytest.raises(ControlError):
        GateControl(io, "OPEN_FB", "CMD", "CLOSED_FB")  # command_tag must be DO
