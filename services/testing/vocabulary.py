"""The vocabulary a scenario file can use in `given`/`when`/`expect`: a
small, explicit set of named fields mapped onto real rig actions and
observations. Deliberately not a general "poke any attribute" DSL —
every key here is a real, meaningful signal or action a commissioning
engineer would actually reason about (docs/CONTROL-LAB.md §7, item 2:
"Tests observe the way a commissioning engineer does").

Unknown keys are a hard error (ScenarioError), not silently ignored — a
typo'd key in a YAML file should fail loudly at setup time, not produce
a scenario that silently checks nothing.

`given.line_state` is handled separately by the runner, not through
APPLY_ACTIONS here — reaching "running" means actually driving the
sequence (ticking), not a one-shot attribute set, so it doesn't fit the
apply(rig, value) -> None shape everything else in this module has.
"""
from __future__ import annotations

import math
from typing import Callable

from services.control.errors import ControlError
from services.testing.rig import Rig


class ScenarioError(Exception):
    """A malformed scenario: an unknown vocabulary key, or a value of
    the wrong shape. Raised at setup time -- a bad scenario file should
    fail loudly before anything executes, not produce a confusing
    runtime error partway through a run."""


def _apply_start(rig: Rig, value: bool) -> None:
    if value:
        rig.line.start()


def _apply_stop(rig: Rig, value: bool) -> None:
    if value:
        rig.line.stop()


def _apply_reset(rig: Rig, value: bool) -> None:
    if value:
        rig.line.reset()


def _apply_acknowledge(rig: Rig, value: bool) -> None:
    if value:
        rig.line.acknowledge()


def _apply_estop(rig: Rig, value: str) -> None:
    if value == "tripped":
        rig.plant.estop.trip()
    elif value == "healthy":
        rig.plant.estop.reset()
    else:
        raise ScenarioError(f"estop must be 'tripped' or 'healthy', got {value!r}")


def _apply_conveyor_trip(rig: Rig, value: bool) -> None:
    rig.plant.conveyor.motor.trip_now = value


def _apply_feeder_trip(rig: Rig, value: bool) -> None:
    rig.plant.feeder.motor.trip_now = value


def _apply_conveyor_fail_to_start(rig: Rig, value: bool) -> None:
    rig.plant.conveyor.motor.fail_to_start = value


def _apply_feeder_fail_to_start(rig: Rig, value: bool) -> None:
    rig.plant.feeder.motor.fail_to_start = value


def _apply_gate_stuck(rig: Rig, value: bool) -> None:
    rig.plant.gate.stuck = value


def _apply_belt_slip(rig: Rig, value: bool) -> None:
    rig.plant.conveyor.motion_switch_stuck_false = value


def _apply_hopper_level_pct(rig: Rig, value: float) -> None:
    rig.plant.hopper.level_kg = (value / 100.0) * rig.plant.hopper.capacity_kg


def _apply_bin_level_pct(rig: Rig, value: float) -> None:
    rig.plant.bin.level_kg = (value / 100.0) * rig.plant.bin.capacity_kg


APPLY_ACTIONS: dict[str, Callable[[Rig, object], None]] = {
    "start": _apply_start,
    "stop": _apply_stop,
    "reset": _apply_reset,
    "acknowledge": _apply_acknowledge,
    "estop": _apply_estop,
    "conveyor_trip": _apply_conveyor_trip,
    "feeder_trip": _apply_feeder_trip,
    "conveyor_fail_to_start": _apply_conveyor_fail_to_start,
    "feeder_fail_to_start": _apply_feeder_fail_to_start,
    "gate_stuck": _apply_gate_stuck,
    "belt_slip": _apply_belt_slip,
    "hopper_level_pct": _apply_hopper_level_pct,
    "bin_level_pct": _apply_bin_level_pct,
}


READ_FIELDS: dict[str, Callable[[Rig], object]] = {
    "line_state": lambda rig: rig.line.state.name.lower(),
    "fault_reason": lambda rig: rig.line.fault_reason,
    "conveyor_running": lambda rig: rig.plant.conveyor.motor.running,
    "feeder_running": lambda rig: rig.plant.feeder.motor.running,
    "gate_open": lambda rig: rig.plant.gate.is_open,
    "estop_healthy": lambda rig: rig.plant.estop.healthy,
    "spilled_kg": lambda rig: rig.plant.spilled_kg,
    "spilled": lambda rig: rig.plant.spilled_kg > 1e-9,
    "hopper_level_kg": lambda rig: rig.plant.hopper.level_kg,
    "any_unacknowledged_trip": lambda rig: rig.line.alarms.any_unacknowledged_trip(),
    "latched_alarm_ids": lambda rig: sorted(a.id for a in rig.line.alarms.latched_alarms),
}


def apply_field(rig: Rig, key: str, value: object) -> None:
    try:
        action = APPLY_ACTIONS[key]
    except KeyError:
        raise ScenarioError(
            f"unknown given/when field: {key!r} (known: {sorted(APPLY_ACTIONS)}, plus given.line_state)"
        ) from None
    try:
        action(rig, value)
    except ControlError as e:
        raise ScenarioError(f"{key}: {e}") from e


def read_field(rig: Rig, key: str) -> object:
    try:
        reader = READ_FIELDS[key]
    except KeyError:
        raise ScenarioError(f"unknown expect field: {key!r} (known: {sorted(READ_FIELDS)})") from None
    return reader(rig)


def values_match(actual: object, expected: object) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if isinstance(actual, bool):
            return False
        return math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-6)
    return actual == expected
