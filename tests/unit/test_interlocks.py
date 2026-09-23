"""Interlocks is built around this line's actual tag names (unlike
MotorControl/GateControl, which are generic), so these tests use the real
build_line_io_image() rather than a bespoke bare table.
"""
from services.control.gate_control import GateControl
from services.control.interlocks import Interlocks
from services.control.motor_control import MotorControl
from services.simulation.engine.plant_io import build_line_io_image

HOPPER_CAPACITY_KG = 2_000.0


def make_interlocks():
    io = build_line_io_image()
    feeder_ctrl = MotorControl(io, "M-103.RUN", "M-103.RUNNING", "M-103.FAULT", speed_tag="SC-103")
    conveyor_ctrl = MotorControl(io, "M-104.RUN", "M-104.RUNNING", "M-104.OL")
    gate_ctrl = GateControl(io, "XV-102.CMD_OPEN", "ZSO-102", "ZSC-102")
    # DI tags default False, and the hopper level switches are fail-safe
    # (1 = below the switch point): an unpublished image reads high-high,
    # exactly like ES-001 reads tripped. Start from healthy switches.
    io.write_input("LSH-105", True)
    io.write_input("LSHH-105", True)
    return io, Interlocks(io, feeder_ctrl, conveyor_ctrl, gate_ctrl, HOPPER_CAPACITY_KG)


def test_estop_healthy_reflects_es_001():
    io, il = make_interlocks()
    assert il.estop_healthy is False  # DI tags default False -- nothing has published a real reading yet
    io.write_input("ES-001", True)
    assert il.estop_healthy is True
    io.write_input("ES-001", False)
    assert il.estop_healthy is False


def test_bin_low_reflects_lsl_101():
    io, il = make_interlocks()
    io.write_input("LSL-101", True)
    assert il.bin_low is True


def test_hopper_high_and_high_high_reflect_their_switches():
    """Fail-safe polarity: each switch reads 1 while the level is below it
    and opens (0) at it."""
    io, il = make_interlocks()
    assert il.hopper_high is False and il.hopper_high_high is False  # both closed: below
    io.write_input("LSH-105", False)
    assert il.hopper_high is True and il.hopper_high_high is False
    io.write_input("LSHH-105", False)
    assert il.hopper_high_high is True


def test_a_dead_level_switch_reads_high_not_healthy():
    """An input nobody has written (a broken wire, a dead card) reads 0, and
    a fail-safe switch reports 0 as the tripped state -- the reason for the
    polarity. Before it, a broken LSHH-105 wire read "not high-high" and
    silently removed the overfill trip."""
    io = build_line_io_image()  # nothing published
    il = Interlocks(
        io,
        MotorControl(io, "M-103.RUN", "M-103.RUNNING", "M-103.FAULT", speed_tag="SC-103"),
        MotorControl(io, "M-104.RUN", "M-104.RUNNING", "M-104.OL"),
        GateControl(io, "XV-102.CMD_OPEN", "ZSO-102", "ZSC-102"),
        HOPPER_CAPACITY_KG,
    )
    assert il.hopper_high is True and il.hopper_high_high is True
    assert "hopper at high-high" in il.start_permissives_ok().reasons


def test_hopper_level_pct_computed_from_weight_and_capacity():
    io, il = make_interlocks()
    io.write_input("WT-105", 1_000.0)  # half of 2,000 kg capacity
    assert il.hopper_level_pct == 50.0


def test_conveyor_confirmed_running_requires_both_running_and_motion():
    io, il = make_interlocks()
    io.write_input("M-104.RUNNING", True)
    io.write_input("ZSS-104", False)
    assert il.conveyor_confirmed_running is False  # belt slip: motor on, belt not moving

    io.write_input("ZSS-104", True)
    assert il.conveyor_confirmed_running is True

    io.write_input("M-104.RUNNING", False)
    assert il.conveyor_confirmed_running is False  # motor itself not running


def test_start_permissives_ok_when_everything_clear():
    io, il = make_interlocks()
    check = il.start_permissives_ok()
    assert check.ok is True
    assert check.reasons == []


def test_start_permissives_refused_on_hopper_high_high():
    io, il = make_interlocks()
    io.write_input("LSHH-105", False)  # open: high-high
    check = il.start_permissives_ok()
    assert check.ok is False
    assert "hopper at high-high" in check.reasons


def test_start_permissives_refused_on_bin_low():
    io, il = make_interlocks()
    io.write_input("LSL-101", True)
    check = il.start_permissives_ok()
    assert check.ok is False
    assert "bin low" in check.reasons


def test_start_permissives_reports_multiple_reasons_together():
    io, il = make_interlocks()
    io.write_input("LSHH-105", False)  # open: high-high
    io.write_input("LSL-101", True)
    check = il.start_permissives_ok()
    assert check.ok is False
    assert len(check.reasons) == 2
