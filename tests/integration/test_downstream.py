"""The hopper as a buffer between the upstream feed and the downstream
consumer DS-107 (docs/CONTROL-LAB.md §6.3, "Downstream ready for
discharge"): the outlet is a discharge-enablement device, the feed keeps
its 60 %/80 % hysteresis behind the draw, and Batch waits for the
downstream. Long-run behavior a declarative scenario can't show: it passes
the moment its expectations first hold."""
from services.control.line_state import LineMode, LineState
from services.testing.invariants import Invariants
from services.testing.rig import DT, build_rig, tick


def run(rig, seconds, inv=None):
    for _ in range(round(seconds / DT)):
        tick(rig)
        if inv is not None:
            inv.check()


def test_auto_cycles_the_buffer_between_60_and_80_percent_behind_the_draw():
    """Feed 5 kg/s in, the downstream 3 kg/s out: the hopper fills to the
    high switch, the feed holds, the draw brings it below 60 % and the feed
    restarts -- over and over, with the outlet open the whole time and
    nothing spilled or alarmed."""
    rig = build_rig(plant_overrides={"bin_level_kg": 9_000.0})  # enough for 1,400 s of feeding
    inv = Invariants(rig)
    rig.line.start()
    run(rig, 3.0, inv)
    assert rig.line.state == LineState.RUNNING and rig.io.read("XV-106.CMD_OPEN")

    run(rig, 800.0, inv)  # 2,000 kg at a net 2 kg/s: the first fill to 80 % takes 800 s
    levels, feeding = [], []
    for _ in range(round(600.0 / DT)):
        tick(rig)
        inv.check()
        levels.append(rig.plant.hopper.level_pct)
        feeding.append(rig.io.read("M-103.RUN"))
        assert rig.io.read("XV-106.CMD_OPEN")  # discharge enabled throughout
    starts = sum(1 for a, b in zip(feeding, feeding[1:]) if b and not a)
    stops = sum(1 for a, b in zip(feeding, feeding[1:]) if a and not b)
    assert starts >= 2 and stops >= 2
    assert 58.0 < min(levels) and max(levels) < 82.0  # between the restart point and the switch
    assert rig.line.state == LineState.RUNNING
    assert rig.plant.spilled_kg == 0.0 and rig.line.alarms.latched_alarms == []


def test_a_downstream_stop_is_not_an_alarm_and_the_buffer_fills_to_the_switch():
    rig = build_rig(plant_overrides={"bin_level_kg": 9_000.0})
    rig.line.start()
    run(rig, 3.0)
    rig.plant.downstream.stopped = True
    run(rig, 0.2)
    assert not rig.io.read("XV-106.CMD_OPEN")
    run(rig, 400.0)  # nothing drawn off: the hopper fills to the high switch and the feed holds
    assert rig.plant.hopper.level_pct >= 80.0 and not rig.io.read("M-103.RUN")
    assert rig.line.state == LineState.RUNNING and rig.line.alarms.latched_alarms == []


def test_a_batch_discharge_waiting_for_the_downstream_never_times_out():
    """The discharge timeout (600 s on the rig) counts only while the
    downstream is ready: a wait longer than it isn't the hopper failing to
    empty."""
    rig = build_rig()
    rig.line.select_batch()
    rig.line.set_recipe("A", 50)
    rig.line.set_hold(1)
    rig.plant.downstream.stopped = True
    tick(rig)
    rig.line.start()
    for _ in range(round(60.0 / DT)):
        tick(rig)
        if rig.line.state == LineState.DISCHARGING:
            break
    assert rig.line.state == LineState.DISCHARGING
    run(rig, 700.0)  # longer than the discharge timeout
    assert rig.line.state == LineState.DISCHARGING and rig.line.fault_reason is None
    assert not rig.io.read("XV-106.CMD_OPEN")

    rig.plant.downstream.stopped = False
    run(rig, 60.0)
    assert rig.line.state == LineState.IDLE and rig.line.mode == LineMode.BATCH
    assert rig.line.batches_completed == 1
