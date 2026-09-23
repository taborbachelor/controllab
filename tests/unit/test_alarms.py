"""AlarmManager sits directly on Interlocks, so these tests build the real
line's I/O image the same way test_interlocks.py does, and drive
conditions through io.write_input()/write_output() rather than a Plant --
this is the "Control module" test tier (docs/CONTROL-LAB.md §7), not a
full sequence or scenario.
"""
import pytest

from services.control.alarms import AlarmManager
from services.control.errors import ControlError
from services.control.gate_control import GateControl
from services.control.interlocks import Interlocks
from services.control.motor_control import MotorControl
from services.simulation.engine.plant_io import build_line_io_image

HOPPER_CAPACITY_KG = 2_000.0


def make_alarms():
    io = build_line_io_image()
    feeder_ctrl = MotorControl(io, "M-103.RUN", "M-103.RUNNING", "M-103.FAULT", speed_tag="SC-103")
    conveyor_ctrl = MotorControl(io, "M-104.RUN", "M-104.RUNNING", "M-104.OL")
    gate_ctrl = GateControl(io, "XV-102.CMD_OPEN", "ZSO-102", "ZSC-102")
    il = Interlocks(io, feeder_ctrl, conveyor_ctrl, gate_ctrl, HOPPER_CAPACITY_KG)
    # DI tags default False, and the hopper level switches are fail-safe
    # (1 = below the switch point): an unpublished image reads high-high,
    # exactly like ES-001 reads tripped. Start from healthy switches.
    io.write_input("LSH-105", True)
    io.write_input("LSHH-105", True)
    return io, AlarmManager(il)


def test_new_alarm_manager_has_no_latched_alarms():
    io, am = make_alarms()
    io.write_input("ES-001", True)  # DI tags default False -- ES-001 needs an explicit healthy reading
    am.scan()
    assert am.latched_alarms == []
    assert am.first_out is None
    assert am.any_unacknowledged_trip() is False


def test_alarm_activates_and_latches_on_its_condition():
    io, am = make_alarms()
    io.write_input("ES-001", False)  # tripped (fail-safe polarity: 0 = tripped)
    am.scan()
    alarm = am.get("ES-001.TRIP")
    assert alarm.active is True
    assert alarm.latched is True
    assert alarm.acknowledged is False


def test_alarm_stays_latched_after_condition_clears_until_acknowledged():
    io, am = make_alarms()
    io.write_input("ES-001", False)
    am.scan()
    io.write_input("ES-001", True)  # healthy again
    am.scan()
    alarm = am.get("ES-001.TRIP")
    assert alarm.active is False
    assert alarm.latched is True  # still outstanding -- nobody acknowledged it


def test_acknowledging_while_still_active_keeps_it_latched():
    io, am = make_alarms()
    io.write_input("ES-001", False)
    am.scan()
    am.acknowledge("ES-001.TRIP")
    alarm = am.get("ES-001.TRIP")
    assert alarm.acknowledged is True
    assert alarm.latched is True  # still physically tripped


def test_alarm_fully_resets_once_acknowledged_and_inactive():
    io, am = make_alarms()
    io.write_input("ES-001", False)
    am.scan()
    am.acknowledge("ES-001.TRIP")
    io.write_input("ES-001", True)
    am.scan()
    alarm = am.get("ES-001.TRIP")
    assert alarm.active is False
    assert alarm.latched is False
    assert am.latched_alarms == []


def test_acknowledge_all_acks_every_latched_alarm():
    io, am = make_alarms()
    io.write_input("ES-001", False)
    io.write_input("LSHH-105", False)  # open: high-high
    am.scan()
    assert len(am.latched_alarms) == 2
    am.acknowledge()
    assert all(a.acknowledged for a in am.latched_alarms)


def test_unknown_alarm_id_raises_control_error():
    io, am = make_alarms()
    with pytest.raises(ControlError):
        am.get("NOT-A-REAL-ALARM")
    with pytest.raises(ControlError):
        am.acknowledge("NOT-A-REAL-ALARM")


def test_first_out_claimed_by_earlier_alarm_when_two_trip_same_scan():
    io, am = make_alarms()
    # E-stop is earlier than hopper high-high in the registration/priority
    # order -- both go active on the same scan() call.
    io.write_input("ES-001", False)
    io.write_input("LSHH-105", False)  # open: high-high
    am.scan()
    assert am.first_out.id == "ES-001.TRIP"
    assert am.get("WT-105.HIGH_HIGH").first_out is False


def test_first_out_stays_with_originating_alarm_after_a_later_one_latches():
    io, am = make_alarms()
    io.write_input("ES-001", False)
    am.scan()
    assert am.first_out.id == "ES-001.TRIP"

    io.write_input("LSHH-105", False)  # open: high-high  # a second, later condition trips
    am.scan()
    assert am.first_out.id == "ES-001.TRIP"  # unchanged
    assert am.get("WT-105.HIGH_HIGH").first_out is False
    assert am.get("WT-105.HIGH_HIGH").latched is True  # still latched, just not first-out


def test_first_out_releases_once_the_board_fully_clears_and_can_be_reclaimed():
    io, am = make_alarms()
    io.write_input("ES-001", False)
    am.scan()
    am.acknowledge("ES-001.TRIP")
    io.write_input("ES-001", True)
    am.scan()
    assert am.first_out is None

    io.write_input("LSHH-105", False)  # open: high-high  # a fresh episode
    am.scan()
    assert am.first_out.id == "WT-105.HIGH_HIGH"


def test_any_unacknowledged_trip_ignores_warning_class_alarms():
    io, am = make_alarms()
    io.write_input("ES-001", True)  # DI tags default False -- establish a healthy baseline first
    io.write_input("LSL-101", True)  # bin low -- warning, not a trip
    am.scan()
    assert am.get("LSL-101.LOW").is_warning is True
    assert am.get("LSL-101.LOW").latched is True
    assert am.any_unacknowledged_trip() is False

    io.write_input("ES-001", False)  # now a real trip too
    am.scan()
    assert am.any_unacknowledged_trip() is True


def test_belt_slip_alarm_requires_conveyor_genuinely_commanded_running():
    io, am = make_alarms()
    io.write_input("ZSS-104", False)  # motion switch false -- but motor never asked to run
    am.scan()
    assert am.get("ZSS-104.LOST").active is False

    io.write_output("M-104.RUN", True)
    io.write_input("M-104.RUNNING", True)  # motor confirms running, belt still not moving
    am.scan()
    assert am.get("ZSS-104.LOST").active is True
