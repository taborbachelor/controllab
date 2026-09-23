"""The hopper level switch cross-check (services/control/level_check.py) and
the 1oo2 high-high vote (Interlocks.hopper_high_high)."""
from services.control.gate_control import GateControl
from services.control.interlocks import Interlocks
from services.control.level_check import LevelSwitchCheck
from services.control.motor_control import MotorControl
from services.simulation.engine.plant_io import build_line_io_image

DT = 0.1


def scans(check, n, switch_open, level_pct, failed=False):
    for _ in range(n):
        check.scan(switch_open, level_pct, failed, DT)
    return check.disagree


def test_agreement_inside_the_deadband_is_not_a_disagreement():
    check = LevelSwitchCheck(95.0)  # 2 % deadband
    assert scans(check, 50, switch_open=False, level_pct=96.9) is False  # switch not yet made, weight just over
    assert scans(check, 50, switch_open=True, level_pct=93.1) is False  # switch made, weight just under


def test_a_disagreement_is_reported_only_after_it_has_lasted_the_delay():
    check = LevelSwitchCheck(95.0)  # 1.0 s delay
    assert scans(check, 9, switch_open=False, level_pct=99.0) is False
    assert scans(check, 1, switch_open=False, level_pct=99.0) is True  # the 10th scan: 1.0 s


def test_both_directions_are_judged():
    assert scans(LevelSwitchCheck(80.0), 10, switch_open=True, level_pct=10.0) is True  # open, hopper nearly empty
    assert scans(LevelSwitchCheck(80.0), 10, switch_open=False, level_pct=90.0) is True  # closed, hopper above it


def test_the_delay_restarts_when_the_instruments_agree_again():
    check = LevelSwitchCheck(95.0)
    scans(check, 9, switch_open=False, level_pct=99.0)
    scans(check, 1, switch_open=True, level_pct=99.0)  # agree for one scan
    assert scans(check, 9, switch_open=False, level_pct=99.0) is False
    assert scans(check, 1, switch_open=False, level_pct=99.0) is True
    assert scans(check, 1, switch_open=True, level_pct=99.0) is False  # clears as soon as they agree


def test_nothing_is_judged_while_the_transmitter_has_failed():
    check = LevelSwitchCheck(95.0)
    assert scans(check, 50, switch_open=True, level_pct=0.0, failed=True) is False


def make_interlocks():
    io = build_line_io_image()
    il = Interlocks(
        io,
        MotorControl(io, "M-103.RUN", "M-103.RUNNING", "M-103.FAULT", speed_tag="SC-103"),
        MotorControl(io, "M-104.RUN", "M-104.RUNNING", "M-104.OL"),
        GateControl(io, "XV-102.CMD_OPEN", "ZSO-102", "ZSC-102"),
        2_000.0,
    )
    io.write_input("LSH-105", True)
    io.write_input("LSHH-105", True)  # healthy: below both switch points
    return io, il


def test_high_high_is_1oo2_either_measurement_trips():
    io, il = make_interlocks()
    io.write_input("WT-105", 1_000.0)
    assert il.hopper_high_high is False
    io.write_input("WT-105", 1_900.0)  # 95 %: the transmitter alone
    assert il.hopper_high_high_switch is False and il.hopper_high_high is True
    io.write_input("WT-105", 1_000.0)
    io.write_input("LSHH-105", False)  # the switch alone
    assert il.hopper_high_high_weight is False and il.hopper_high_high is True
    assert "hopper at high-high" in il.start_permissives_ok().reasons


def test_a_failed_transmitter_casts_no_high_high_vote():
    io, il = make_interlocks()
    io.write_input("WT-105", 1_950.0)
    io.write_input("WT-105.FLT", True)  # the reading is meaningless
    assert il.hopper_high_high_weight is False
