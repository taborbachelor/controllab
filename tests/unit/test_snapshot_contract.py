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
