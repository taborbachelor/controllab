"""EventLog observes a real LineController through a full tick cycle
(state transitions, fault sequences, alarm activation/clear/acknowledge)
-- unlike TagHistory (generic, tested against a bare IOImage),
LineController/AlarmManager are inherently line-specific, so these tests
use the real rig, the same tier test_line_controller.py already
established for this class of behavior.
"""
import json

from services.telemetry.events import EventLog, write_jsonl
from services.testing.rig import DT, build_rig, run, tick


def run_and_sample(rig, event_log, seconds, dt: float = DT) -> None:
    """The driving pattern a real telemetry-enabled run would use: tick,
    then sample at the same boundary, using the rig's own elapsed time
    (Plant.time_s) rather than a separately tracked counter -- whatever
    drives the loop already has that number."""
    for _ in range(round(seconds / dt)):
        tick(rig, dt)
        event_log.sample(rig.plant.time_s)


def test_first_sample_establishes_baseline_without_emitting_events():
    rig = build_rig()
    event_log = EventLog(rig.line)
    event_log.sample(t=0.0)
    assert event_log.events == []


def test_normal_start_emits_a_state_changed_event_per_transition():
    rig = build_rig()
    event_log = EventLog(rig.line)
    event_log.sample(rig.plant.time_s)

    rig.line.start()
    run_and_sample(rig, event_log, 5.0)
    assert rig.line.state.name == "RUNNING"

    transitions = [(e.data["from"], e.data["to"]) for e in event_log.events if e.type == "state_changed"]
    assert transitions == [("idle", "starting"), ("starting", "running")]


def test_fault_state_changed_event_carries_the_fault_reason():
    rig = build_rig()
    rig.plant.gate.stuck = True
    event_log = EventLog(rig.line)
    event_log.sample(rig.plant.time_s)

    rig.line.start()
    run_and_sample(rig, event_log, 5.0)
    assert rig.line.state.name == "FAULTED"

    faulted_events = [e for e in event_log.events if e.type == "state_changed" and e.data["to"] == "faulted"]
    assert len(faulted_events) == 1
    assert faulted_events[0].data["fault_reason"] == "gate failed to prove open"


def test_alarm_activation_emits_alarm_activated_with_first_out():
    rig = build_rig()
    event_log = EventLog(rig.line)
    event_log.sample(rig.plant.time_s)

    rig.plant.hopper.level_kg = 1_950.0  # 97.5% -- above the 95% high-high threshold
    run_and_sample(rig, event_log, 0.2)

    activated = [e for e in event_log.events if e.type == "alarm_activated"]
    assert len(activated) == 1
    assert activated[0].data["alarm_id"] == "WT-105.HIGH_HIGH"
    assert activated[0].data["first_out"] is True
    assert activated[0].data["is_warning"] is False


def test_two_simultaneous_alarms_only_the_first_registered_gets_first_out():
    rig = build_rig()
    event_log = EventLog(rig.line)
    event_log.sample(rig.plant.time_s)

    rig.plant.estop.trip()
    rig.plant.hopper.level_kg = 1_950.0
    run_and_sample(rig, event_log, 0.2)

    activated = {e.data["alarm_id"]: e.data["first_out"] for e in event_log.events if e.type == "alarm_activated"}
    assert activated == {"ES-001.TRIP": True, "WT-105.HIGH_HIGH": False}


def test_alarm_clear_and_acknowledge_are_separate_events_in_order():
    """Hopper high-high, not a gate/motor fault: it's a pure level
    condition, freely settable up and down with no Control-driven
    fault-latching involved, so it clears exactly once and stays
    cleared -- the cleanest possible case for proving activate/clear/
    acknowledge are three distinct events in the right order, unclouded
    by an unrelated device's own timing behavior."""
    rig = build_rig()
    event_log = EventLog(rig.line)
    event_log.sample(rig.plant.time_s)

    rig.plant.hopper.level_kg = 1_950.0  # 97.5% -- above the 95% high-high threshold
    run_and_sample(rig, event_log, 0.2)

    rig.plant.hopper.level_kg = 500.0  # recovers -- comfortably below
    run_and_sample(rig, event_log, 0.2)

    hopper_events = [e for e in event_log.events if e.data.get("alarm_id") == "WT-105.HIGH_HIGH"]
    assert [e.type for e in hopper_events] == ["alarm_activated", "alarm_cleared"]

    rig.line.acknowledge()
    run_and_sample(rig, event_log, 0.1)

    hopper_events = [e for e in event_log.events if e.data.get("alarm_id") == "WT-105.HIGH_HIGH"]
    assert [e.type for e in hopper_events] == ["alarm_activated", "alarm_cleared", "alarm_acknowledged"]


