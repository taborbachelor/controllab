import pytest

from services.testing.rig import build_rig, run
from services.testing.vocabulary import ScenarioError, apply_field, read_field, values_match


def test_apply_field_rejects_unknown_key():
    rig = build_rig()
    with pytest.raises(ScenarioError):
        apply_field(rig, "not_a_real_field", True)


def test_read_field_rejects_unknown_key():
    rig = build_rig()
    with pytest.raises(ScenarioError):
        read_field(rig, "not_a_real_field")


def test_estop_rejects_invalid_value():
    rig = build_rig()
    with pytest.raises(ScenarioError):
        apply_field(rig, "estop", "sideways")


@pytest.mark.parametrize(
    "key,value,check",
    [
        ("conveyor_trip", True, lambda rig: rig.plant.conveyor.motor.trip_now is True),
        ("feeder_trip", True, lambda rig: rig.plant.feeder.motor.trip_now is True),
        ("conveyor_fail_to_start", True, lambda rig: rig.plant.conveyor.motor.fail_to_start is True),
        ("feeder_fail_to_start", True, lambda rig: rig.plant.feeder.motor.fail_to_start is True),
        ("gate_stuck", True, lambda rig: rig.plant.gate.stuck is True),
        ("belt_slip", True, lambda rig: rig.plant.conveyor.motion_switch_stuck_false is True),
    ],
)
def test_simple_flag_actions_set_the_expected_attribute(key, value, check):
    rig = build_rig()
    apply_field(rig, key, value)
    assert check(rig)


def test_estop_tripped_and_healthy():
    rig = build_rig()
    apply_field(rig, "estop", "tripped")
    assert rig.plant.estop.tripped is True
    apply_field(rig, "estop", "healthy")
    assert rig.plant.estop.tripped is False


def test_start_stop_reset_acknowledge_reach_line_controller():
    rig = build_rig()
    apply_field(rig, "start", True)
    assert rig.line._start_requested is True  # noqa: SLF001 -- verifying the wiring, not the behavior
    apply_field(rig, "stop", True)
    assert rig.line._stop_requested is True  # noqa: SLF001
    apply_field(rig, "reset", True)
    assert rig.line._reset_requested is True  # noqa: SLF001
    apply_field(rig, "acknowledge", True)
    assert rig.line._acknowledge_requested is True  # noqa: SLF001


def test_hopper_and_bin_level_pct_compute_from_capacity():
    rig = build_rig()
    apply_field(rig, "hopper_level_pct", 50.0)
    assert rig.plant.hopper.level_kg == pytest.approx(0.5 * rig.plant.hopper.capacity_kg)
    apply_field(rig, "bin_level_pct", 10.0)
    assert rig.plant.bin.level_kg == pytest.approx(0.10 * rig.plant.bin.capacity_kg)


def test_read_field_line_state_is_lowercase_string():
    rig = build_rig()
    assert read_field(rig, "line_state") == "idle"


def test_read_field_spilled_is_a_derived_boolean():
    rig = build_rig()
    assert read_field(rig, "spilled") is False
    rig.plant.spilled_kg = 1.0
    assert read_field(rig, "spilled") is True


def test_read_field_any_unacknowledged_trip_and_latched_alarm_ids():
    rig = build_rig()
    assert read_field(rig, "any_unacknowledged_trip") is False
    assert read_field(rig, "latched_alarm_ids") == []

    apply_field(rig, "hopper_level_pct", 97.5)  # above the 95% high-high threshold
    # Two ticks: the first is when plant_scan()'s publish step makes the
    # new level visible on WT-105 (it runs after line.scan() within a
    # tick, same as every other "force a level" test in this codebase);
    # the second is when alarms.scan() actually observes it.
    run(rig, 0.2)
    assert read_field(rig, "any_unacknowledged_trip") is True
    assert read_field(rig, "latched_alarm_ids") == ["WT-105.HIGH_HIGH"]


def test_values_match_uses_float_tolerance():
    assert values_match(0.1 + 0.2, 0.3) is True  # classic float-drift case
    assert values_match(1.0, 2.0) is False


def test_values_match_distinguishes_bool_from_numeric():
    """bool is a subclass of int in Python -- if a scenario author
    writes `expect: {spilled: 1}` meaning "truthy" instead of `true`,
    that should NOT silently match the real bool False/True read_field
    returns. Only this direction matters in practice: every function in
    READ_FIELDS returns bool/str/float/None, never a plain int, so the
    reverse (an int actual compared to a bool expected) never occurs."""
    assert values_match(True, 1) is False
    assert values_match(False, 0) is False


def test_values_match_exact_for_strings_and_none():
    assert values_match("idle", "idle") is True
    assert values_match("idle", "running") is False
    assert values_match(None, None) is True
