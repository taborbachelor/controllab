from services.simulation.engine import SimClock


def test_advances_by_fixed_step():
    clock = SimClock(dt_s=0.1)
    assert clock.time_s == 0.0
    clock.tick()
    assert clock.time_s == 0.1
    clock.tick()
    assert clock.time_s == 0.2


def test_no_float_drift_over_many_ticks():
    clock = SimClock(dt_s=0.1)
    for _ in range(1000):
        clock.tick()
    assert clock.time_s == 100.0
    assert clock.tick_count == 1000


def test_reset():
    clock = SimClock(dt_s=0.1)
    clock.tick()
    clock.tick()
    clock.reset()
    assert clock.time_s == 0.0
    assert clock.tick_count == 0


def test_rejects_nonpositive_step():
    import pytest

    with pytest.raises(ValueError):
        SimClock(dt_s=0.0)
    with pytest.raises(ValueError):
        SimClock(dt_s=-1.0)