def test_write_jsonl_produces_one_parseable_object_per_line(tmp_path):
    rig = build_rig()
    event_log = EventLog(rig.line)
    event_log.sample(rig.plant.time_s)
    rig.line.start()
    run_and_sample(rig, event_log, 5.0)
    assert len(event_log.events) >= 2

    out = tmp_path / "events.jsonl"
    write_jsonl(event_log, out)

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(event_log.events)
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["type"] == "state_changed"
    assert parsed[0]["from"] == "idle"
    assert parsed[0]["to"] == "starting"


# ---- Phase 5 step 3: the command sink ---------------------------------


def attach(rig) -> EventLog:
    event_log = EventLog(rig.line)
    rig.line.command_sink = event_log.record_command
    event_log.sample(rig.plant.time_s)
    return event_log


def test_command_sink_is_none_by_default():
    assert build_rig().line.command_sink is None


def test_command_sink_receives_every_command_in_issue_order():
    rig = build_rig()
    received: list[str] = []
    rig.line.command_sink = received.append

    rig.line.start()
    rig.line.stop()
    rig.line.reset()
    rig.line.acknowledge()
    assert received == ["start", "stop", "reset", "acknowledge"]


def test_a_command_with_no_state_change_is_still_recorded():
    """The whole reason the sink exists: stop() while already IDLE
    changes nothing a diff could see, but an audit trail must still show
    the button was pressed."""
    rig = build_rig()
    event_log = attach(rig)

    rig.line.stop()
    run_and_sample(rig, event_log, 0.5)

    assert rig.line.state.name == "IDLE"
    assert [(e.type, e.data) for e in event_log.events] == [("command_issued", {"command": "stop"})]


def test_command_is_stamped_at_the_consuming_tick_and_precedes_its_effect():
    rig = build_rig()
    event_log = attach(rig)
    t_before = rig.plant.time_s

    rig.line.start()
    run_and_sample(rig, event_log, DT)

    first_two = event_log.events[:2]
    assert [e.type for e in first_two] == ["command_issued", "state_changed"]
    assert first_two[0].data == {"command": "start"}
    assert first_two[1].data["to"] == "starting"
    assert first_two[0].t == first_two[1].t == rig.plant.time_s
    assert first_two[0].t > t_before


def test_commands_issued_before_the_first_sample_are_not_swallowed_by_the_baseline():
    rig = build_rig()
    event_log = EventLog(rig.line)
    rig.line.command_sink = event_log.record_command

    rig.line.acknowledge()
    event_log.sample(rig.plant.time_s)
    assert [e.type for e in event_log.events] == ["command_issued"]


def test_attaching_a_sink_changes_no_control_behavior():
    """Same stimulus, with and without a sink: the line's state trace must
    be identical tick for tick (docs/CONTROL-LAB.md §7: deterministic)."""

    def trace(with_sink: bool) -> list[tuple[str, str | None]]:
        rig = build_rig()
        rig.plant.gate.stuck = True
        if with_sink:
            rig.line.command_sink = lambda _cmd: None
        out = []
        rig.line.start()
        for _ in range(40):
            tick(rig)
            out.append((rig.line.state.name, rig.line.fault_reason))
        rig.line.acknowledge()
        rig.line.reset()
        for _ in range(10):
            tick(rig)
            out.append((rig.line.state.name, rig.line.fault_reason))
        return out

    assert trace(with_sink=False) == trace(with_sink=True)


def test_write_jsonl_includes_command_events(tmp_path):
    rig = build_rig()
    event_log = attach(rig)
    rig.line.start()
    run_and_sample(rig, event_log, 0.1)

    out = tmp_path / "events.jsonl"
    write_jsonl(event_log, out)
    first = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert first == {"t": first["t"], "type": "command_issued", "command": "start"}
