"""The discrete "JSONL event log" half of Phase 5 (docs/CONTROL-LAB.md
§3.4 and §10's Phase 5 entry): state transitions and the alarm lifecycle,
captured by diffing LineController/AlarmManager's existing public state
against the previous sample -- the confirmed Phase 5 architecture (pull,
not push).

Nothing in services/control/ knows this module exists. EventLog reads
LineController.state, LineController.fault_reason, and every Alarm in
LineController.alarms.all_alarms, exactly the same non-invasive
observation Testing already has (services/testing/vocabulary.py's
READ_FIELDS). sample(t) is called by an outside driver once per tick, the
same tick boundary services/testing/rig.py's tick() uses and
services/telemetry/tag_history.py's record(t) already follows -- t comes
from the caller (in practice, Plant.time_s, which every rig already
tracks), so this class stays as ignorant of simulated time as
TagHistory is.

Known, accepted limitation (the same one tag_history.py and the Phase 5
architecture decision both note): this only observes state AT tick
boundaries. A condition that begins and ends within a single tick is
invisible to it. Not solved here -- nothing in the current simulation
contract has demonstrated such a state is meaningful to capture.

Deliberately scoped to exactly two diffable primitives per alarm --
`active` and `acknowledged` -- not `latched`/`first_out`. `latched` is
itself only ever a function of those two (services/control/alarms.py:
`latched = active or not acknowledged`), so a transition in it always
coincides with a transition already being captured by one of the two
real events below; recording it a third time would be redundant, not
additional information. `first_out` only ever changes at the same
moment `active` does (on the rising edge that claims it) or the same
moment an alarm fully resets (already captured by whichever of
alarm_cleared/alarm_acknowledged closes it out) -- so it rides along as
a field on alarm_activated rather than needing its own event type.

`start()`/`stop()`/`reset()`/`acknowledge()` themselves -- "was a
command issued" -- can't be seen by diffing: a command can occur with
zero state change (stop() while already stopped). They arrive instead
through LineController's optional command sink (Phase 5 step 3, the one
push-style exception to this module's pull/diff design), wired
explicitly by the caller:

    event_log = EventLog(line)
    line.command_sink = event_log.record_command

record_command() only queues the name; the next sample(t) emits it as a
`command_issued` event stamped with that tick's t, BEFORE that tick's
state/alarm diffs. Two reasons. It keeps this class ignorant of
simulated time -- the sink fires between ticks, where no timestamp is
available without reaching for a clock. And the stamp is the honest
one: a command is a one-shot request that LineController.scan()
consumes on the next tick, so that tick is when it took effect, and
ordering it before the same tick's diffs keeps cause ahead of effect in
the log (command_issued "start" precedes state_changed idle->starting,
same t).

`command_refused` (2026-09-26) is derived, not pushed: the refusable
requests (REFUSABLE) are evaluated by the controller whenever they are
consumed, so after the tick that consumed one, the controller's published
`start_inhibit` is that request's outcome. Non-NONE means refused, and
the event records the request(s) with the inhibit's reason names, right
after the tick's command_issued events. Reading only `start_inhibit` is
what keeps it identical for the built-in controller and one reached over
Modbus (whose reason text never crosses the wire). Two refusable requests
in one tick share one event: the register is their combined outcome.

File output is a separate, standalone function (write_jsonl()), not a
method -- EventLog itself never imports json or pathlib. Mirrors
tag_history.py's write_csv() and services/testing/report.py /
scripts/scenario_report.py's pure-logic/file-writer split. Nothing
writes a file during a normal test run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from services.control.line_controller import DEVICE_START_ORDER, LineController
from services.control.line_state import StartInhibit, inhibit_names

# The requests the controller can refuse, by their command_issued names.
REFUSABLE = frozenset({"start", "reset", "select_auto", "select_manual", "select_batch", *DEVICE_START_ORDER})


@dataclass
class Event:
    t: float
    type: str
    data: dict[str, object] = field(default_factory=dict)


class EventLog:
    """`controller_state=False` (Phase 9 step 3): the line's controller
    publishes no state -- an external controller without a status block --
    so only commands are recorded; there is no state or alarm to diff."""

    def __init__(self, line: LineController, controller_state: bool = True) -> None:
        self.line = line
        self.controller_state = controller_state
        self.events: list[Event] = []
        self._last_state = None
        self._last_alarm: dict[str, tuple[bool, bool]] = {}
        self._pending_commands: list[str] = []

    def record_command(self, command: str) -> None:
        """The LineController.command_sink target. Queues only -- see the
        module docstring for why the timestamp waits for sample(t)."""
        self._pending_commands.append(command)

    def sample(self, t: float) -> None:
        """Call once per tick -- after line.scan(dt) has run, so this
        reads the tick's settled state, not a stale one. The very first
        call on a fresh EventLog only ever establishes a baseline; it
        can't know whether the line's current state/alarms are "new"
        this tick or already true before observation started, so it
        emits nothing rather than guess. Queued commands are the
        exception: a command is a recorded fact, not a diff, so there's
        no baseline to establish for it and it's emitted even on the
        first call."""
        refusable = [c for c in self._pending_commands if c in REFUSABLE]
        self._flush_commands(t)
        if self.controller_state:
            if refusable and self.line.start_inhibit != StartInhibit.NONE:
                self.events.append(Event(t=t, type="command_refused", data={
                    "commands": refusable, "inhibit": inhibit_names(self.line.start_inhibit)}))
            self._sample_state(t)
            self._sample_alarms(t)

    def _flush_commands(self, t: float) -> None:
        for command in self._pending_commands:
            self.events.append(Event(t=t, type="command_issued", data={"command": command}))
        self._pending_commands.clear()

    def _sample_state(self, t: float) -> None:
        current = self.line.state
        if self._last_state is not None and current != self._last_state:
            self.events.append(
                Event(
                    t=t,
                    type="state_changed",
                    data={
                        "from": self._last_state.name.lower(),
                        "to": current.name.lower(),
                        "fault_reason": self.line.fault_reason,
                    },
                )
            )
        self._last_state = current

    def _sample_alarms(self, t: float) -> None:
        for alarm in self.line.alarms.all_alarms:
            previous = self._last_alarm.get(alarm.id)
            if previous is not None:
                was_active, was_acknowledged = previous
                if alarm.active and not was_active:
                    self.events.append(
                        Event(
                            t=t,
                            type="alarm_activated",
                            data={
                                "alarm_id": alarm.id,
                                "description": alarm.description,
                                "is_warning": alarm.is_warning,
                                "first_out": alarm.first_out,
                            },
                        )
                    )
                if was_active and not alarm.active:
                    self.events.append(Event(t=t, type="alarm_cleared", data={"alarm_id": alarm.id}))
                if alarm.acknowledged and not was_acknowledged:
                    self.events.append(Event(t=t, type="alarm_acknowledged", data={"alarm_id": alarm.id}))
            self._last_alarm[alarm.id] = (alarm.active, alarm.acknowledged)


def write_jsonl(event_log: EventLog, path: Path) -> None:
    """One JSON object per line, `t`/`type` plus that event's own fields
    flattened alongside them -- meant to be read, not parsed back in
    (docs/CONTROL-LAB.md §8: "every artifact is inspectable")."""
    with path.open("w", encoding="utf-8") as f:
        for event in event_log.events:
            f.write(json.dumps({"t": event.t, "type": event.type, **event.data}) + "\n")
