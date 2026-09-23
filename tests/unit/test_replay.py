"""build_frames()/render_html() against hand-built telemetry: a bare
IOImage and TagHistory (the same fixture tier test_tag_history.py uses)
plus hand-written events -- the replay is defined purely by what
telemetry records, so that's all these tests need."""
import json
import re

from services.simulation.engine.io_image import IOImage, TagType
from services.telemetry.events import Event
from services.telemetry.tag_history import TagHistory
from services.visualization.replay import build_frames, build_replay, render_html


def history(n: int) -> TagHistory:
    io = IOImage()
    io.define("X-1", TagType.DI, description="a switch")
    h = TagHistory(io)
    for k in range(n):
        h.record(round(k * 0.1, 9))
    return h


def activated(t, alarm_id="A-1", first_out=True, is_warning=False):
    return Event(t, "alarm_activated", {"alarm_id": alarm_id, "description": "d", "is_warning": is_warning, "first_out": first_out})


def test_one_frame_per_sample_with_state_from_events():
    events = [
        Event(0.1, "command_issued", {"command": "start"}),
        Event(0.1, "state_changed", {"from": "idle", "to": "starting", "fault_reason": None}),
        Event(0.3, "state_changed", {"from": "starting", "to": "running", "fault_reason": None}),
    ]
    frames = build_frames(events, history(5))
    assert [f["state"] for f in frames] == ["idle", "starting", "starting", "running", "running"]
    assert [f["events"] for f in frames] == [[], [0, 1], [], [2], []]


def test_alarm_stays_on_the_board_until_cleared_and_acknowledged():
    events = [
        activated(0.1),
        Event(0.2, "alarm_cleared", {"alarm_id": "A-1"}),
        Event(0.4, "alarm_acknowledged", {"alarm_id": "A-1"}),
    ]
    frames = build_frames(events, history(6))
    board = [[(a["active"], a["acknowledged"]) for a in f["alarms"]] for f in frames]
    assert board == [[], [(True, False)], [(False, False)], [(False, False)], [], []]


def test_acknowledged_but_still_active_alarm_stays_latched():
    frames = build_frames([activated(0.1), Event(0.2, "alarm_acknowledged", {"alarm_id": "A-1"})], history(4))
    assert frames[3]["alarms"] == [
        {"id": "A-1", "description": "d", "is_warning": False, "active": True, "acknowledged": True, "first_out": True}
    ]


def test_first_out_rides_with_the_alarm_that_claimed_it():
    frames = build_frames([activated(0.1, "B", True), activated(0.1, "A", False)], history(2))
    assert {a["id"]: a["first_out"] for a in frames[1]["alarms"]} == {"A": False, "B": True}


def test_render_html_embeds_the_data_and_cannot_be_broken_out_of():
    replay = build_replay("T</script><script>alert(1)", [], history(2), plant={"hopper_capacity_kg": 1.0})
    html = render_html(replay)
    assert "/*__REPLAY_DATA__*/" not in html
    assert html.count("</script>") == 1  # only the template's own closing tag

    embedded = re.search(r"const R = (.*?);\n", html).group(1)
    assert json.loads(embedded.replace("<\/", "</"))["title"] == "T</script><script>alert(1)"


def test_build_replay_carries_tag_metadata_for_the_tag_table():
    replay = build_replay("T", [], history(1), plant={})
    assert replay["tags"] == [{"name": "X-1", "type": "DI", "units": "", "description": "a switch"}]
