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
command issued" -- are deliberately NOT observed here. A command can
occur with zero state change (stop() while already stopped), which a
diff can't see by construction; that's Phase 5 step 3's minimal command
sink, a different mechanism for a different kind of fact, kept separate
on purpose.

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

from services.control.line_controller import LineController


@dataclass
class Event:
    t: float
    type: str
    data: dict[str, object] = field(default_factory=dict)


class EventLog:
    def __init__(self, line: LineController) -> None:
        self.line = line
        self.events: list[Event] = []
        self._last_state = None
        self._last_alarm: dict[str, tuple[bool, bool]] = {}

    def sample(self, t: float) -> None:
        """Call once per tick -- after line.scan(dt) has run, so this
        reads the tick's settled state, not a stale one. The very first
        call on a fresh EventLog only ever establishes a baseline; it
        can't know whether the line's current state/alarms are "new"
        this tick or already true before observation started, so it
        emits nothing rather than guess."""
        self._sample_state(t)
        self._sample_alarms(t)

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
