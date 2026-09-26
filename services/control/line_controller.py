"""The line state machine (docs/CONTROL-LAB.md §6.1-6.2): the two modes,
Auto-mode sequencing, interlocks, and hopper hysteresis, wired together.

Auto is the default and the sequences below. Manual (completing Phase 2)
is one more state, MANUAL, in which the operator starts and stops each
device with its own pushbutton: the sequence is bypassed, the protection
is not. Every §6.3 row is enforced at the device it protects (the feeder
only onto a proven belt, nothing started at high-high, trips go to
FAULTED exactly as in Auto), plus one Manual-only rule: LSH-105 stops a
running feeder and refuses its start, standing in for the level control
Manual doesn't have, so a routine manual fill ends at the high switch
rather than in a high-high trip. The mode changes only at rest (IDLE, or
MANUAL with every device off) and survives FAULTED and ESTOPPED: a reset
returns the line to its mode's rest state, never with anything running.

Owns nothing from Simulation directly — only the three device-control
modules (MotorControl x2, GateControl) built in Phase 2 step 2, and the
Interlocks query object built on top of them. This file is automatically
covered by the architecture boundary guard test (tests/unit/test_control_
boundary.py), which scans every module in services/control/.

Start()/Stop()/Reset() are one-shot requests, like real momentary
pushbuttons: call the method to raise the request, scan() consumes it (at
most once) on however many scans it takes to become relevant, and it's a
no-op if the current state doesn't act on it (e.g. start() while already
RUNNING).

The four commands are also the one place Control reports anything
outward (Phase 5 step 3): an optional `command_sink` callable, None by
default, receives the command name at the moment it's issued. It exists
because a command can produce zero observable state change (stop() while
already IDLE) and a commissioning audit trail should still show it was
pressed -- the one fact the pull/diff telemetry in services/telemetry/
can't see by construction. Unconfigured, it's a no-op: no behavior
change, no I/O, no import of anything telemetry-related (the sink is a
plain callable; tests/unit/test_control_boundary.py enforces that
services/control/ never imports services.telemetry).
"""
from __future__ import annotations

from collections.abc import Callable

from services.control.alarms import AlarmManager
from services.control.gate_control import GateControl
from services.control.hopper_hysteresis import HopperHysteresis
from services.control.interlocks import Interlocks
from services.control.level_check import HopperLevelChecks
from services.control.line_state import BINS, BatchStep, LineMode, LineState, StartInhibit, StartStep
from services.control.motor_control import MotorControl
from services.simulation.engine.io_image import IOImage

# Trips whose cause is upstream of the conveyor (docs/CONTROL-LAB.md §6.3:
# trips cascade upstream; downstream keeps running so it can clear). On
# these, a running conveyor keeps running for the purge time so the belt
# empties into the hopper, then stops. Every other trip -- E-stop, hopper
# high-high, an unknown hopper level, any conveyor fault -- stops it at once.
CLEAR_BELT_ON = frozenset({
    "feeder trip", "feeder jam", "feeder failed to prove running", "gate travel fault", "gate failed to prove open",
})

# Manual mode's device pushbuttons (one-shot, like start()/stop()). A stop
# and a start of the same device in one scan leaves it stopped.
DEVICE_STARTS = frozenset({"start_conveyor", "open_gate", "start_feeder", "open_outlet"})
DEVICE_STOPS = frozenset({"stop_conveyor", "close_gate", "stop_feeder", "close_outlet"})
BATCH_STATES = frozenset({LineState.LOADING, LineState.PROCESSING, LineState.DISCHARGING, LineState.CLEANING})


