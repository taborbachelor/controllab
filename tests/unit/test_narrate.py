"""Plain-English narration (services/visualization/narrate.py), driven by a
real LiveSession so every sentence is checked against what the controller
actually did."""
from services.visualization.live import LiveSession
from services.visualization.narrate import _FAULTS, narrate


def story(s: LiveSession, running: bool = True) -> dict:
    return narrate({**s.snapshot(), "running": running})


def steps(s: LiveSession, n: int) -> None:
    for _ in range(n):
        s.step()


def running_session() -> LiveSession:
    s = LiveSession()
    s.command("start")
    steps(s, 20)
    assert s.snapshot()["state"] == "running"
    return s


def test_a_fresh_line_says_it_is_ready_and_what_start_will_do():
    st = story(LiveSession())
    assert st["headline"] == "Stopped and ready." and "Press Start" in st["detail"]


def test_starting_names_the_step_it_is_on():
    s = LiveSession()
    s.command("start")
    s.step()
    assert "Step 1 of 3" in story(s)["detail"]


def test_running_and_the_feeder_pausing_at_the_high_mark():
    s = running_session()
    assert story(s)["headline"] == "Running."
    s.stimulus("hopper_level_pct", 85)
    steps(s, 3)
    assert story(s)["headline"] == "Running, feeder paused (hopper full)."


def test_a_refused_start_says_why_and_how_to_fix_it():
    """The case that prompted this module: Start pressed repeatedly with a
    near-empty bin and nothing on the page saying why it was refused."""
    s = LiveSession()
    s.stimulus("bin_level_pct", 5)
    s.step()
    s.command("start")
    steps(s, 2)
    st = story(s)
    assert st["headline"] == "Stopped. The last Start was refused."
    assert "the bin is nearly empty" in st["detail"]
    assert [x["text"] for x in st["steps"]][-1] == "Press Start again"
    assert any("Set bin level" in x["text"] for x in st["steps"])


def test_a_trip_gives_the_recovery_checklist_and_ticks_it_off():
    s = running_session()
    s.stimulus("feeder_trip", True)
    steps(s, 3)
    st = story(s)
    assert st["tone"] == "trip" and "motor drive reported a fault" in st["detail"]
    ack = next(x for x in st["steps"] if x["text"].startswith("Press Acknowledge"))
    assert ack["done"] is False
    s.command("acknowledge")
    s.step()
    assert next(x for x in story(s)["steps"] if x["text"].startswith("Press Acknowledge"))["done"] is True


def test_every_fault_reason_the_controller_can_give_is_explained():
    from services.protocols.controller_status import FAULT_REASONS

    unexplained = [r for r in FAULT_REASONS if r and r != "e-stop" and r not in _FAULTS]
    assert unexplained == []


def test_the_stuck_switch_story_explains_the_disagreement():
    s = running_session()
    s.stimulus("sensor_stuck", "LSHH-105")
    s.stimulus("hopper_level_pct", 97)
    steps(s, 15)
    assert "one of them is wrong" in story(s)["detail"]


def test_emergency_stop():
    s = running_session()
    s.stimulus("estop", "tripped")
    steps(s, 2)
    st = story(s)
    assert st["headline"].startswith("Emergency stop") and st["steps"][0]["done"] is False


def test_paused_says_so_and_lists_what_is_waiting():
    s = LiveSession()
    s.command("start")
    st = story(s, running=False)
    assert st["headline"].startswith("Paused.") and "Waiting to apply: start" in st["detail"]


def test_the_checklist_ticks_off_the_fix_once_the_cause_is_gone():
    s = running_session()
    s.stimulus("sensor_stuck", "LSHH-105")
    s.stimulus("hopper_level_pct", 97)
    steps(s, 15)
    first = story(s)["steps"]
    assert first[0] == {"text": "Repair LSHH-105 (Engineer tools → Instrument faults → LSHH-105 → Restore)", "done": False}
    assert first[1]["text"].startswith("Lower the hopper level") and first[1]["done"] is False
    s.stimulus("sensor_restored", "LSHH-105")
    s.stimulus("hopper_level_pct", 50)
    steps(s, 2)
    after = story(s)["steps"]
    assert after[0]["text"].startswith("Lower the hopper level") and after[0]["done"] is True


def test_every_explained_fault_says_how_to_tell_its_cause_is_gone():
    from services.visualization.narrate import _CLEARED

    assert set(_CLEARED) == set(_FAULTS)

