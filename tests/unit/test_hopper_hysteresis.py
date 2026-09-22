from services.control.hopper_hysteresis import HopperHysteresis


def test_starts_wanting_to_feed():
    h = HopperHysteresis()
    assert h.evaluate(hopper_high=False, hopper_level_pct=50.0) is True


def test_stops_at_high():
    h = HopperHysteresis(restart_below_pct=60.0)
    assert h.evaluate(hopper_high=True, hopper_level_pct=80.0) is False


def test_stays_off_between_high_and_restart_point():
    h = HopperHysteresis(restart_below_pct=60.0)
    h.evaluate(hopper_high=True, hopper_level_pct=80.0)
    assert h.evaluate(hopper_high=False, hopper_level_pct=70.0) is False  # draining, not low enough yet
    assert h.evaluate(hopper_high=False, hopper_level_pct=61.0) is False


def test_resumes_below_restart_point():
    h = HopperHysteresis(restart_below_pct=60.0)
    h.evaluate(hopper_high=True, hopper_level_pct=80.0)
    assert h.evaluate(hopper_high=False, hopper_level_pct=59.9) is True


def test_hopper_high_wins_even_if_level_pct_disagrees():
    """hopper_high (the actual LSH-105 switch) is authoritative over the
    computed percentage -- if they ever disagree, trust the switch."""
    h = HopperHysteresis(restart_below_pct=60.0)
    assert h.evaluate(hopper_high=True, hopper_level_pct=10.0) is False


def test_custom_restart_point():
    h = HopperHysteresis(restart_below_pct=40.0)
    h.evaluate(hopper_high=True, hopper_level_pct=90.0)
    assert h.evaluate(hopper_high=False, hopper_level_pct=45.0) is False
    assert h.evaluate(hopper_high=False, hopper_level_pct=35.0) is True
