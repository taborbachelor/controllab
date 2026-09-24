"""The conveyor motor current (IT-104), the belt scale (FT-104), a conveyor
jam and bin bridging (completing the master specification, item 5): the
plant models, and what the controller does with the two signals."""
import pytest

from services.control.line_state import LineState
from services.simulation.engine.plant_io import scan as plant_scan
from services.testing.rig import DT, build_rig, run, tick


def running_rig():
    rig = build_rig()
    rig.line.start()
    run(rig, 5.0)  # past the belt transit: material on the belt, flow at the scale
    assert rig.line.state == LineState.RUNNING
    return rig


# ---- the plant ----------------------------------------------------------------


def test_the_motor_current_follows_the_motor_and_its_load():
    rig = build_rig()
    fla = rig.plant.conveyor.full_load_a
    assert rig.io.read("IT-104") == 0.0  # stopped
    rig.line.start()
    tick(rig)  # the test rig's motor starts in 0.2 s: the first tick is mid-start
    assert rig.io.read("IT-104") == pytest.approx(6.0 * fla)  # inrush while starting
    run(rig, 0.5)
    empty = rig.io.read("IT-104")
    assert empty == pytest.approx(0.45 * fla)  # running, nothing on the belt yet
    run(rig, 4.0)
    loaded = rig.io.read("IT-104")
    assert empty < loaded <= 0.85 * fla + 1e-9  # the belt carries its rated load


def test_a_jam_draws_jam_current_and_a_slip_draws_less_than_no_load():
    rig = running_rig()
    fla = rig.plant.conveyor.full_load_a
    rig.plant.conveyor.jammed = True
    rig.plant.step(DT)
    assert rig.plant.conveyor.current_a == pytest.approx(2.5 * fla)
    rig.plant.conveyor.jammed = False
    rig.plant.conveyor.motion_switch_stuck_false = True
    assert rig.plant.conveyor.current_a == pytest.approx(0.3 * fla)


def test_a_jam_left_running_trips_the_motor_overload_relay():
    """Without a controller to stop it, the motor strains against the jam
    until its thermal overload trips (5 s at jam current)."""
    rig = build_rig(with_controller=False)
    rig.io.write_output("M-104.RUN", True)
    for _ in range(10):
        plant_scan(rig.plant, rig.io, DT)
    rig.plant.conveyor.jammed = True
    for _ in range(49):
        plant_scan(rig.plant, rig.io, DT)
    assert not rig.io.read("M-104.OL")
    plant_scan(rig.plant, rig.io, DT)
    assert rig.io.read("M-104.OL") and rig.io.read("IT-104") == 0.0


def test_the_belt_scale_reads_the_feed_rate_once_the_belt_is_full():
    rig = running_rig()
    assert rig.io.read("FT-104") == pytest.approx(rig.plant.feeder.max_rate_kg_s, rel=1e-6)


def test_a_bridged_bin_discharges_nothing_though_it_is_full():
    rig = running_rig()
    level = rig.plant.bin.level_kg
    rig.plant.bin.bridged = True
    run(rig, 3.0)
    assert rig.plant.bin.level_kg == level
    assert rig.io.read("FT-104") == 0.0  # the belt has emptied into the hopper
    assert not rig.io.read("LSL-101")  # the level instruments see a full bin


# ---- the controller ---------------------------------------------------------------


def test_a_normal_start_never_counts_the_inrush_as_overcurrent():
    rig = build_rig()
    rig.line.start()
    for _ in range(80):
        tick(rig)
        assert not rig.line.interlocks.conveyor_overcurrent
    assert rig.line.state == LineState.RUNNING


def test_a_belt_slip_is_still_a_slip_not_a_jam():
    """The current tells them apart: the slip's motor runs light."""
    rig = running_rig()
    rig.plant.conveyor.motion_switch_stuck_false = True
    run(rig, 0.3)
    assert rig.line.fault_reason == "conveyor lost confirmation"


def test_overcurrent_needs_a_full_second():
    rig = running_rig()
    rig.plant.instruments.stick("ZSS-104")
    rig.plant.conveyor.jammed = True
    run(rig, 0.9)
    assert rig.line.state == LineState.RUNNING  # 0.8 s of overcurrent seen so far
    run(rig, 0.3)
    assert (rig.line.state, rig.line.fault_reason) == (LineState.FAULTED, "conveyor jam")
    assert not rig.io.read("M-104.OL")  # the line tripped before the overload relay had to


def test_no_flow_is_a_warning_the_line_keeps_running():
    rig = running_rig()
    rig.plant.bin.bridged = True
    run(rig, 10.0)
    alarm = rig.line.alarms.get("FT-104.NO_FLOW")
    assert alarm.active and alarm.is_warning
    assert rig.line.state == LineState.RUNNING and not rig.line.alarms.any_unacknowledged_trip()
    rig.plant.bin.bridged = False  # the bridge breaks
    run(rig, 4.0)
    assert not rig.line.alarms.get("FT-104.NO_FLOW").active


def test_the_hopper_level_control_pause_is_not_no_flow():
    """At the high switch the feeder stops: no feeding, so no verdict on flow."""
    rig = build_rig()
    rig.plant.hopper.level_kg = 1_700.0  # past LSH-105
    rig.line.start()
    run(rig, 20.0)
    assert not rig.io.read("M-103.RUN")
    assert not rig.line.alarms.get("FT-104.NO_FLOW").active
