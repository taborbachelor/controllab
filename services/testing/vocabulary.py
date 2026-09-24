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
APPLY_ACTIONS here — reaching "running" (or "manual") means actually
driving the controller there (ticking), not a one-shot attribute set, so
it doesn't fit the apply(rig, value) -> None shape everything else in this
module has.
"""
from __future__ import annotations

import math
from typing import Callable

from services.control.errors import ControlError
from services.control.line_state import inhibit_names
from services.testing.rig import Rig


class ScenarioError(Exception):
    """A malformed scenario: an unknown vocabulary key, or a value of
    the wrong shape. Raised at setup time -- a bad scenario file should
    fail loudly before anything executes, not produce a confusing
    runtime error partway through a run."""


class StatusWithheld:
    """A controller seen WITHOUT its status block: commands and scans pass
    through, every state read raises NotObservable. What
    run_scenario(status=False) runs, so the suite and the review gate can
    ask, deterministically, what a scenario proves from field evidence
    alone -- the same view the real-time runner has of a controller that
    publishes no status (Phase 9 step 3)."""

    def __init__(self, line) -> None:
        self._line = line

    def __getattr__(self, name):  # the pushbuttons and scan
        return getattr(self._line, name)

    @property
    def command_sink(self):
        return self._line.command_sink

    @command_sink.setter
    def command_sink(self, sink) -> None:
        self._line.command_sink = sink

    def _withheld(self):
        raise NotObservable("the controller's status block is withheld")

    state = property(_withheld)
    mode = property(_withheld)
    source_bin = property(_withheld)
    active_bin = property(_withheld)
    batch_loaded_kg = property(_withheld)
    batches_completed = property(_withheld)
    fault_reason = property(_withheld)
    alarms = property(_withheld)
    start_inhibit = property(_withheld)


class NotObservable(Exception):
    """The field exists, but this controller doesn't publish it (Phase 9
    step 3): an external controller without ControlLab's status block
    has no line state, fault reason, alarms or start inhibit to read.
    The runner reports such an expectation as not observed -- never as
    failed, and never as silently passed."""


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


def _pushbutton(name: str):
    """A Manual-mode pushbutton (docs/CONTROL-LAB.md §6.1): one-shot, like
    start/stop -- `true` presses it."""
    def apply(rig: Rig, value: bool) -> None:
        if value:
            getattr(rig.line, name)()
    return apply


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


def _apply_conveyor_jam(rig: Rig, value: bool) -> None:
    rig.plant.conveyor.jammed = value


def _apply_bin_bridged(rig: Rig, value: bool) -> None:
    rig.plant.bin.bridged = value


def _apply_belt_slip(rig: Rig, value: bool) -> None:
    rig.plant.conveyor.motion_switch_stuck_false = value


# Field resets (Phase 6 step 3): clearing a device's OWN latched fault --
# resetting a VFD fault, an overload relay, or a gate actuator locally at
# the equipment. Separate from un-injecting the cause (feeder_trip: false
# etc.) on purpose: in a real plant those are two different actions, and
# tests/integration/test_line_controller.py::test_reset_succeeds_once_a_
# passthrough_cause_clears already documents that recovery needs both.
# Plant-side only -- there is no I/O tag for this, so Control can't do it,
# the same as a real line where someone walks to the MCC. One-shot like
# start/stop: true performs the reset, false is a no-op.


def _apply_feeder_drive_reset(rig: Rig, value: bool) -> None:
    if value:
        rig.plant.feeder.motor.clear_fault()


def _apply_conveyor_overload_reset(rig: Rig, value: bool) -> None:
    if value:
        rig.plant.conveyor.motor.clear_fault()


def _apply_gate_reset(rig: Rig, value: bool) -> None:
    if value:
        rig.plant.gate.clear_fault()


def _apply_feeder_jam(rig: Rig, value: bool) -> None:
    """true: the feeder's discharge jams (flow stops, the drive keeps
    running, the plug switch makes after it has pushed against the jam
    for plug_detect_s); false: the jam is physically cleared."""
    rig.plant.feeder.jammed = value


# Sensor faults (Phase 4 completion; services/simulation/equipment/
# instruments.py). The value is the instrument's tag. stuck: it keeps its
# last reading; failed: signal lost (WT-105 reads 0 with its channel
# diagnostic set; a switch reads 0, which a fail-safe switch reports as
# tripped); restored: repaired at the field.


def _instrument_action(method: str):
    def apply(rig: Rig, value: str) -> None:
        if value not in rig.io or not rig.io.tag(value).type.is_input:
            raise ScenarioError(f"sensor_{method}: {value!r} is not an input instrument tag")
        try:
            getattr(rig.plant.instruments, {"stuck": "stick", "failed": "fail", "restored": "restore"}[method])(value)
        except ValueError as e:
            raise ScenarioError(f"sensor_{method}: {e}") from e
    return apply


# Degraded instruments (instruments.py): a reading that is plausible but wrong.
# The value names the instrument and the one parameter that shapes the fault:
#   sensor_noise: {tag: WT-105, amplitude: 30}      +/- 30 kg of noise
#   sensor_drift: {tag: WT-105, rate_per_s: -10}   reading walks off at -10 kg/s
#   sensor_slow:  {tag: ZSS-104, seconds: 1.5}      reports what was true 1.5 s ago
def _degraded_action(key: str, method: str, param: str):
    def apply(rig: Rig, value: dict) -> None:
        if not isinstance(value, dict) or set(value) != {"tag", param}:
            raise ScenarioError(f"{key}: expected {{tag: <input tag>, {param}: <number>}}, got {value!r}")
        tag, number = value["tag"], value[param]
        if tag not in rig.io or not rig.io.tag(tag).type.is_input:
            raise ScenarioError(f"{key}: {tag!r} is not an input instrument tag")
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise ScenarioError(f"{key}: {param} must be a number, got {number!r}")
        try:
            getattr(rig.plant.instruments, method)(tag, number)
        except ValueError as e:
            raise ScenarioError(f"{key}: {e}") from e
    return apply


def _apply_recipe(rig: Rig, value: dict) -> None:
    """The batch recipe setpoints: {A: kg, B: kg, C: kg}; a bin left out is 0."""
    if not isinstance(value, dict) or not set(value) <= {"A", "B", "C"}:
        raise ScenarioError(f"recipe: expected {{A: kg, B: kg, C: kg}}, got {value!r}")
    for bin_ in "ABC":
        kg = value.get(bin_, 0)
        if isinstance(kg, bool) or not isinstance(kg, (int, float)) or kg < 0:
            raise ScenarioError(f"recipe: {bin_} must be a number of kg >= 0, got {kg!r}")
        rig.line.set_recipe(bin_, kg)


def _apply_hold_s(rig: Rig, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ScenarioError(f"hold_s must be a number of seconds >= 0, got {value!r}")
    rig.line.set_hold(value)


def _apply_outlet_stuck(rig: Rig, value: bool) -> None:
    rig.plant.outlet.stuck = value


def _apply_outlet_plugged(rig: Rig, value: bool) -> None:
    rig.plant.outlet_plugged = value


def _apply_outlet_reset(rig: Rig, value: bool) -> None:
    if value:
        rig.plant.outlet.clear_fault()


def _apply_source_bin(rig: Rig, value: str) -> None:
    """The HMI's source-bin setpoint: the bin the next start draws from."""
    if value not in ("A", "B", "C"):
        raise ScenarioError(f"source_bin must be 'A', 'B' or 'C', got {value!r}")
    rig.line.select_source(value)


