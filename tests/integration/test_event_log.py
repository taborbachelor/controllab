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
