from services.simulation.equipment.vessel import Hopper, MaterialBin


def test_bin_discharge_limited_by_level():
    bin_ = MaterialBin("BIN-1", capacity_kg=100.0, level_kg=5.0)
    actual = bin_.discharge(20.0)
    assert actual == 5.0
    assert bin_.level_kg == 0.0
    assert bin_.empty


def test_bin_low_threshold():
    bin_ = MaterialBin("BIN-1", capacity_kg=100.0, level_kg=50.0, low_pct=10.0)
    assert not bin_.low
    bin_.discharge(45.0)
    assert bin_.level_kg == 5.0
    assert bin_.low


def test_hopper_receive_spills_once_full():
    h = Hopper("HOP-1", capacity_kg=100.0, level_kg=90.0)
    spilled = h.receive(20.0)
    assert h.level_kg == 100.0
    assert spilled == 10.0


def test_hopper_high_and_high_high_thresholds():
    h = Hopper("HOP-1", capacity_kg=100.0, high_pct=80.0, high_high_pct=95.0)
    h.receive(79.0)
    assert not h.high
    h.receive(1.0)
    assert h.high
    assert not h.high_high
    h.receive(15.0)
    assert h.high_high


def test_hopper_draws_at_fixed_rate_and_tracks_total():
    h = Hopper("HOP-1", capacity_kg=100.0, level_kg=10.0, draw_rate_kg_s=3.0)
    h.step(dt=1.0)
    assert h.level_kg == 7.0
    assert h.total_discharged_kg == 3.0


def test_hopper_draw_never_goes_negative():
    h = Hopper("HOP-1", capacity_kg=100.0, level_kg=1.0, draw_rate_kg_s=3.0)
    h.step(dt=1.0)
    assert h.level_kg == 0.0
    assert h.total_discharged_kg == 1.0
