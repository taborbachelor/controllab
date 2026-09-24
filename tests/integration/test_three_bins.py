"""Three bins feeding the one feeder (completing the master specification,
item 6): the plant, the controller's source bin (an HMI setpoint), one gate
at a time, and the setpoint and the second alarm word over Modbus."""
import pytest

from services.control.line_state import LineMode, LineState, StartInhibit
from services.protocols import controller_status
from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.modbus import ModbusError
from services.protocols.register_map import IOImageDataStore
from services.simulation.engine.plant_io import scan as plant_scan
from services.testing.external import build_external_rig
from services.testing.rig import DT, build_rig, run, tick
from services.visualization.live import LiveSession


# ---- the plant ------------------------------------------------------------------


def test_the_feeder_draws_from_the_open_gate_and_shares_between_open_gates():
    rig = build_rig(with_controller=False)
    io = rig.io
    for tag in ("M-104.RUN", "M-103.RUN", "XV-112.CMD_OPEN"):
        io.write_output(tag, True)
    io.write_output("SC-103", 100.0)
    for _ in range(30):
        plant_scan(rig.plant, io, DT)
    a, b, c = (rig.plant.bins[x][0].level_kg for x in "ABC")
    assert a == c == 2_000.0 and b < 2_000.0  # only bin B gave anything
    io.write_output("XV-122.CMD_OPEN", True)
    for _ in range(15):
        plant_scan(rig.plant, io, DT)
    b0, c0 = rig.plant.bin_b.level_kg, rig.plant.bin_c.level_kg
    for _ in range(10):
        plant_scan(rig.plant, io, DT)
    assert b0 - rig.plant.bin_b.level_kg == pytest.approx(c0 - rig.plant.bin_c.level_kg)  # an equal share each
    assert rig.plant.accounted_mass_kg() == pytest.approx(6_000.0)  # all three bins conserved


def test_the_estop_closes_every_gate():
    rig = build_rig(with_controller=False)
    for tag in ("XV-102.CMD_OPEN", "XV-112.CMD_OPEN", "XV-122.CMD_OPEN"):
        rig.io.write_output(tag, True)
    rig.plant.estop.trip()
    for _ in range(20):
        plant_scan(rig.plant, rig.io, DT)
    assert all(gate.is_closed for _, gate in rig.plant.bins.values())


# ---- the controller -----------------------------------------------------------------


def test_the_source_bin_is_validated_recorded_once_and_latched_at_start():
    rig = build_rig()
    pressed = []
    rig.line.command_sink = pressed.append
    with pytest.raises(ValueError):
        rig.line.select_source("D")
    rig.line.select_source("B")
    rig.line.select_source("B")  # no change, nothing recorded
    assert pressed == ["source_bin B"]
    rig.line.start()
    run(rig, 3.0)
    assert rig.line.active_bin == "B"
    rig.line.select_source("C")
    run(rig, 0.5)
    assert (rig.line.source_bin, rig.line.active_bin) == ("C", "B")
    assert rig.plant.gate_b.is_open and not rig.plant.gate_c.is_open
    rig.line.stop()
    run(rig, 3.0)
    assert rig.line.state == LineState.IDLE and rig.line.active_bin is None


def test_manual_opens_only_the_selected_bins_gate():
    rig = build_rig()
    rig.line.select_manual()
    tick(rig)
    rig.line.open_gate()
    run(rig, 1.5)
    assert rig.plant.gate.is_open
    rig.line.select_source("C")
    rig.line.open_gate()
    run(rig, 1.5)
    assert rig.plant.gate_c.is_open and rig.plant.gate.is_closed  # one bin at a time
    rig.line.close_gate()
    run(rig, 1.5)
    assert all(gate.is_closed for _, gate in rig.plant.bins.values())
    assert rig.line.mode == LineMode.MANUAL and rig.line.state == LineState.MANUAL


