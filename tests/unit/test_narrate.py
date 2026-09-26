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
    assert "the source bin is nearly empty" in st["detail"]
    assert [x["text"] for x in st["steps"]][-1] == "Press Start again"
    assert any("Set bin A/B/C level" in x["text"] for x in st["steps"])


def test_a_start_refused_on_a_gate_not_closed_says_why():
    """The gates-closed permissive (2026-09-25): a gate stuck short of
    closed refuses Start, and the page says which check and what to do."""
    s = running_session()
    s.stimulus("gate_stuck", True)
    s.command("stop")
    steps(s, 30)
    assert s.snapshot()["state"] == "faulted"
    s.command("acknowledge")
    s.command("reset")
    steps(s, 2)
    s.command("start")
    steps(s, 2)
    st = story(s)
    assert st["headline"] == "Stopped. The last Start was refused."
    assert "isn't proven closed at its closed limit switch" in st["detail"]
    assert [x["text"] for x in st["steps"]][-1] == "Press Start again"


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



# ---- Manual mode ---------------------------------------------------------


def manual_session() -> LiveSession:
    s = LiveSession()
    s.command("select_manual")
    s.step()
    assert s.snapshot()["state"] == "manual"
    return s


def test_manual_with_everything_off_says_so_and_lists_the_order_that_moves_material():
    st = story(manual_session())
    assert st["headline"] == "Manual mode: every device is off. You drive each one."
    assert "bypasses the start sequence, not the protection" in st["detail"]
    assert [x["done"] for x in st["steps"]] == [False, False, False]


def test_manual_ticks_off_each_device_from_the_field_and_says_when_material_flows():
    s = manual_session()
    s.command("start_conveyor")
    steps(s, 6)
    assert [x["done"] for x in story(s)["steps"]] == [True, False, False]
    s.command("open_gate")
    s.command("start_feeder")
    steps(s, 15)
    st = story(s)
    assert st["headline"] == "Manual mode: material is flowing."
    assert all(x["done"] for x in st["steps"])


def test_a_refused_manual_feeder_start_says_why_and_what_to_do():
    s = manual_session()
    s.command("start_feeder")
    s.step()
    st = story(s)
    assert st["tone"] == "warn" and st["headline"] == "Manual mode. The last request was refused."
    assert "only feed onto a moving belt" in st["detail"]
    assert st["steps"] == [{"text": "Start the conveyor first and wait for it to show running", "done": False}]


def test_the_high_switch_stopping_a_manual_feeder_is_explained():
    s = manual_session()
    s.command("start_conveyor")
    steps(s, 6)
    s.command("open_gate")
    s.command("start_feeder")
    steps(s, 15)
    s.stimulus("hopper_level_pct", 85)
    steps(s, 3)
    assert story(s)["detail"].startswith("The hopper is at its high switch, so the feeder is stopped.")


def test_a_device_command_in_auto_is_a_refused_request_not_a_refused_start():
    s = LiveSession()
    s.command("start_conveyor")
    s.step()
    st = story(s)
    assert st["headline"] == "Stopped. That request was refused."
    assert "only work in Manual mode" in st["detail"]
    assert all(x["text"] != "Press Start again" for x in st["steps"])


def test_every_refusal_the_controller_can_give_has_plain_words():
    """Each reason LineController puts in last_start_refusal matches a prefix
    here, so no refusal ever reaches the card unexplained."""
    from services.visualization.narrate import _REFUSALS
    reasons = [
        "bin low", "hopper at high-high", "hopper weight signal failed", "unacknowledged alarm: M-104.OL",
        "conveyor not proven running", "hopper at the high switch", "device commands need Manual mode",
        "line Start is an Auto command; in Manual start each device", "mode change to manual refused: the line is running",
        "recipe is empty", "recipe is more than fits under the high switch (1600 kg)", "hopper not empty",
    ]
    for r in reasons:
        assert any(r.startswith(prefix) for prefix, _, _ in _REFUSALS), r


def test_a_batch_narrates_where_it_is():
    s = LiveSession()
    s.command("select_batch")
    s.step()
    assert story(s)["headline"] == "Batch mode: ready for a batch."
    s.command("start")
    s.step()
    assert "recipe has no bin in it" in story(s)["detail"]  # refused: no recipe yet
    s.setpoint("recipe_b_kg", 100)
    s.step()
    s.command("start")
    steps(s, 10)
    st = story(s)
    assert st["headline"] == "Batch: Loading." and "bin B" in st["detail"]
    assert [x["done"] for x in st["steps"]] == [False, False, False, False]
