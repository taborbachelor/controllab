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
    steps(s, 12)  # Start waits for the gates to finish closing (the gates-closed permissive)
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
        lambda s: s.stimulus("sensor_stuck", "XV-102.CMD_OPEN"),  # an output, not an instrument
        lambda s: s.stimulus("sensor_failed", "LT-101"),  # analog, no diagnostic: can only stick
        lambda s: s.stimulus("sensor_restored", True),
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


def test_instrument_faults_from_the_dashboard_show_the_level_protection():
    """The dashboard's instrument panel: LSHH-105 stuck healthy, the hopper
    set to 97 %, and WT-105 still trips the line (1oo2); the cross-check
    then names the switch."""
    s = LiveSession()
    s.command("start")
    steps(s, 20)
    s.stimulus("sensor_stuck", "LSHH-105")
    s.stimulus("hopper_level_pct", 97)
    steps(s, 8)  # the transmitter's vote holds for 0.5 s before it counts
    snap = s.snapshot()
    assert snap["state"] == "faulted" and snap["injected"]["instruments"] == {"LSHH-105": "stuck"}
    steps(s, 12)
    assert {a["id"] for a in s.snapshot()["alarms"]} == {"WT-105.HIGH_HIGH", "LSHH-105.DISAGREE"}
    s.stimulus("sensor_restored", "LSHH-105")
    s.step()
    assert s.snapshot()["injected"]["instruments"] == {}


def test_manual_mode_through_the_dashboard_commands():
    from services.protocols.line_map import LINE_REGISTER_MAP
    from services.visualization.live import COMMANDS

    assert list(COMMANDS) == LINE_REGISTER_MAP.commands  # the HMI request word's bit order
    s = LiveSession()
    assert s.snapshot()["line_mode"] == "auto"
    s.command("select_manual")
    s.step()
    s.command("start_conveyor")
    for _ in range(6):
        s.step()
    snap = s.snapshot()
    assert (snap["state"], snap["line_mode"]) == ("manual", "manual")
    assert snap["values"]["M-104.RUN"] and snap["values"]["ZSS-104"]
    assert [e["command"] for e in snap["events"] if e["type"] == "command_issued"] == ["select_manual", "start_conveyor"]


def test_an_external_session_hands_manual_commands_to_the_controller():
    s = LiveSession(external=True)
    assert s.snapshot()["line_mode"] is None  # the mode lives in the external controller
    s.command("select_manual")
    s.step()
    assert "select_manual" in s.handshake.outstanding()


def test_degraded_instruments_from_the_dashboard():
    import pytest

    s = LiveSession()
    s.stimulus("sensor_slow", {"tag": "ZSS-104", "seconds": 1.5})
    s.command("start")
    steps(s, 25)
    snap = s.snapshot()
    assert (snap["state"], snap["fault_reason"]) == ("faulted", "conveyor failed to prove running")
    assert snap["injected"]["instruments"] == {"ZSS-104": "slow"}
    s.stimulus("sensor_noise", {"tag": "WT-105", "amplitude": 30})
    s.step()
    assert s.snapshot()["injected"]["instruments"]["WT-105"] == "noisy"
    for key, value in [
        ("sensor_noise", {"tag": "LSH-105", "amplitude": 30}),   # a switch
        ("sensor_drift", {"tag": "WT-105", "rate_per_s": 0}),    # no drift
        ("sensor_slow", {"tag": "ZSS-104"}),                     # missing its parameter
        ("sensor_noise", "WT-105"),                              # wrong shape
    ]:
        with pytest.raises(ValueError):
            s.stimulus(key, value)