def _bin_level(which: str):
    def apply(rig: Rig, value: float) -> None:
        bin_ = rig.plant.bins[which][0]
        bin_.level_kg = (value / 100.0) * bin_.capacity_kg
    return apply


def _gate_stuck(which: str):
    def apply(rig: Rig, value: bool) -> None:
        rig.plant.bins[which][1].stuck = value
    return apply


def _gate_reset(which: str):
    def apply(rig: Rig, value: bool) -> None:
        if value:
            rig.plant.bins[which][1].clear_fault()
    return apply


def _apply_hopper_level_pct(rig: Rig, value: float) -> None:
    rig.plant.hopper.level_kg = (value / 100.0) * rig.plant.hopper.capacity_kg


def _apply_bin_level_pct(rig: Rig, value: float) -> None:
    rig.plant.bin.level_kg = (value / 100.0) * rig.plant.bin.capacity_kg


APPLY_ACTIONS: dict[str, Callable[[Rig, object], None]] = {
    "start": _apply_start,
    "stop": _apply_stop,
    "reset": _apply_reset,
    "acknowledge": _apply_acknowledge,
    "select_manual": _pushbutton("select_manual"),
    "select_auto": _pushbutton("select_auto"),
    "select_batch": _pushbutton("select_batch"),
    "open_outlet": _pushbutton("open_outlet"),
    "close_outlet": _pushbutton("close_outlet"),
    "start_conveyor": _pushbutton("start_conveyor"),
    "stop_conveyor": _pushbutton("stop_conveyor"),
    "open_gate": _pushbutton("open_gate"),
    "close_gate": _pushbutton("close_gate"),
    "start_feeder": _pushbutton("start_feeder"),
    "stop_feeder": _pushbutton("stop_feeder"),
    "estop": _apply_estop,
    "conveyor_trip": _apply_conveyor_trip,
    "feeder_trip": _apply_feeder_trip,
    "conveyor_fail_to_start": _apply_conveyor_fail_to_start,
    "feeder_fail_to_start": _apply_feeder_fail_to_start,
    "gate_stuck": _apply_gate_stuck,
    "belt_slip": _apply_belt_slip,
    "conveyor_jam": _apply_conveyor_jam,
    "bin_bridged": _apply_bin_bridged,
    "feeder_jam": _apply_feeder_jam,
    "sensor_stuck": _instrument_action("stuck"),
    "sensor_failed": _instrument_action("failed"),
    "sensor_restored": _instrument_action("restored"),
    "source_bin": _apply_source_bin,
    "recipe": _apply_recipe,
    "outlet_stuck": _apply_outlet_stuck,
    "outlet_plugged": _apply_outlet_plugged,
    "outlet_reset": _apply_outlet_reset,
    "hold_s": _apply_hold_s,
    "bin_b_level_pct": _bin_level("B"),
    "bin_c_level_pct": _bin_level("C"),
    "gate_b_stuck": _gate_stuck("B"),
    "gate_c_stuck": _gate_stuck("C"),
    "gate_b_reset": _gate_reset("B"),
    "gate_c_reset": _gate_reset("C"),
    "sensor_noise": _degraded_action("sensor_noise", "add_noise", "amplitude"),
    "sensor_drift": _degraded_action("sensor_drift", "drift", "rate_per_s"),
    "sensor_slow": _degraded_action("sensor_slow", "lag", "seconds"),
    "feeder_drive_reset": _apply_feeder_drive_reset,
    "conveyor_overload_reset": _apply_conveyor_overload_reset,
    "gate_reset": _apply_gate_reset,
    "hopper_level_pct": _apply_hopper_level_pct,
    "bin_level_pct": _apply_bin_level_pct,
}


