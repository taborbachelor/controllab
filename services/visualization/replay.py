"""Replay of a recorded run (docs/CONTROL-LAB.md §10, Phase 6 step 2):
turns the two Phase 5 telemetry records -- the EventLog's events and a
TagHistory -- into one self-contained HTML file that plays the run back
on a line mimic, tick by tick.

Replay is built purely from telemetry, never from a live rig: the file
shows what was recorded, not a re-simulation that could disagree with it.
That's why line state and the alarm board are *reconstructed from
events* here (state_changed, alarm_activated/cleared/acknowledged), not
read from LineController -- if the reconstruction and the live system
ever disagreed, the event log would be missing a fact, and the tests in
tests/unit/test_replay.py are where that would surface.

Depends only on Telemetry (the Visualization row of §3.1: "Telemetry
(read)"). It knows nothing about scenarios or the runner -- a caller
(scripts/replay.py) hands it events, tags, and a title, so a future live
dashboard recording or an external-controller run can be replayed the
same way.

Writes no files, the same split every other layer uses: build_frames()
is the tested data model, render_html() only substitutes it into
replay_template.html (assembled by page.py with the shared mimic) and returns a string;
scripts/replay.py is the only thing that writes one. Output is
deterministic (no timestamps, no absolute paths), so a replay file can
be committed and diffed like the commissioning report.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from services.telemetry.events import Event
from services.telemetry.tag_history import TagHistory
from services.visualization.page import assemble

DATA_PLACEHOLDER = "/*__REPLAY_DATA__*/null"


@dataclass
class AlarmView:
    id: str
    description: str
    is_warning: bool
    active: bool
    acknowledged: bool
    first_out: bool


def build_frames(events: list[Event], tags: TagHistory, initial_state: str = "idle") -> list[dict]:
    """One frame per TagHistory sample: that sample's tag values, the line
    state in effect, the latched alarm board, and the indexes of events
    that happened at exactly that tick.

    An alarm is on the board while latched (active, or not yet
    acknowledged) -- the same definition as services/control/alarms.py.
    first_out is sticky until the alarm drops off the board, matching
    the per-episode first-out rule there."""
    frames: list[dict] = []
    state = initial_state
    board: dict[str, AlarmView] = {}
    i = 0
    for sample in tags.samples:
        fired: list[int] = []
        while i < len(events) and events[i].t <= sample.t:
            state = _apply(events[i], state, board)
            fired.append(i)
            i += 1
        for alarm_id in [a.id for a in board.values() if not a.active and a.acknowledged]:
            del board[alarm_id]
        frames.append(
            {
                "t": sample.t,
                "state": state,
                "values": sample.values,
                "alarms": [vars(a).copy() for a in sorted(board.values(), key=lambda a: a.id)],
                "events": fired,
            }
        )
    return frames


def _apply(event: Event, state: str, board: dict[str, AlarmView]) -> str:
    d = event.data
    if event.type == "state_changed":
        return str(d["to"])
    if event.type == "alarm_activated":
        board[d["alarm_id"]] = AlarmView(
            id=d["alarm_id"],
            description=d["description"],
            is_warning=bool(d["is_warning"]),
            active=True,
            acknowledged=False,
            first_out=bool(d["first_out"]),
        )
    elif event.type == "alarm_cleared" and d["alarm_id"] in board:
        board[d["alarm_id"]].active = False
    elif event.type == "alarm_acknowledged" and d["alarm_id"] in board:
        board[d["alarm_id"]].acknowledged = True
    return state


def build_replay(title: str, events: list[Event], tags: TagHistory, plant: dict, meta: dict | None = None) -> dict:
    """Everything the page needs, as one JSON-serializable dict. `plant`
    carries the physical constants the mimic needs to draw levels
    (hopper capacity and switch setpoints -- WT-105 is in kg, not %).
    `meta` is free-form run context shown in the header (pass/fail,
    source file, ...)."""
    return {
        "title": title,
        "meta": meta or {},
        "plant": plant,
        "tags": [
            {"name": n, "type": tags.io.tag(n).type.name, "units": tags.io.tag(n).units, "description": tags.io.tag(n).description}
            for n in tags.io.names()
        ],
        "events": [{"t": e.t, "type": e.type, **e.data} for e in events],
        "frames": build_frames(events, tags),
    }


def render_html(replay: dict) -> str:
    """Substitutes the replay data into the template. `</` is escaped so
    no recorded string can close the <script> block early."""
    data = json.dumps(replay, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = assemble("replay_template.html")
    assert template.count(DATA_PLACEHOLDER) == 1, "replay_template.html must contain the data placeholder exactly once"
    return template.replace(DATA_PLACEHOLDER, data)
