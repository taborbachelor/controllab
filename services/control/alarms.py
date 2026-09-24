"""Alarm latching, first-out, and acknowledge (docs/CONTROL-LAB.md §6.3 --
closes "No active latched alarms," and gives the warning half of "Bin not
low" something real to do).

Built the same way Interlocks (services/control/interlocks.py) was: a
Control-layer object with no opinion on what LineController does about a
trip -- deciding to fault the line stays LineController's job (Phase 4
step 2). What this owns is purely bookkeeping: which conditions are
currently outstanding, and which one happened first.

Unlike Interlocks, an alarm needs real memory across scans -- it has to
stay latched after its condition clears, which a stateless computed
property can't do. So this is a small generic engine (register/scan/
acknowledge) rather than nine hand-written property pairs: the
rising-edge/first-out/latch bookkeeping is identical for every alarm, and
writing it out nine times the way Interlocks' stateless booleans are
written would be duplication, not this project's "concrete before
generic" default (docs/CONTROL-LAB.md §8). The *set* of nine alarms below
is still hardcoded for this exact line, the same way Interlocks and
plant_io.py are -- nothing here is a pluggable alarm-definition format.

Deliberately minimal two-state model per alarm (`active`, `acknowledged`)
with `latched` computed, not a third stored flag:

    latched = active or not acknowledged

i.e. an alarm shows latched while its condition is true, OR after the
condition has cleared but nobody has acknowledged it yet. Acknowledging
it while still active clears the "unacknowledged" half, but `active`
alone keeps it latched -- exactly like a real annunciator panel's lamp
going from flashing to steady, not off. Once the condition then clears,
it goes out on its own on the very next scan -- no separate manual
"clear" action needed. Acknowledge always succeeds immediately, whether
or not the condition is still active: acknowledging means "an operator
has seen this," not "the problem is gone" -- a trip-class condition
that's still physically true keeps blocking a start through the *direct*
permissive that already checks it (e.g. Interlocks.hopper_high_high),
not through this alarm's own latch.

First-out: among alarms that go active on the very same scan, only the
first one (by the fixed process-order list below -- E-stop, then
upstream-to-downstream) claims first_out; on any other scan, whichever
alarm's rising edge is actually observed first naturally gets it, so the
tie-break only matters within one scan() call. The claim sticks -- even
once that alarm's own condition clears -- until the whole board is quiet
again (every alarm inactive and acknowledged), so the *cause* of a trip
cascade stays identifiable even after its symptoms have cleared.

Warnings (currently just bin low) latch and acknowledge exactly like
trip alarms -- the difference only matters to any_unacknowledged_trip(),
which Phase 4 step 2 wires into the "No active latched alarms" start
permissive: a warning never gates a start, since bin_low already has its
own direct permissive row and "warning only while running" was never
meant to become a hard block.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from services.control.errors import ControlError
from services.control.interlocks import Interlocks
from services.control.level_check import HopperLevelChecks

AlarmCondition = Callable[[], bool]


@dataclass
class Alarm:
    id: str
    description: str
    is_warning: bool = False

    active: bool = False
    acknowledged: bool = True  # nothing to acknowledge until it first trips
    first_out: bool = False

    @property
    def latched(self) -> bool:
        return self.active or not self.acknowledged


class AlarmManager:
    """The line's alarm set, scanned once a tick -- after Interlocks'
    underlying device-control modules have scanned this tick (the same
    ordering requirement MotorControl/GateControl/LineController already
    have), so every condition below reads this tick's fresh state, not
    last tick's stale one."""

    def __init__(self, interlocks: Interlocks, level_checks: HopperLevelChecks | None = None) -> None:
        """`level_checks`: the hopper switch cross-checks, scanned by whoever
        owns the scan cycle (LineController). A manager built without them
        gets an unscanned set whose two alarms never go active."""
        self._il = interlocks
        self._level = level_checks if level_checks is not None else HopperLevelChecks()
        self._entries: list[tuple[Alarm, AlarmCondition]] = []
        self._by_id: dict[str, Alarm] = {}
        self._first_out_holder: str | None = None

        self._register("ES-001.TRIP", "E-stop tripped", lambda: not self._il.estop_healthy)
        self._register("LSL-101.LOW", "Bin A low", lambda: self._il.bin_low, is_warning=True)
        self._register("XV-102.TRAVEL_FAULT", "Bin A gate travel fault", lambda: self._il.gate_ctrl.travel_fault)
        self._register("M-103.FAULT", "Feeder trip (VFD fault/overload)", lambda: self._il.feeder_ctrl.faulted)
        self._register(
            "M-103.START_PROOF",
            "Feeder failed to prove running",
            lambda: self._il.feeder_ctrl.start_proof_fault,
        )
        self._register("M-104.OL", "Conveyor trip (overload)", lambda: self._il.conveyor_ctrl.faulted)
        self._register(
            "ZSS-104.LOST",
            "Conveyor motion loss (belt slip)",
            lambda: self._il.conveyor_ctrl.running and not self._il.conveyor_motion_confirmed,
        )
        self._register(
            "M-104.START_PROOF",
            "Conveyor failed to prove running",
            lambda: self._il.conveyor_ctrl.start_proof_fault,
        )
        self._register("WT-105.HIGH_HIGH", "Hopper high-high", lambda: self._il.hopper_high_high)
        # Registered after the original nine, not in process order: the
        # published alarm bits (services/protocols/controller_status.py) are
        # append-only. Order only breaks same-scan first-out ties, and a plug
        # can't coincide with another trip's rising edge in practice: it takes
        # plug_detect_s of the feeder running jammed to make.
        self._register("LSH-103.JAM", "Feeder jam (discharge chute plugged)", lambda: self._il.feeder_plugged)
        self._register("WT-105.FAIL", "Hopper weight transmitter failed", lambda: self._il.hopper_weight_failed)
        # The level switch cross-checks (services/control/level_check.py),
        # appended for the same reason. LSH-105 is a control switch, so its
        # disagreement is a warning; LSHH-105's means the overfill
        # protection is down to one measurement, so it must be acknowledged
        # before a restart, like any trip-class alarm.
        self._register(
            "LSH-105.DISAGREE", "Hopper high switch disagrees with WT-105", lambda: self._level.lsh.disagree,
            is_warning=True,
        )
        self._register(
            "LSHH-105.DISAGREE",
            "Hopper high-high switch disagrees with WT-105",
            lambda: self._level.lshh.disagree,
        )
        # The motor current and the belt scale (master specification, item 5),
        # appended for the same reason.
        self._register("IT-104.HIGH", "Conveyor motor overcurrent (jam)", lambda: self._il.conveyor_overcurrent)
        self._register(
            "FT-104.NO_FLOW", "No flow on the belt while feeding", lambda: self._il.no_flow, is_warning=True,
        )
        # Bins B and C (master specification, item 6), appended; registered
        # whether or not the line has them, so the published bits never move.
        for letter, low, gate in (("B", "LSL-111", "XV-112"), ("C", "LSL-121", "XV-122")):
            self._register(f"{low}.LOW", f"Bin {letter} low", lambda b=letter: self._il.bin_low_of(b), is_warning=True)
            self._register(f"{gate}.TRAVEL_FAULT", f"Bin {letter} gate travel fault",
                           lambda b=letter: b in self._il.gates and self._il.gates[b].travel_fault)

    def _register(self, alarm_id: str, description: str, condition: AlarmCondition, is_warning: bool = False) -> None:
        alarm = Alarm(id=alarm_id, description=description, is_warning=is_warning)
        self._entries.append((alarm, condition))
        self._by_id[alarm_id] = alarm

    def get(self, alarm_id: str) -> Alarm:
        try:
            return self._by_id[alarm_id]
        except KeyError:
            raise ControlError(f"unknown alarm id: {alarm_id!r}") from None

    @property
    def all_alarms(self) -> list[Alarm]:
        """Every registered alarm, in fixed registration/priority order."""
        return [alarm for alarm, _ in self._entries]

    @property
    def latched_alarms(self) -> list[Alarm]:
        return [alarm for alarm in self.all_alarms if alarm.latched]

    @property
    def first_out(self) -> Alarm | None:
        return self._by_id[self._first_out_holder] if self._first_out_holder else None

    def any_unacknowledged_trip(self) -> bool:
        """What Phase 4 step 2 wires into the "No active latched alarms"
        start permissive -- trip-class only; see the warnings paragraph
        in the module docstring for why bin low is excluded."""
        return any(not alarm.acknowledged for alarm in self.all_alarms if not alarm.is_warning)

    def scan(self) -> None:
        for alarm, condition in self._entries:
            was_active = alarm.active
            alarm.active = bool(condition())
            rising_edge = alarm.active and not was_active
            if rising_edge:
                alarm.acknowledged = False
                if self._first_out_holder is None:
                    self._first_out_holder = alarm.id
                    alarm.first_out = True
            self._release_if_reset(alarm)

    def acknowledge(self, alarm_id: str | None = None) -> None:
        """Acknowledge one alarm, or -- with no id -- every registered
        alarm (a real annunciator panel's "ack all" pushbutton; a no-op
        for anything not currently latched)."""
        targets = [self.get(alarm_id)] if alarm_id is not None else self.all_alarms
        for alarm in targets:
            alarm.acknowledged = True
            self._release_if_reset(alarm)

    def _release_if_reset(self, alarm: Alarm) -> None:
        if not alarm.latched:
            alarm.first_out = False
            if self._first_out_holder == alarm.id:
                self._first_out_holder = None