READ_FIELDS: dict[str, Callable[[Rig], object]] = {
    "line_state": lambda rig: rig.line.state.name.lower(),
    "fault_reason": lambda rig: rig.line.fault_reason,
    # The operator-selected mode, "auto" or "manual" (docs/CONTROL-LAB.md §6.1).
    "mode": lambda rig: rig.line.mode.name.lower(),
    "conveyor_running": lambda rig: rig.plant.conveyor.motor.running,
    "feeder_running": lambda rig: rig.plant.feeder.motor.running,
    # What the controller is COMMANDING the field to do: its output coils,
    # which ControlLab sees whether or not the controller publishes any
    # status. The command, not the device's response -- a trip drops the
    # command in the same scan, while the gate takes its travel time to
    # close -- so these show a controller's decision in field terms.
    "feeder_run_commanded": lambda rig: rig.io.read("M-103.RUN"),
    "conveyor_run_commanded": lambda rig: rig.io.read("M-104.RUN"),
    "gate_open_commanded": lambda rig: rig.io.read("XV-102.CMD_OPEN"),
    # Material actually leaving the feeder (field truth). With feeder_running
    # it tells a jam (running, not flowing) apart from a stopped feeder.
    "feeder_flowing": lambda rig: rig.plant.feed_flow_kg_s > 0,
    "gate_open": lambda rig: rig.plant.gate.is_open,
    "gate_b_open": lambda rig: rig.plant.gate_b.is_open,
    "gate_c_open": lambda rig: rig.plant.gate_c.is_open,
    "gate_b_open_commanded": lambda rig: rig.io.read("XV-112.CMD_OPEN"),
    "gate_c_open_commanded": lambda rig: rig.io.read("XV-122.CMD_OPEN"),
    # The source bin the next start draws from, and the bin the line is
    # drawing from now ("none" at rest).
    "source_bin": lambda rig: rig.line.source_bin,
    "active_bin": lambda rig: rig.line.active_bin or "none",
    # The batch (master specification, item 7): this (or the last) batch's
    # weigh-in, the batches completed, and the hopper's outlet gate.
    "batch_loaded_kg": lambda rig: rig.line.batch_loaded_kg,
    "batches_completed": lambda rig: rig.line.batches_completed,
    "outlet_open": lambda rig: rig.plant.outlet.is_open,
    "outlet_open_commanded": lambda rig: rig.io.read("XV-106.CMD_OPEN"),
    "estop_healthy": lambda rig: rig.plant.estop.healthy,
    "spilled_kg": lambda rig: rig.plant.spilled_kg,
    "spilled": lambda rig: rig.plant.spilled_kg > 1e-9,
    # Nothing left on the conveyor (field truth): what a stop sequence's
    # belt purge is for (docs/CONTROL-LAB.md §6.2).
    "belt_empty": lambda rig: rig.plant.conveyor.mass_on_belt_kg <= 1e-9,
    "hopper_level_kg": lambda rig: rig.plant.hopper.level_kg,
    # What WT-105 is reporting on the wire -- which a stuck or failed
    # transmitter makes differ from hopper_level_kg, the truth. Agreement is
    # judged the way a commissioning engineer checks a transmitter against a
    # known level: within 5 kg (0.25 % of the 2,000 kg span; Modbus carries
    # 0.1 kg).
    "hopper_weight_agrees": lambda rig: abs(rig.io.read("WT-105") - rig.plant.hopper.level_kg) <= 5.0,
    "any_unacknowledged_trip": lambda rig: rig.line.alarms.any_unacknowledged_trip(),
    "latched_alarm_ids": lambda rig: sorted(a.id for a in rig.line.alarms.latched_alarms),
    # The first-out alarm's id, or null: which alarm started this episode.
    "first_out": lambda rig: next((a.id for a in rig.line.alarms.all_alarms if a.first_out), None),
    # Why the most recent start request was refused: sorted reason names, or
    # ["NONE"]. Set only when a start is evaluated, so asserting it proves a
    # start was issued -- see StartInhibit (services/control/line_state.py).
    "start_inhibit": lambda rig: inhibit_names(rig.line.start_inhibit),
}


# The read fields that come from the CONTROLLER (its status block, when
# it's external) rather than from the plant. Everything else is field
# truth, observable against any controller. Tied to READ_FIELDS by a test
# (tests/unit/test_observability.py), so a new controller field can't
# silently be treated as always observable.
CONTROLLER_FIELDS = frozenset(
    {"line_state", "mode", "fault_reason", "any_unacknowledged_trip", "latched_alarm_ids", "first_out", "start_inhibit",
     "source_bin", "active_bin", "batch_loaded_kg", "batches_completed"}
)


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