def test_a_manual_feeder_start_checks_the_bin_it_would_draw_from():
    rig = build_rig(plant_overrides={"bin_c_level_kg": 500.0})  # bin C at 5 %
    rig.line.select_manual()
    tick(rig)
    rig.line.select_source("C")
    rig.line.start_conveyor()
    run(rig, 0.6)
    rig.line.open_gate()
    run(rig, 1.5)
    rig.line.start_feeder()
    tick(rig)
    assert StartInhibit.BIN_LOW in rig.line.start_inhibit


def test_a_one_bin_line_still_builds_and_runs():
    """A LineController built with bin A's gate alone is the original line."""
    from services.testing.rig import build_line_controller
    rig = build_rig()
    line = build_line_controller(rig.io, 2_000.0)
    assert set(line.gates) == {"A", "B", "C"}
    solo = type(line)(rig.io, line.feeder_ctrl, line.conveyor_ctrl, line.gate_ctrl, hopper_capacity_kg=2_000.0)
    assert set(solo.gates) == {"A"} and solo.source_bin == "A"
    with pytest.raises(ValueError):
        solo.select_source("B")


# ---- over Modbus ------------------------------------------------------------------------


def test_the_second_alarm_word_and_the_bins_round_trip_through_the_status_block():
    rig = build_rig()
    rig.line.select_source("B")
    rig.plant.gate_b.stuck = True
    rig.line.start()
    run(rig, 3.0)
    assert rig.line.fault_reason == "gate failed to prove open"
    status = controller_status.decode(controller_status.encode(rig.line))
    assert status.source_bin == "B" and status.active_bin == "B"
    alarm = next(a for a in status.alarms if a.id == "XV-112.TRAVEL_FAULT")  # bit 16: the second word
    # The faulted line commands the gate closed, where the stuck gate already is,
    # so the condition is gone -- but the alarm stays latched and first-out.
    assert alarm.latched and not alarm.acknowledged and alarm.first_out


def test_the_source_bin_reaches_an_external_controller_through_its_setpoint_register():
    rig = build_external_rig()
    try:
        rig.line.select_source("C")
        rig.line.scan(DT)
        rig.line.start()
        for _ in range(30):
            tick(rig)
        assert rig.line.controller.line.source_bin == "C"
        assert (rig.line.source_bin, rig.line.active_bin) == ("C", "C")
        assert rig.plant.gate_c.is_open and not rig.plant.gate.is_open
    finally:
        rig.line.close()


def test_a_scada_write_to_the_setpoint_register_reaches_the_built_in_controller():
    rig = build_rig()
    seen = []
    store = IOImageDataStore(LINE_REGISTER_MAP, lambda: rig.io, on_setpoint=lambda n, raw: seen.append((n, raw)),
                             setpoint_source=lambda: {"source_bin": 1})
    store.write_holding_registers(101, [2])
    assert seen == [("source_bin", 2)]
    assert store.read_holding_registers(100, 2)[1] == 1
    with pytest.raises(ModbusError):
        store.write_holding_registers(100, [1, 2])  # the request word isn't the HMI's to write


# ---- the dashboard ----------------------------------------------------------------------------


def test_the_dashboard_selects_the_source_bin():
    s = LiveSession()
    s.setpoint("source_bin", "B")
    s.step()
    snap = s.snapshot()
    assert (snap["source_bin"], snap["active_bin"]) == ("B", None)
    assert any(e["type"] == "command_issued" and e["command"] == "source_bin B" for e in snap["events"])
    with pytest.raises(ValueError):
        s.setpoint("source_bin", "D")
    ext = LiveSession(external=True)
    ext.setpoint("source_bin", "C")
    ext.step()
    assert ext.handshake.setpoints["source_bin"] == 3 and ext.snapshot()["source_bin"] == "C"


def test_a_fresh_hmi_channel_puts_every_setpoint_back_at_its_default():
    """Found on the first real-time run of the three-bin suite: the source bin
    one scenario selected leaked into the next through the shared channel."""
    handshake = LINE_REGISTER_MAP.handshake()
    handshake.set_setpoint("source_bin", 3)
    handshake.request("start")
    handshake.reset()
    assert handshake.setpoints == LINE_REGISTER_MAP.setpoint_defaults and handshake.request_word == 0
    assert handshake.setpoints["source_bin"] == 1