class LineController:
    def __init__(
        self,
        io: IOImage,
        feeder_ctrl: MotorControl,
        conveyor_ctrl: MotorControl,
        gate_ctrl: GateControl,
        hopper_capacity_kg: float,
        feed_speed_pct: float = 100.0,
        restart_below_pct: float = 60.0,
        conveyor_proof_timeout_s: float = 3.0,
        purge_time_s: float = 15.0,
        hopper_high_pct: float = 80.0,
        hopper_high_high_pct: float = 95.0,
        conveyor_overcurrent_a: float = 15.0,
        no_flow_s: float = 15.0,
        gate_b_ctrl: GateControl | None = None,
        gate_c_ctrl: GateControl | None = None,
        outlet_ctrl: GateControl | None = None,
        batch_preact_kg: float = 50.0,
        batch_empty_kg: float = 5.0,
        batch_tolerance_kg: float = 10.0,
        discharge_timeout_s: float = 900.0,
    ) -> None:
        self.io = io
        self.feeder_ctrl = feeder_ctrl
        self.conveyor_ctrl = conveyor_ctrl
        self.gate_ctrl = gate_ctrl  # bin A's gate
        # Every bin's gate, by letter (master specification, item 6). A line
        # built without B and C is the original one-bin line.
        self.gates = {"A": gate_ctrl, **({"B": gate_b_ctrl} if gate_b_ctrl else {}),
                      **({"C": gate_c_ctrl} if gate_c_ctrl else {})}
        # The hopper's outlet gate (master specification, item 7); a line
        # without one has no Batch mode.
        self.outlet_ctrl = outlet_ctrl
        # Batch commissioning constants: stop feeding this much early (the
        # belt's in-flight load), "empty" means at or under batch_empty_kg,
        # a weigh-in this far off target is out of tolerance, and a discharge
        # that hasn't emptied the hopper by discharge_timeout_s has failed.
        self.batch_preact_kg = batch_preact_kg
        self.batch_empty_kg = batch_empty_kg
        self.batch_tolerance_kg = batch_tolerance_kg
        self.discharge_timeout_s = discharge_timeout_s
        self.interlocks = Interlocks(
            io, feeder_ctrl, conveyor_ctrl, gate_ctrl, hopper_capacity_kg, hopper_high_high_pct=hopper_high_high_pct,
            conveyor_overcurrent_a=conveyor_overcurrent_a, no_flow_s=no_flow_s, gates=self.gates,
        )
        self.hysteresis = HopperHysteresis(restart_below_pct)
        # The switch-vs-transmitter cross-checks, set to the switches'
        # commissioned points (docs/CONTROL-LAB.md §5.3).
        self.level_checks = HopperLevelChecks(hopper_high_pct, hopper_high_high_pct)
        # Built here, not injected, same as self.hysteresis -- AlarmManager
        # hardcodes this line's 9 alarms the same way Interlocks hardcodes
        # this line's tags, so it's not something a caller configures.
        self.alarms = AlarmManager(self.interlocks, self.level_checks)
        # Batch mode's alarms, appended after the built-in set.
        self.alarms.add("XV-106.TRAVEL_FAULT", "Hopper outlet gate travel fault",
                        lambda: self.outlet_ctrl is not None and self.outlet_ctrl.travel_fault)
        self.alarms.add("HOP-105.NOT_EMPTYING", "Batch discharge didn't empty the hopper", lambda: self._discharge_timed_out)
        self.alarms.add("BATCH.TOLERANCE", "Batch weighed in out of tolerance", lambda: self._batch_out_of_tolerance,
                        is_warning=True)

        self.feed_speed_pct = feed_speed_pct
        self.conveyor_proof_timeout_s = conveyor_proof_timeout_s
        self.purge_time_s = purge_time_s

        self.mode = LineMode.AUTO
        # The source bin, an HMI setpoint: the bin the NEXT start draws from.
        # active_bin is the one the line is drawing from now (taken at Start).
        self.source_bin = "A"
        self.active_bin: str | None = None
        # The batch recipe (HMI setpoints): kg from each bin, and the hold.
        self.recipe = {b: 0.0 for b in BINS}
        self.hold_s = 10.0
        self.batch_step: BatchStep | None = None
        self.batch_loaded_kg = 0.0  # this batch's (or the last one's) weigh-in so far
        self.batches_completed = 0
        self._batch_plan: list[tuple[str, float]] = []
        self._batch_index = 0
        self._batch_start_kg = 0.0
        self._batch_conveyor_proven = False
        self._batch_elapsed_s = 0.0
        self._discharge_timed_out = False
        self._batch_out_of_tolerance = False
        self.state = LineState.IDLE
        self.fault_reason: str | None = None
        self.last_start_refusal: list[str] = []
        # Machine-readable outcome of the most recent start request -- see
        # StartInhibit. Reporting only: nothing in this class reads it back.
        self.start_inhibit = StartInhibit.NONE
        self.start_step: StartStep | None = None

        self._step_elapsed_s = 0.0
        self._purge_elapsed_s = 0.0
        # STOPPING: the belt has proven moving during this stop, so losing
        # motion now is a trip, not a purge that counts on regardless.
        self._stop_belt_proven = False
        # FAULTED on an upstream trip: the conveyor is still clearing the belt.
        self.clearing_belt = False
        self._start_requested = False
        self._stop_requested = False
        self._reset_requested = False
        self._acknowledge_requested = False
        self._mode_request: LineMode | None = None
        self._device_requests: set[str] = set()
        # Manual mode's conveyor proof: once the belt has proven running
        # (RUNNING and ZSS-104) after a manual start, losing it is a trip;
        # never proving it within conveyor_proof_timeout_s is a fail-to-start.
        self._manual_conveyor_proven = False
        self._manual_conveyor_elapsed_s = 0.0

        # Phase 5 step 3 -- see the module docstring. Set by whoever
        # wants an audit trail of operator commands (in practice,
        # services/telemetry/events.py's EventLog.record_command); never
        # read by anything in Control itself.
        self.command_sink: Callable[[str], None] | None = None

    # ---- operator/HMI-style commands ----------------------------------

    def start(self) -> None:
        self._emit_command("start")
        self._start_requested = True

    def stop(self) -> None:
        self._emit_command("stop")
        self._stop_requested = True

    def reset(self) -> None:
        self._emit_command("reset")
        self._reset_requested = True

    def acknowledge(self) -> None:
        """Acks every currently latched alarm (a real annunciator panel's
        "ack all" button) -- deliberately independent of line state and
        of reset(): acknowledging an alarm means an operator has seen it,
        not that whatever tripped it is fixed. See
        docs/CONTROL-LAB.md §10's Phase 4 entry for why these stay two
        separate operator actions."""
        self._emit_command("acknowledge")
        self._acknowledge_requested = True

    def select_source(self, bin_: str) -> None:
        """The HMI's source-bin setpoint. It applies at the next start (a
        running line keeps drawing from its active bin) and is recorded like
        a command, since changing it changes what the next start does."""
        if bin_ not in self.gates:
            raise ValueError(f"no bin {bin_!r} on this line (bins: {', '.join(self.gates)})")
        if bin_ != self.source_bin:
            self._emit_command(f"source_bin {bin_}")
        self.source_bin = bin_

    def set_recipe(self, bin_: str, kg: float) -> None:
        """A recipe setpoint: kg to load from that bin. Takes effect at the
        next batch start; recorded like a command."""
        if bin_ not in BINS or kg < 0:
            raise ValueError(f"recipe: bin must be one of {', '.join(BINS)} and kg >= 0, got {bin_!r} {kg!r}")
        if float(kg) != self.recipe[bin_]:
            self._emit_command(f"recipe {bin_} {kg:g} kg")
        self.recipe[bin_] = float(kg)

    def set_hold(self, seconds: float) -> None:
        """The batch's hold (PROCESSING) time setpoint."""
        if seconds < 0:
            raise ValueError(f"hold must be >= 0 s, got {seconds!r}")
        if float(seconds) != self.hold_s:
            self._emit_command(f"hold {seconds:g} s")
        self.hold_s = float(seconds)

    def select_batch(self) -> None:
        self._emit_command("select_batch")
        self._mode_request = LineMode.BATCH

    def open_outlet(self) -> None:
        self._device_command("open_outlet")

    def close_outlet(self) -> None:
        self._device_command("close_outlet")

    def select_auto(self) -> None:
        self._emit_command("select_auto")
        self._mode_request = LineMode.AUTO

    def select_manual(self) -> None:
        self._emit_command("select_manual")
        self._mode_request = LineMode.MANUAL

    def start_conveyor(self) -> None:
        self._device_command("start_conveyor")

    def stop_conveyor(self) -> None:
        self._device_command("stop_conveyor")

    def open_gate(self) -> None:
        self._device_command("open_gate")

    def close_gate(self) -> None:
        self._device_command("close_gate")

    def start_feeder(self) -> None:
        self._device_command("start_feeder")

    def stop_feeder(self) -> None:
        self._device_command("stop_feeder")

    def _device_command(self, command: str) -> None:
        self._emit_command(command)
        self._device_requests.add(command)

    def _emit_command(self, command: str) -> None:
        if self.command_sink is not None:
            self.command_sink(command)

    # ---- the scan cycle -------------------------------------------------

    def scan(self, dt: float) -> None:
        """Call once per tick. Scans the three device-control modules
        first (so their own supervision timing runs exactly once per
        tick, same as everything else), then the alarm set (so it reads
        this tick's fresh fault flags, not last tick's), then this state
        machine."""
        self.feeder_ctrl.scan(dt)
        self.conveyor_ctrl.scan(dt)
        for gate in self.gates.values():
            gate.scan(dt)
        if self.outlet_ctrl is not None:
            self.outlet_ctrl.scan(dt)
        self.interlocks.scan(dt)
        self.level_checks.scan(self.interlocks, dt)
        self.alarms.scan()

        if self._acknowledge_requested:
            self.alarms.acknowledge()

        if not self.interlocks.estop_healthy and self.state != LineState.ESTOPPED:
            self._enter_estopped()

        if self._mode_request is not None:
            self._change_mode(self._mode_request)
        if self.state != LineState.MANUAL:
            self._refuse_device_starts()

        if self.state == LineState.IDLE:
            self._scan_idle()
        elif self.state == LineState.STARTING:
            self._scan_starting(dt)
        elif self.state == LineState.RUNNING:
            self._scan_running()
        elif self.state == LineState.STOPPING:
            self._scan_stopping(dt)
        elif self.state == LineState.FAULTED:
            self._scan_faulted(dt)
        elif self.state == LineState.ESTOPPED:
            self._scan_estopped()
        elif self.state == LineState.MANUAL:
            self._scan_manual(dt)
        elif self.state == LineState.LOADING:
            self._scan_loading(dt)
        elif self.state == LineState.PROCESSING:
            self._scan_processing(dt)
        elif self.state == LineState.DISCHARGING:
            self._scan_discharging(dt)
        elif self.state == LineState.CLEANING:
            self._scan_cleaning(dt)

        self._start_requested = False
        self._stop_requested = False
        self._reset_requested = False
        self._acknowledge_requested = False
        self._mode_request = None
        self._device_requests.clear()

    # ---- mode -----------------------------------------------------------

    def _change_mode(self, mode: LineMode) -> None:
        """docs/CONTROL-LAB.md §6.1: the mode changes only at rest. A refusal
        is reported like a refused start (StartInhibit.LINE_NOT_IDLE), so a
        scenario can tell a refused mode change from one never requested."""
        if mode == self.mode:
            self.start_inhibit = StartInhibit.NONE
            self.last_start_refusal = []
            return
        if mode == LineMode.BATCH and self.outlet_ctrl is None:
            raise ValueError("this line has no hopper outlet gate, so no Batch mode")
        if self.state == LineState.IDLE or (self.state == LineState.MANUAL and not self._any_device_commanded()):
            self.mode = mode
            self._enter_rest()
            self.start_inhibit = StartInhibit.NONE
            self.last_start_refusal = []
            return
        why = "stop every device first" if self.state == LineState.MANUAL else f"the line is {self.state.name.lower()}"
        self.start_inhibit = StartInhibit.LINE_NOT_IDLE
        self.last_start_refusal = [f"mode change to {mode.name.lower()} refused: {why}"]

    def _any_device_commanded(self) -> bool:
        return (self.feeder_ctrl.commanded_run or self.conveyor_ctrl.commanded_run
                or any(g.commanded_open for g in self.gates.values())
                or (self.outlet_ctrl is not None and self.outlet_ctrl.commanded_open))

    def _enter_rest(self) -> None:
        """The mode's rest state -- IDLE in Auto, MANUAL in Manual -- with
        nothing running: every state that enforces outputs off hands over
        with them already off, and MANUAL only runs what is started anew."""
        self.state = LineState.MANUAL if self.mode == LineMode.MANUAL else LineState.IDLE
        self.fault_reason = None
        self.active_bin = None
        self.batch_step = None
        self._manual_conveyor_proven = False
        self._manual_conveyor_elapsed_s = 0.0

    def _refuse_device_starts(self) -> None:
        """A device start outside MANUAL is refused and reported -- in Auto,
        the master spec's "operator manual override during automatic"; in
        Manual mode, the line is FAULTED or ESTOPPED. Device stops outside
        MANUAL are no-ops, like stop() while IDLE."""
        if not self._device_requests & DEVICE_STARTS:
            return
        if self.mode != LineMode.MANUAL:  # Auto or Batch (it read "== AUTO", so Batch said "faulted")
            self.start_inhibit = StartInhibit.WRONG_MODE
            self.last_start_refusal = ["device commands need Manual mode"]
        elif self.state == LineState.ESTOPPED:
            self.start_inhibit = StartInhibit.ESTOP_ACTIVE
            self.last_start_refusal = ["e-stop active"]
        else:
            self.start_inhibit = StartInhibit.LINE_FAULTED
            self.last_start_refusal = [f"line faulted: {self.fault_reason}"]

    # ---- IDLE -----------------------------------------------------------

    def _scan_idle(self) -> None:
        # Continuously enforced, not just assumed -- IDLE means off.
        self.feeder_ctrl.command_run(False)
        self.conveyor_ctrl.command_run(False)
        self._close_gates()
        self._close_outlet()

        if not self._start_requested:
            return
        if self.mode == LineMode.BATCH:
            self._request_batch()
            return

        check = self.interlocks.start_permissives_ok(self.source_bin)
        reasons = list(check.reasons)
        # "No active latched alarms" (docs/CONTROL-LAB.md §6.3) lives here,
        # not inside Interlocks.start_permissives_ok() -- AlarmManager is
        # built ON TOP of Interlocks (services/control/alarms.py), so
        # Interlocks checking AlarmManager back would be circular.
        # LineController is where the two are already combined for every
        # other decision, so it's the natural place for this one too.
        unacked_trips = self._unacked_trip_ids()
        if unacked_trips:
            reasons.append(f"unacknowledged alarm: {', '.join(unacked_trips)}")
        open_gates = self._gates_not_closed()
        if open_gates:
            reasons.append(f"gate not closed: {', '.join(open_gates)}")
        self.last_start_refusal = reasons
        inhibit = StartInhibit.NONE
        if self.interlocks.hopper_high_high:  # the same reads start_permissives_ok() just made
            inhibit |= StartInhibit.HOPPER_HIGH_HIGH
        if self.interlocks.bin_low_of(self.source_bin):
            inhibit |= StartInhibit.BIN_LOW
        if self.interlocks.hopper_weight_failed:
            inhibit |= StartInhibit.SENSOR_FAILED
        if unacked_trips:
            inhibit |= StartInhibit.UNACKNOWLEDGED_ALARM
        if open_gates:
            inhibit |= StartInhibit.GATE_NOT_CLOSED
        self.start_inhibit = inhibit
        if not reasons:
            self._begin_start_sequence()

    def _close_gates(self, outlet: bool = True) -> None:
        """Every bin gate -- and the hopper outlet, unless `outlet` is False
        (Manual's close-gate pushbutton acts on the bin gates only)."""
        for gate in self.gates.values():
            gate.command_open(False)
        if outlet:
            self._close_outlet()

    def _gates_not_closed(self) -> list[str]:
        """A start permissive: every bin gate and the hopper outlet proven
        closed at its closed limit switch. A gate stuck open while IDLE
        otherwise let a start through that then tripped on the wrong words
        ("gate failed to prove open"), or fed from two bins at once (found
        in the 2026-09-23 logic review)."""
        gates = list(self.gates.values())
        if self.outlet_ctrl is not None:
            gates.append(self.outlet_ctrl)
        return [g.command_tag.split(".")[0] for g in gates if not g.is_closed]

    def _close_outlet(self) -> None:
        if self.outlet_ctrl is not None:
            self.outlet_ctrl.command_open(False)

    def _enable_discharge(self, wanted: bool) -> None:
        """The outlet as an interlocked discharge-enablement device: open
        only when `wanted` and the downstream consumer is ready."""
        if self.outlet_ctrl is not None:
            self.outlet_ctrl.command_open(wanted and self.interlocks.downstream_ready)

    @property
    def _active_gate(self) -> GateControl:
        return self.gates[self.active_bin or self.source_bin]

    @property
    def _gate_travel_fault(self) -> bool:
        """Any gate that didn't reach its commanded position -- including a
        gate that should be closed and isn't, pouring from the wrong bin."""
        return any(g.travel_fault for g in self.gates.values())

    def _unacked_trip_ids(self) -> list[str]:
        return [a.id for a in self.alarms.all_alarms if not a.is_warning and not a.acknowledged]

    def _begin_start_sequence(self) -> None:
        self.active_bin = self.source_bin
        self.state = LineState.STARTING
        self.start_step = StartStep.CONVEYOR
        self._step_elapsed_s = 0.0
        self.hysteresis.rearm()
        self.conveyor_ctrl.command_run(True)

    # ---- STARTING ---------------------------------------------------------

    def _scan_starting(self, dt: float) -> None:
        reason = self._starting_trip_reason()
        if reason is not None:
            self._enter_faulted(reason)
            return

        if self._stop_requested:
            # A real operator pressing Stop mid-startup expects the
            # sequence to abort, not to be silently ignored.
            # _begin_stop_sequence() is safe to call from any start step:
            # it unconditionally drops feeder/gate (a no-op if they were
            # never started yet) and purges with the conveyor, which is
            # either already running or about to be commanded to stop
            # from wherever it currently is.
            self._begin_stop_sequence()
            return

        if self.start_step == StartStep.CONVEYOR:
            self._step_elapsed_s = round(self._step_elapsed_s + dt, 9)
            if self.interlocks.conveyor_confirmed_running:
                self.start_step = StartStep.GATE
                self._step_elapsed_s = 0.0
                self._active_gate.command_open(True)
            elif self._step_elapsed_s >= self.conveyor_proof_timeout_s:
                self._enter_faulted("conveyor failed to prove running")

        elif self.start_step == StartStep.GATE:
            if self._active_gate.is_open:
                # Level control decides the first feed too: a hopper already
                # at LSH-105 starts the line with the feed held, and RUNNING
                # starts the feeder once the level falls below the restart
                # point (a drive that won't start then trips, as mid-run).
                if self.hysteresis.evaluate(self.interlocks.hopper_high, self.interlocks.hopper_level_pct):
                    self.start_step = StartStep.FEEDER
                    self._step_elapsed_s = 0.0
                    self.feeder_ctrl.command_run(True)
                    self.feeder_ctrl.command_speed(self.feed_speed_pct)
                else:
                    self._enter_running()
            # The active gate's travel_fault (checked above, via
            # _starting_trip_reason) is what catches "never opened" --
            # its own 5s window is already running via its scan(),
            # called once per tick from this class's own scan().

        elif self.start_step == StartStep.FEEDER:
            if self.feeder_ctrl.running:
                self._enter_running()
            # feeder_ctrl.start_proof_fault (checked above) is what
            # catches "never confirmed running."

    def _starting_trip_reason(self) -> str | None:
        if self.interlocks.hopper_high_high:
            return "hopper high-high"
        if self.conveyor_ctrl.faulted:
            return "conveyor trip"
        if self.interlocks.conveyor_overcurrent:
            return "conveyor jam"
        if self.feeder_ctrl.faulted:
            return "feeder trip"
        if self.interlocks.feeder_plugged:
            return "feeder jam"
        if self.interlocks.hopper_weight_failed:
            return "hopper weight signal failed"
        if self.conveyor_ctrl.start_proof_fault:
            return "conveyor failed to prove running"
        if self.feeder_ctrl.start_proof_fault:
            return "feeder failed to prove running"
        if self._gate_travel_fault:
            return "gate failed to prove open"
        if self.outlet_ctrl is not None and self.outlet_ctrl.travel_fault:
            return "outlet travel fault"
        return None

    def _enter_running(self) -> None:
        self.state = LineState.RUNNING
        self.start_step = None

    # ---- RUNNING ----------------------------------------------------------

    def _scan_running(self) -> None:
        reason = self._running_trip_reason()
        if reason is not None:
            self._enter_faulted(reason)
            return

        if self._stop_requested:
            self._begin_stop_sequence()
            return

        # The only thing that modulates during normal RUNNING
        # (docs/CONTROL-LAB.md §6.2): the conveyor and gate stay as they
        # are: the feeder cycles on and off with hopper level.
        want_feed = self.hysteresis.evaluate(self.interlocks.hopper_high, self.interlocks.hopper_level_pct)
        if want_feed:
            self.feeder_ctrl.command_run(True)
            self.feeder_ctrl.command_speed(self.feed_speed_pct)
        else:
            self.feeder_ctrl.command_run(False)

        # The hopper is a buffer between the upstream feed and the downstream
        # consumer (DS-107): the outlet is enabled while the line runs and the
        # consumer is ready, and closes in the same scan when it isn't -- a
        # normal hand-off, not a trip. Level plays no part in it: the feed's
        # 60 %/80 % hysteresis above keeps the buffer topped up behind the
        # draw. (Stop, every trip and E-stop close it with the other gates.)
        self._enable_discharge(True)

        # bin_low is a WARNING while running, not a trip
        # (docs/CONTROL-LAB.md §6.3) -- there's nothing to actively DO
        # with it yet (no alarm/notification system exists before Phase
        # 4/5). self.interlocks.bin_low is already queryable by anything
        # that wants it; deliberately not acted on here.

    def _running_trip_reason(self) -> str | None:
        if self.interlocks.hopper_high_high:
            return "hopper high-high"
        if self.feeder_ctrl.faulted:
            return "feeder trip"
        if self.interlocks.feeder_plugged:
            # The drive still reports RUNNING through a jam (current limit),
            # so feeder_ctrl.faulted never sees it -- only the plug switch does.
            return "feeder jam"
        if self.feeder_ctrl.start_proof_fault:
            # Level control restarts the feeder mid-run; if the drive never
            # runs, that's a fail-to-start (§6.3), not just an alarm -- the
            # line must not sit in RUNNING while the hopper empties.
            return "feeder failed to prove running"
        if self.interlocks.hopper_weight_failed:
            # The feed/no-feed decision below reads WT-105; with its signal
            # gone that decision can't be made. Unknown means stopped (§8).
            # STOPPING doesn't trip on it: the stop sequence never reads WT-105.
            return "hopper weight signal failed"
        if self.conveyor_ctrl.faulted:
            return "conveyor trip"
        if self.interlocks.conveyor_overcurrent:
            return "conveyor jam"
        if not self.interlocks.conveyor_confirmed_running:
            return self._motion_loss_reason()
        if self._gate_travel_fault:
            return "gate travel fault"
        if self.outlet_ctrl is not None and self.outlet_ctrl.travel_fault:
            return "outlet travel fault"
        return None

    def _motion_loss_reason(self) -> str:
        """The belt stopped under a running motor: the motor current says
        why. High current -- it's pushing against a jam; normal or low -- the
        belt is slipping or broken."""
        return "conveyor jam" if self.interlocks.conveyor_current_high else "conveyor lost confirmation"

    # ---- STOPPING (upstream first) -----------------------------------

    def _begin_stop_sequence(self) -> None:
        self.state = LineState.STOPPING
        self.feeder_ctrl.command_run(False)
        self._close_gates()
        self._purge_elapsed_s = 0.0
        self._stop_belt_proven = self.interlocks.conveyor_confirmed_running

    def _scan_stopping(self, dt: float) -> None:
        if self.interlocks.conveyor_confirmed_running:
            self._stop_belt_proven = True
        reason = self._stopping_trip_reason()
        if reason is not None:
            self._enter_faulted(reason)
            return

        # Conveyor keeps running through the purge so the belt clears
        # (docs/CONTROL-LAB.md §6.2) -- feeder and gate are already
        # commanded off from _begin_stop_sequence(), so nothing new is
        # being fed onto it regardless of gate position.
        self._purge_elapsed_s = round(self._purge_elapsed_s + dt, 9)
        if self._purge_elapsed_s >= self.purge_time_s:
            self.conveyor_ctrl.command_run(False)
            self.state = LineState.IDLE
            self.active_bin = None
            self._purge_elapsed_s = 0.0

    def _stopping_trip_reason(self) -> str | None:
        if self.interlocks.hopper_high_high:
            return "hopper high-high"
        if self.conveyor_ctrl.faulted:
            return "conveyor trip"
        if self.interlocks.conveyor_overcurrent:
            return "conveyor jam"
        if self.conveyor_ctrl.commanded_run:
            # The purge only clears the belt if the belt moves: a slip during
            # it would otherwise count down and leave the line IDLE with
            # material stranded on the belt (found in the 2026-09-23 logic
            # review). A belt still proving after a Stop mid-startup that
            # never proves is the start sequence's own fail-to-start.
            if self.conveyor_ctrl.start_proof_fault:
                return "conveyor failed to prove running"
            if self._stop_belt_proven and not self.interlocks.conveyor_confirmed_running:
                return self._motion_loss_reason()
        if self.feeder_ctrl.faulted:
            return "feeder trip"
        if self.interlocks.feeder_plugged:
            return "feeder jam"
        if self._gate_travel_fault:
            return "gate travel fault"
        if self.outlet_ctrl is not None and self.outlet_ctrl.travel_fault:
            return "outlet travel fault"
        return None

    # ---- FAULTED ------------------------------------------------------

    def _enter_faulted(self, reason: str) -> None:
        self.clearing_belt = reason in CLEAR_BELT_ON and self.conveyor_ctrl.commanded_run
        self._purge_elapsed_s = 0.0
        self.feeder_ctrl.command_run(False)
        self.conveyor_ctrl.command_run(self.clearing_belt)
        self._close_gates()
        self.state = LineState.FAULTED
        self.fault_reason = reason
        self.start_step = None

    def _scan_faulted(self, dt: float) -> None:
        self.feeder_ctrl.command_run(False)
        self._close_gates()
        if self.clearing_belt:
            # The same purge as a normal stop, cut short by anything that makes
            # running the belt on wrong: the conveyor itself failing or losing
            # motion, the hopper at high-high, or its level unknown.
            self._purge_elapsed_s = round(self._purge_elapsed_s + dt, 9)
            if (self._purge_elapsed_s >= self.purge_time_s
                    or self.conveyor_ctrl.faulted
                    or self.interlocks.conveyor_overcurrent
                    or not self.interlocks.conveyor_confirmed_running
                    or self.interlocks.hopper_high_high
                    or self.interlocks.hopper_weight_failed):
                self.clearing_belt = False
        self.conveyor_ctrl.command_run(self.clearing_belt)
        if self._start_requested:
            # Refused exactly as before (FAULTED never acts on start); only
            # the reporting is new.
            self.start_inhibit = StartInhibit.LINE_FAULTED

        if not self._reset_requested:
            return
        if self._fault_cause_cleared():
            self._clear_all_device_faults()
            self.clearing_belt = False  # rest means off; a reset ends any belt clearing,
            self.conveyor_ctrl.command_run(False)  # in this same scan
            self._enter_rest()
        # else: refused, stays FAULTED, fault_reason unchanged

    def _fault_cause_cleared(self) -> bool:
        """Whether the underlying condition is still directly observable
        as active. Only covers PASS-THROUGH/level conditions Control can
        check independently (hopper high-high, a motor's own fault tag)
        -- NOT the latched timing diagnostics (start_proof_fault,
        travel_fault), which have no independent "still broken" signal to
        check: Control can only re-test them by trying again.
        clear_fault() on those happens unconditionally in
        _clear_all_device_faults() once this passes; if the underlying
        problem is still there, the next start attempt fails again on
        its own."""
        return self._standing_cause() is None

    def _standing_cause(self) -> str | None:
        """The trip cause still observably present, or None: what a reset
        from FAULTED -- and from ESTOPPED -- has to wait out. One list, so
        the two reset paths can't drift apart."""
        if self.interlocks.hopper_high_high:
            return "hopper high-high"
        if self.conveyor_ctrl.faulted:
            return "conveyor trip"
        if self.feeder_ctrl.faulted:
            return "feeder trip"
        if self.interlocks.feeder_plugged:  # the jam is still in the chute
            return "feeder jam"
        if self.interlocks.hopper_weight_failed:  # the signal hasn't been restored
            return "hopper weight signal failed"
        return None

    def _clear_all_device_faults(self) -> None:
        self.feeder_ctrl.clear_fault()
        self.conveyor_ctrl.clear_fault()
        for gate in self.gates.values():
            gate.clear_fault()
        if self.outlet_ctrl is not None:
            self.outlet_ctrl.clear_fault()
        self._discharge_timed_out = False

    # ---- ESTOPPED -------------------------------------------------------

    def _enter_estopped(self) -> None:
        self.clearing_belt = False
        self.feeder_ctrl.command_run(False)
        self.conveyor_ctrl.command_run(False)
        self._close_gates()
        self.state = LineState.ESTOPPED
        self.fault_reason = "e-stop"
        self.start_step = None

    def _scan_estopped(self) -> None:
        # Continuously enforced -- a stale command sitting in the I/O
        # image must never be allowed to restart anything the instant
        # the motor itself is reset (docs/CONTROL-LAB.md §10's Phase 2
        # entry flags exactly this gap from step 1's I/O-image-only
        # testing; this is what closes it).
        self.feeder_ctrl.command_run(False)
        self.conveyor_ctrl.command_run(False)
        self._close_gates()

        if self._start_requested:
            # Refused exactly as before (ESTOPPED never acts on start); only
            # the reporting is new.
            self.start_inhibit = StartInhibit.ESTOP_ACTIVE
        if self.interlocks.estop_healthy and self._reset_requested:
            self._clear_all_device_faults()
            # A reset out of ESTOPPED clears the E-stop, not whatever else is
            # still wrong: with a standing cause the line goes to FAULTED on
            # it, and needs its own reset once that's cleared. (It went
            # straight to IDLE, so an E-stop cycle got around "reset refused
            # while the chute is plugged" and a start was accepted onto a
            # known fault -- found in the 2026-09-23 logic review.)
            standing = self._standing_cause()
            if standing is not None:
                self.state = LineState.FAULTED
                self.fault_reason = standing
            else:
                self._enter_rest()
        # else: stays ESTOPPED -- either e-stop is still tripped, or no
        # reset yet. Both conditions are required
        # (docs/CONTROL-LAB.md §6.2's diagram).

    # ---- MANUAL -----------------------------------------------------------

    def _scan_manual(self, dt: float) -> None:
        self._supervise_manual_conveyor(dt)
        reason = self._manual_trip_reason()
        if reason is not None:
            self._enter_faulted(reason)
            return

        requests = set(self._device_requests)
        if self._stop_requested:
            # The line Stop works in every mode; in Manual it stops every device at once.
            requests |= DEVICE_STOPS
        if "stop_feeder" in requests:
            self.feeder_ctrl.command_run(False)
        if "close_gate" in requests:
            self._close_gates(outlet=False)
        if "close_outlet" in requests:
            self._close_outlet()
        if "stop_conveyor" in requests:
            self.conveyor_ctrl.command_run(False)
            self._manual_conveyor_proven = False
            self._manual_conveyor_elapsed_s = 0.0

        inhibit = StartInhibit.NONE
        reasons: list[str] = []
        evaluated = False
        if self._start_requested:
            evaluated = True
            inhibit |= StartInhibit.WRONG_MODE
            reasons.append("line Start is an Auto command; in Manual start each device")
        if "start_conveyor" in requests and "stop_conveyor" not in requests:
            evaluated = True
            refused, why = self._manual_conveyor_refusal()
            inhibit |= refused
            reasons += why
            if not refused and not self.conveyor_ctrl.commanded_run:
                self.conveyor_ctrl.command_run(True)
                self._manual_conveyor_proven = False
                self._manual_conveyor_elapsed_s = 0.0
        if "open_gate" in requests and "close_gate" not in requests:
            # No permissive beyond the E-stop (already diverted to ESTOPPED):
            # the gate alone moves no material, and stroking it to check its
            # limit switches is what Manual is for.
            evaluated = True
            # One bin at a time, in every mode: opening the selected bin's gate
            # closes any other.
            for letter, gate in self.gates.items():
                gate.command_open(letter == self.source_bin)
        if "open_outlet" in requests and "close_outlet" not in requests and self.outlet_ctrl is not None:
            # Draining the hopper by hand is a Manual-mode job (after an aborted
            # batch, say), but only into a downstream that can take it: the
            # discharge permissive holds in every mode.
            evaluated = True
            if self.interlocks.downstream_ready:
                self.outlet_ctrl.command_open(True)
            else:
                inhibit |= StartInhibit.DOWNSTREAM_NOT_READY
                reasons.append("downstream not ready")
        if "start_feeder" in requests and "stop_feeder" not in requests:
            evaluated = True
            refused, why = self._manual_feeder_refusal()
            inhibit |= refused
            reasons += why
            if not refused:
                self.feeder_ctrl.command_run(True)
                self.feeder_ctrl.command_speed(self.feed_speed_pct)
        if evaluated:
            self.start_inhibit = inhibit
            self.last_start_refusal = reasons

        # Enforced every scan, not only at start: the feeder runs only onto a
        # proven belt (an operator stopping the conveyor takes the feeder with
        # it, no trip -- an uncommanded loss is a trip, above), and stops at
        # the high switch.
        if not self._manual_feed_permitted():
            self.feeder_ctrl.command_run(False)
        # Likewise the outlet: it closes the scan the downstream stops being ready.
        if not self.interlocks.downstream_ready:
            self._close_outlet()

    def _manual_feed_permitted(self) -> bool:
        return self._manual_conveyor_proven and not self.interlocks.hopper_high

    def _supervise_manual_conveyor(self, dt: float) -> None:
        if not self.conveyor_ctrl.commanded_run:
            self._manual_conveyor_proven = False
            self._manual_conveyor_elapsed_s = 0.0
        elif self.interlocks.conveyor_confirmed_running:
            self._manual_conveyor_proven = True
        elif not self._manual_conveyor_proven:
            self._manual_conveyor_elapsed_s = round(self._manual_conveyor_elapsed_s + dt, 9)

    def _manual_trip_reason(self) -> str | None:
        """Auto's RUNNING trips, applied while the feeder or conveyor is
        running; with both off, MANUAL is at rest and a condition such as
        high-high only refuses starts, as it does in IDLE. The gate's travel
        fault trips at any time: in Manual it is the result of a stroke."""
        feeding = self.feeder_ctrl.commanded_run
        conveying = self.conveyor_ctrl.commanded_run
        if feeding or conveying:
            if self.interlocks.hopper_high_high:
                return "hopper high-high"
            if self.conveyor_ctrl.faulted:
                return "conveyor trip"
            if self.interlocks.conveyor_overcurrent:
                return "conveyor jam"
            if self.feeder_ctrl.faulted:
                return "feeder trip"
            if self.interlocks.feeder_plugged:
                return "feeder jam"
            if self.interlocks.hopper_weight_failed:
                return "hopper weight signal failed"
        if conveying:
            if self.conveyor_ctrl.start_proof_fault or (
                not self._manual_conveyor_proven and self._manual_conveyor_elapsed_s >= self.conveyor_proof_timeout_s
            ):
                return "conveyor failed to prove running"
            if self._manual_conveyor_proven and not self.interlocks.conveyor_confirmed_running:
                return self._motion_loss_reason()
        if feeding and self.feeder_ctrl.start_proof_fault:
            return "feeder failed to prove running"
        if self._gate_travel_fault:
            return "gate travel fault"
        if self.outlet_ctrl is not None and self.outlet_ctrl.travel_fault:
            return "outlet travel fault"
        return None

    def _manual_conveyor_refusal(self) -> tuple[StartInhibit, list[str]]:
        inhibit, reasons = StartInhibit.NONE, []
        if self.interlocks.hopper_high_high:
            inhibit |= StartInhibit.HOPPER_HIGH_HIGH
            reasons.append("hopper at high-high")
        if self.interlocks.hopper_weight_failed:
            inhibit |= StartInhibit.SENSOR_FAILED
            reasons.append("hopper weight signal failed")
        inhibit, reasons = self._unacked_refusal(inhibit, reasons)
        return inhibit, reasons

    def _manual_feeder_refusal(self) -> tuple[StartInhibit, list[str]]:
        inhibit, reasons = StartInhibit.NONE, []
        if not self._manual_conveyor_proven:
            inhibit |= StartInhibit.CONVEYOR_NOT_RUNNING
            reasons.append("conveyor not proven running")
        drawn = [b for b, g in self.gates.items() if g.commanded_open] or [self.source_bin]
        if any(self.interlocks.bin_low_of(b) for b in drawn):
            inhibit |= StartInhibit.BIN_LOW
            reasons.append("bin low")
        if self.interlocks.hopper_high:
            inhibit |= StartInhibit.HOPPER_HIGH
            reasons.append("hopper at the high switch")
        if self.interlocks.hopper_high_high:
            inhibit |= StartInhibit.HOPPER_HIGH_HIGH
            reasons.append("hopper at high-high")
        if self.interlocks.hopper_weight_failed:
            inhibit |= StartInhibit.SENSOR_FAILED
            reasons.append("hopper weight signal failed")
        inhibit, reasons = self._unacked_refusal(inhibit, reasons)
        return inhibit, reasons

    def _unacked_refusal(self, inhibit: StartInhibit, reasons: list[str]) -> tuple[StartInhibit, list[str]]:
        unacked = self._unacked_trip_ids()
        if unacked:
            inhibit |= StartInhibit.UNACKNOWLEDGED_ALARM
            reasons = reasons + [f"unacknowledged alarm: {', '.join(unacked)}"]
        return inhibit, reasons

    # ---- BATCH (master specification, item 7) ------------------------------------------

    @property
    def batch_target_kg(self) -> float:
        return sum(kg for _, kg in self._batch_plan)

    def _request_batch(self) -> None:
        """A start in Batch mode: the batch permissives, then LOADING."""
        plan = [(b, self.recipe[b]) for b in BINS if b in self.gates and self.recipe[b] > 0]
        weight = self.interlocks.io.read("WT-105")
        room = self.interlocks.hopper_capacity_kg * self.level_checks.lsh.switch_pct / 100.0
        inhibit, reasons = StartInhibit.NONE, []
        if not plan:
            inhibit |= StartInhibit.RECIPE_EMPTY
            reasons.append("recipe is empty")
        elif sum(kg for _, kg in plan) > room:
            inhibit |= StartInhibit.RECIPE_TOO_LARGE
            reasons.append(f"recipe is more than fits under the high switch ({room:g} kg)")
        if weight > self.batch_empty_kg:
            inhibit |= StartInhibit.HOPPER_NOT_EMPTY
            reasons.append("hopper not empty")
        if any(self.interlocks.bin_low_of(b) for b, _ in plan):
            inhibit |= StartInhibit.BIN_LOW
            reasons.append("bin low")
        if self.interlocks.hopper_high_high:
            inhibit |= StartInhibit.HOPPER_HIGH_HIGH
            reasons.append("hopper at high-high")
        if self.interlocks.hopper_weight_failed:
            inhibit |= StartInhibit.SENSOR_FAILED
            reasons.append("hopper weight signal failed")
        open_gates = self._gates_not_closed()
        if open_gates:
            inhibit |= StartInhibit.GATE_NOT_CLOSED
            reasons.append(f"gate not closed: {', '.join(open_gates)}")
        inhibit, reasons = self._unacked_refusal(inhibit, reasons)
        self.start_inhibit = inhibit
        self.last_start_refusal = reasons
        if inhibit:
            return
        self._batch_plan = plan
        self._batch_index = 0
        self._batch_start_kg = weight
        self.batch_loaded_kg = 0.0
        self._batch_out_of_tolerance = False
        self._batch_conveyor_proven = False
        self._batch_elapsed_s = 0.0
        self.active_bin = plan[0][0]
        self.state = LineState.LOADING
        self.batch_step = BatchStep.CONVEYOR
        self.conveyor_ctrl.command_run(True)

    def _batch_trip_reason(self) -> str | None:
        """The trips of a running line, applied to whatever the batch has
        running, plus the outlet gate's travel fault."""
        feeding = self.feeder_ctrl.commanded_run
        conveying = self.conveyor_ctrl.commanded_run
        if self.interlocks.hopper_high_high:
            return "hopper high-high"
        if conveying and self.conveyor_ctrl.faulted:
            return "conveyor trip"
        if conveying and self.interlocks.conveyor_overcurrent:
            return "conveyor jam"
        if feeding and self.feeder_ctrl.faulted:
            return "feeder trip"
        if self.interlocks.feeder_plugged:
            return "feeder jam"
        if feeding and self.feeder_ctrl.start_proof_fault:
            return "feeder failed to prove running"
        if self.interlocks.hopper_weight_failed:
            return "hopper weight signal failed"  # a batch is weighed: unknown weight, no batch
        if conveying and self.conveyor_ctrl.start_proof_fault:
            return "conveyor failed to prove running"
        if conveying and self._batch_conveyor_proven and not self.interlocks.conveyor_confirmed_running:
            return self._motion_loss_reason()
        if self.state == LineState.LOADING and self.batch_step == BatchStep.FEED and self.interlocks.no_flow:
            # A dose that stops flowing (a bin bridging mid-load) would leave the
            # batch waiting forever for its weight: in a batch, no flow is a trip.
            return "batch feed stalled"
        if self._gate_travel_fault:
            proving = self.state == LineState.LOADING and self.batch_step == BatchStep.GATE
            return "gate failed to prove open" if proving else "gate travel fault"
        if self.outlet_ctrl is not None and self.outlet_ctrl.travel_fault:
            return "outlet travel fault"
        return None

    def _batch_prove_conveyor(self, dt: float) -> bool | None:
        """True once the belt has proven running, None while it's still
        within its proof window, False once the window has passed."""
        if self.interlocks.conveyor_confirmed_running:
            self._batch_conveyor_proven = True
        if self._batch_conveyor_proven:
            return True
        self._batch_elapsed_s = round(self._batch_elapsed_s + dt, 9)
        return None if self._batch_elapsed_s < self.conveyor_proof_timeout_s else False

    def _batch_common(self) -> bool:
        """Trips, then Stop (which aborts the batch). True if either acted."""
        reason = self._batch_trip_reason()
        if reason is not None:
            self._enter_faulted(reason)
            return True
        if self._stop_requested:
            self._begin_stop_sequence()
            return True
        return False

    def _scan_loading(self, dt: float) -> None:
        if self._batch_common():
            return
        weight = self.interlocks.io.read("WT-105")
        self.batch_loaded_kg = max(0.0, weight - self._batch_start_kg)
        bin_, _ = self._batch_plan[self._batch_index]
        if self.batch_step == BatchStep.CONVEYOR:
            proven = self._batch_prove_conveyor(dt)
            if proven is False:
                self._enter_faulted("conveyor failed to prove running")
            elif proven:
                self.batch_step = BatchStep.GATE
                self.gates[bin_].command_open(True)
        elif self.batch_step == BatchStep.GATE:
            if self.gates[bin_].is_open:
                self.batch_step = BatchStep.FEED
                self.feeder_ctrl.command_run(True)
                self.feeder_ctrl.command_speed(self.feed_speed_pct)
        elif self.batch_step == BatchStep.FEED:
            # Stop feeding when what's on the belt will make up the rest.
            target = self._batch_start_kg + sum(kg for _, kg in self._batch_plan[: self._batch_index + 1])
            if weight + self.batch_preact_kg >= target:
                self.feeder_ctrl.command_run(False)
                self._close_gates(outlet=False)
                self.batch_step = BatchStep.SETTLE
                self._batch_elapsed_s = 0.0
        elif self.batch_step == BatchStep.SETTLE:
            self._batch_elapsed_s = round(self._batch_elapsed_s + dt, 9)
            if self._batch_elapsed_s >= self.purge_time_s:
                self._batch_index += 1
                if self._batch_index < len(self._batch_plan):
                    self.active_bin = self._batch_plan[self._batch_index][0]
                    self.batch_step = BatchStep.GATE
                    self.gates[self.active_bin].command_open(True)
                else:
                    self._batch_out_of_tolerance = (
                        abs(self.batch_loaded_kg - self.batch_target_kg) > self.batch_tolerance_kg
                    )
                    self.conveyor_ctrl.command_run(False)
                    self._batch_conveyor_proven = False
                    self.active_bin = None
                    self.batch_step = None
                    self.state = LineState.PROCESSING
                    self._batch_elapsed_s = 0.0

    def _scan_processing(self, dt: float) -> None:
        if self._batch_common():
            return
        self._batch_elapsed_s = round(self._batch_elapsed_s + dt, 9)
        if self._batch_elapsed_s >= self.hold_s:
            self.state = LineState.DISCHARGING
            self._batch_elapsed_s = 0.0
            self._enable_discharge(True)

    def _scan_discharging(self, dt: float) -> None:
        if self._batch_common():
            return
        # Discharge waits for the downstream: the outlet is enabled only while
        # it's ready, and the timeout counts only while it is, so it still
        # means "the hopper won't empty", never "the downstream isn't taking".
        self._enable_discharge(True)
        if self.interlocks.downstream_ready:
            self._batch_elapsed_s = round(self._batch_elapsed_s + dt, 9)
        if self.outlet_ctrl.is_open and self.interlocks.io.read("WT-105") <= self.batch_empty_kg:
            # Empty: clean the belt out while the outlet drains the rest.
            self.state = LineState.CLEANING
            self._batch_elapsed_s = 0.0
            self._batch_conveyor_proven = False
            self.conveyor_ctrl.command_run(True)
        elif self._batch_elapsed_s >= self.discharge_timeout_s:
            self._discharge_timed_out = True
            self._enter_faulted("discharge timeout")

    def _scan_cleaning(self, dt: float) -> None:
        if self._batch_common():
            return
        if self.conveyor_ctrl.commanded_run:
            self._enable_discharge(True)  # the outlet drains the rest, while the downstream takes it
            proven_before = self._batch_conveyor_proven
            proven = self._batch_prove_conveyor(dt)
            if proven is False:
                self._enter_faulted("conveyor failed to prove running")
                return
            if proven:
                if not proven_before:
                    self._batch_elapsed_s = 0.0
                self._batch_elapsed_s = round(self._batch_elapsed_s + dt, 9)
                if self._batch_elapsed_s >= self.purge_time_s:
                    self.conveyor_ctrl.command_run(False)
                    self._batch_conveyor_proven = False
                    self.outlet_ctrl.command_open(False)
        elif self.outlet_ctrl.is_closed:
            self.batches_completed += 1
            self._enter_rest()
