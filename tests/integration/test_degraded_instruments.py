"""Degraded instruments (services/simulation/equipment/instruments.py):
noise, drift and slow response -- readings that are plausible but wrong --
and what the controller does with them. The sustained properties a
declarative scenario can't show (a scenario passes the moment its
expectations first hold) are here."""
import pytest

from services.control.line_state import LineState
from services.simulation.equipment.instruments import InstrumentFault
from services.testing.rig import DT, build_rig, run, tick


def readings(rig, tag, seconds):
    out = []
    for _ in range(round(seconds / DT)):
        tick(rig)
        out.append(rig.io.read(tag))
    return out


# ---- the instrument model -----------------------------------------------------


def test_noise_is_bounded_reproducible_and_seeded():
    def noisy(seed=0):
        rig = build_rig(plant_overrides={"instrument_seed": seed})
        rig.plant.hopper.level_kg = 1_000.0
        tick(rig)
        rig.plant.instruments.add_noise("WT-105", 30.0)
        return readings(rig, "WT-105", 5.0)

    first = noisy()
    assert first == noisy()  # the same readings every run
    assert noisy(seed=1) != first  # a different seed, a different stream
    assert all(970.0 <= v <= 1_030.0 for v in first) and len(set(first)) > 10


def test_noise_is_clamped_to_the_calibrated_range():
    rig = build_rig()
    rig.plant.hopper.level_kg = 5.0
    tick(rig)
    rig.plant.instruments.add_noise("WT-105", 30.0)
    assert min(readings(rig, "WT-105", 5.0)) == 0.0  # a 4-20 mA loop can't read below range


def test_drift_walks_away_linearly_and_pins_at_full_scale():
    rig = build_rig()
    rig.plant.hopper.level_kg = 1_000.0
    tick(rig)
    rig.plant.instruments.drift("WT-105", 50.0)
    values = readings(rig, "WT-105", 30.0)
    assert values[9] == pytest.approx(1_050.0)  # 1 s in
    assert values[-1] == 2_000.0  # the transmitter's full scale, not 2,500 kg
    assert rig.plant.hopper.level_kg == 1_000.0  # the process never moved


def test_a_slow_instrument_reports_what_was_true_earlier():
    rig = build_rig()
    rig.plant.instruments.lag("ZSS-104", 1.0)
    rig.line.start()
    history = []
    for _ in range(30):
        tick(rig)
        history.append((rig.plant.conveyor.motion_confirmed, rig.io.read("ZSS-104")))
    moved = next(i for i, (true, _) in enumerate(history) if true)
    reported = next(i for i, (_, seen) in enumerate(history) if seen)
    assert reported - moved == 10  # 1.0 s later, to the tick


def test_restore_clears_a_degraded_instrument_and_one_fault_replaces_another():
    rig = build_rig()
    tick(rig)
    inst = rig.plant.instruments
    inst.add_noise("WT-105", 30.0)
    inst.drift("WT-105", -5.0)
    assert inst.fault("WT-105") is InstrumentFault.DRIFTING
    inst.restore("WT-105")
    assert inst.fault("WT-105") is InstrumentFault.HEALTHY
    rig.plant.hopper.level_kg = 700.0
    tick(rig)
    assert rig.io.read("WT-105") == 700.0


@pytest.mark.parametrize("call", [
    lambda i: i.add_noise("LSH-105", 1.0),  # a switch has no analog reading
    lambda i: i.drift("ZSS-104", 1.0),
    lambda i: i.add_noise("WT-105", 0.0),
    lambda i: i.drift("WT-105", 0.0),
    lambda i: i.lag("WT-105", 0.0),
    lambda i: i.lag("NOT-A-TAG", 1.0),
])
def test_invalid_degradations_are_refused(call):
    rig = build_rig()
    tick(rig)
    with pytest.raises(ValueError):
        call(rig.plant.instruments)


# ---- what the controller does with them -----------------------------------------


def test_noise_near_high_high_never_trips_a_running_line():
    """30 s of +/- 30 kg noise with the hopper 1 % under the high-high point:
    peaks cross 95 % again and again, and the 0.5 s vote debounce holds."""
    rig = build_rig()
    rig.plant.hopper.level_kg = 1_880.0  # 94 %; the line doesn't feed past the high switch
    rig.plant.downstream.stopped = True  # and nothing draws it down: the level stays put
    rig.line.start()
    run(rig, 3.0)
    assert rig.line.state == LineState.RUNNING
    rig.plant.instruments.add_noise("WT-105", 30.0)
    peaks = 0
    for _ in range(300):
        tick(rig)
        peaks += rig.io.read("WT-105") >= 1_900.0
        assert rig.line.state == LineState.RUNNING
    assert peaks > 10  # the noise really did cross the setpoint


def test_without_the_debounce_the_same_noise_trips_the_line():
    """Why the debounce exists: the same run with an instant transmitter vote."""
    rig = build_rig()
    rig.line.interlocks.hh_weight_debounce_s = 0.0
    rig.plant.hopper.level_kg = 1_880.0
    rig.plant.downstream.stopped = True
    rig.line.start()
    run(rig, 3.0)
    rig.plant.instruments.add_noise("WT-105", 30.0)
    run(rig, 30.0)
    assert (rig.line.state, rig.line.fault_reason) == (LineState.FAULTED, "hopper high-high")


def test_a_slightly_slow_motion_switch_is_tolerated_by_the_proof_window():
    rig = build_rig()
    rig.plant.instruments.lag("ZSS-104", 0.5)
    rig.line.start()
    run(rig, 4.0)
    assert rig.line.state == LineState.RUNNING


def test_a_drift_is_invisible_until_the_level_crosses_a_switch_point():
    """The cross-check compares the transmitter with the point switches, so a
    drift at a steady level between the switch points raises nothing, however
    far it goes: found writing the drift scenario, recorded as a limit."""
    rig = build_rig()
    rig.plant.hopper.level_kg = 1_000.0  # 50 %, well between the switch points
    tick(rig)
    rig.plant.instruments.drift("WT-105", -20.0)
    run(rig, 40.0)  # reading 800 kg low
    assert rig.io.read("WT-105") == pytest.approx(200.0, abs=1.0)
    assert not rig.line.alarms.latched_alarms
