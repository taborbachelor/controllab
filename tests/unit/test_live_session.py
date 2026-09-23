"""LiveSession -- the dashboard's deterministic core -- driven directly,
no HTTP and no real-time thread: step() is one tick, so these tests are
exactly as deterministic as the scenario runner."""
import pytest

from services.visualization.live import LiveSession


def steps(session: LiveSession, n: int) -> None:
    for _ in range(n):
        session.step()


def test_inputs_are_queued_until_the_next_tick():
    s = LiveSession()
    s.command("start")
    assert s.snapshot()["state"] == "idle"  # nothing applied between ticks
    s.step()
    assert s.snapshot()["state"] == "starting"


def test_commands_are_recorded_as_telemetry():
    s = LiveSession()
    s.command("stop")  # a no-op while idle -- still recorded
    s.step()
    assert [(e["type"], e.get("command")) for e in s.snapshot()["events"]] == [("command_issued", "stop")]


def test_a_stimulus_goes_through_the_scenario_vocabulary_and_trips_the_line():
    s = LiveSession()
    s.command("start")
    steps(s, 20)
    s.stimulus("feeder_trip", True)
    steps(s, 3)
    snap = s.snapshot()
    assert snap["state"] == "faulted"
    assert snap["injected"]["feeder_trip"] is True
    assert [a["id"] for a in snap["alarms"]] == ["M-103.FAULT"]


def test_full_operator_recovery_after_a_fault():
    s = LiveSession()
    s.command("start")
    steps(s, 20)
    s.stimulus("feeder_trip", True)
    steps(s, 3)
    s.stimulus("feeder_trip", False)
    s.stimulus("feeder_drive_reset", True)  # the device's own latch -- see vocabulary.py
    s.command("acknowledge")
    steps(s, 2)  # let the cleared fault tag publish before Control's reset
    s.command("reset")
    steps(s, 3)
    s.command("start")
    steps(s, 20)
    assert s.snapshot()["state"] == "running"
    assert s.snapshot()["violation"] is None


def test_setting_a_level_rebaselines_conservation_instead_of_flagging_it():
    s = LiveSession()
    s.stimulus("hopper_level_pct", 97.0)
    steps(s, 3)
    snap = s.snapshot()
    assert snap["violation"] is None
    assert [a["id"] for a in snap["alarms"]] == ["WT-105.HIGH_HIGH"]


def test_invariant_violation_is_reported_not_raised():
    """Adding material behind the invariants' back (not through the
    level stimulus, which rebaselines) is exactly what conservation
    exists to catch -- the session must surface it and keep running."""
    s = LiveSession()
    s.step()
    s.rig.plant.bin.level_kg += 500.0
    s.step()
    assert s.snapshot()["violation"].startswith("t=0.20s")
    s.step()  # keeps running


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.command("explode"),
        lambda s: s.stimulus("teleport", True),
        lambda s: s.stimulus("gate_stuck", "yes"),
        lambda s: s.stimulus("estop", True),
        lambda s: s.stimulus("hopper_level_pct", 150),
        lambda s: s.stimulus("bin_level_pct", True),
        lambda s: s.stimulus("gate_reset", False),
    ],
)
def test_invalid_inputs_are_rejected_before_anything_is_queued(call):
    s = LiveSession()
    with pytest.raises(ValueError):
        call(s)
    s.step()
    assert s.snapshot()["events"] == []


def test_snapshot_since_returns_only_new_events():
    s = LiveSession()
    s.command("start")
    s.step()
    first = s.snapshot()
    assert first["event_count"] == 2
    assert s.snapshot(since=first["event_count"])["events"] == []


def test_restart_gives_a_fresh_line_and_drops_queued_inputs():
    s = LiveSession()
    s.command("start")
    steps(s, 20)
    s.command("stop")
    s.restart()
    s.step()
    snap = s.snapshot()
    assert (snap["state"], snap["t"], snap["event_count"]) == ("idle", 0.1, 0)


def test_a_live_session_downloads_as_a_replay_of_what_happened():
    s = LiveSession()
    s.command("start")
    steps(s, 20)
    html = s.replay_html()
    assert "Live session" in html
    assert '"type":"command_issued","command":"start"' in html


def test_without_a_field_reset_the_tripped_drive_blocks_recovery():
    """Un-injecting the cause alone isn't a repair: the drive's own fault
    latch keeps M-103.FAULT up, so Control's reset is refused."""
    s = LiveSession()
    s.command("start")
    steps(s, 20)
    s.stimulus("feeder_trip", True)
    steps(s, 3)
    s.stimulus("feeder_trip", False)
    s.command("acknowledge")
    s.command("reset")
    steps(s, 3)
    assert s.snapshot()["state"] == "faulted"
