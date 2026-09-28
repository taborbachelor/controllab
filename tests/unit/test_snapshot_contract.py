"""What the live snapshot and the recordings carry for the frontend
redesign (the controller contract, step 3): the controller's preview of
each refusable request, and the plant reading the picture needs for a
belt that stopped holding material. Both are data only; the page decides
nothing from them."""
from pathlib import Path

from services.telemetry.events import REFUSABLE
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario
from services.visualization.live import LiveSession
from services.visualization.replay import build_frames

SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"


def steps(session: LiveSession, n: int) -> None:
    for _ in range(n):
        session.step()


def test_the_snapshot_previews_every_refusable_request():
    s = LiveSession()
    s.stimulus("bin_level_pct", 5)
    steps(s, 3)
    preview = s.snapshot()["preview"]
    assert set(preview) == REFUSABLE
    assert preview["start"] == {"accepted": False, "inhibits": ["BIN_LOW"], "reasons": ["bin low"]}
    assert preview["reset"] == {"accepted": True, "inhibits": [], "reasons": []}
    assert preview["start_feeder"]["inhibits"] == ["WRONG_MODE"]


def test_the_preview_is_the_controllers_answer_after_the_press():
    s = LiveSession()
    s.stimulus("bin_level_pct", 5)
    steps(s, 3)
    before = s.snapshot()["preview"]["start"]
    s.command("start")
    s.step()
    snap = s.snapshot()
    assert snap["state"] == "idle"
    assert (before["reasons"], before["inhibits"]) == (snap["last_start_refusal"], ["BIN_LOW"])
    refused = [e for e in snap["events"] if e["type"] == "command_refused"]
    assert refused == [{"t": refused[0]["t"], "type": "command_refused", "commands": ["start"], "inhibit": ["BIN_LOW"]}]


def test_an_external_controller_has_no_preview():
    """It can only be asked by pressing: the page shows every row unknown."""
    assert LiveSession(external=True).snapshot()["preview"] is None


def test_the_belt_load_is_a_plant_reading_not_a_tag():
    s = LiveSession()
    s.command("start")
    steps(s, 60)
    snap = s.snapshot()
    assert snap["plant"]["belt_load_kg"] > 0
    assert "belt_load_kg" not in snap["values"]  # never passes for I/O


def test_a_recording_shows_material_stranded_on_a_stopped_belt():
    """The picture's loaded-but-stopped belt: a conveyor trip stops the belt
    with its load on it, which only the plant reading can show."""
    scenario = Scenario.load(SCENARIOS / "faults" / "conveyor_trip_recovery.yaml")
    result = run_scenario(scenario)
    frames = build_frames(result.events, result.tags)
    stranded = [f for f in frames if f["state"] == "faulted" and not f["values"]["ZSS-104"]
                and f["plant"]["belt_load_kg"] > 0]
    assert stranded, "the tripped belt should hold material"
    assert all("belt_load_kg" in f["plant"] for f in frames)


def test_a_standing_cause_is_data_the_picture_can_point_at():
    """C1 of the frontend/controls boundary: the jam a reset waits out, with
    the equipment it is on and the input showing it, never text to parse;
    gone once the cause is."""
    s = LiveSession()
    s.command("start")
    steps(s, 60)
    assert s.snapshot()["standing_causes"] == []
    s.stimulus("feeder_jam", True)
    steps(s, 20)
    snap = s.snapshot()
    assert snap["state"] == "faulted"
    assert snap["standing_causes"] == [{"reason": "feeder jam", "devices": ["FDR-103"], "tags": ["LSH-103"]}]
    assert snap["values"]["LSH-103"] is True  # the tag named is the one showing it
    s.stimulus("feeder_jam", False)
    steps(s, 5)
    assert s.snapshot()["standing_causes"] == []


def test_standing_causes_come_in_the_order_a_reset_reports_them():
    """Two causes at once (a feeder trip and a jam can't both stand: a
    tripped feeder stops before its plug switch makes): the first is the one
    the refused reset names, so the picture and the refusal can't disagree."""
    s = LiveSession()
    s.command("start")
    steps(s, 60)
    s.stimulus("conveyor_trip", True)
    s.stimulus("sensor_failed", "WT-105")
    steps(s, 20)
    causes = s.snapshot()["standing_causes"]
    assert [c["reason"] for c in causes] == ["conveyor trip", "hopper weight signal failed"]
    assert [c["tags"] for c in causes] == [["M-104.OL"], ["WT-105.FLT"]]
    assert causes[0]["reason"] == s.rig.line.standing_cause()
    s.command("acknowledge")
    s.command("reset")
    steps(s, 2)
    assert s.snapshot()["preview"]["reset"]["reasons"] == [f"trip cause still present: {causes[0]['reason']}"]


def test_a_high_high_cause_names_the_measurements_that_vote():
    """1oo2: the hopper full to 98 % trips on both the switch and the
    transmitter, and both are named."""
    s = LiveSession()
    s.stimulus("hopper_level_pct", 98)
    steps(s, 10)
    causes = s.snapshot()["standing_causes"]
    assert causes == [{"reason": "hopper high-high", "devices": ["HOP-105"], "tags": ["LSHH-105", "WT-105"]}]


def test_an_external_controller_has_no_standing_causes_to_report():
    assert LiveSession(external=True).snapshot()["standing_causes"] is None
