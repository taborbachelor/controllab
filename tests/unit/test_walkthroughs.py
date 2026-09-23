"""Every guided walkthrough (services/visualization/walkthroughs.py) runs to
completion on a real LiveSession: each step's own "Do it for me" actions,
then ticks until the line actually reaches the step's condition. A step
whose condition can't be reached, or that completes before its action, is
a broken walkthrough, and a newcomer would be the one to find it."""
import pytest

from services.visualization.live import COMMANDS, LiveSession
from services.visualization.walkthroughs import WALKTHROUGHS

MAX_TICKS_PER_STEP = 300  # 30 s of plant time; the slowest step (stop and purge) takes ~2 s


def advance(s: LiveSession, index: int) -> int:
    """Tick until the walkthrough leaves step `index`; returns ticks taken."""
    for n in range(1, MAX_TICKS_PER_STEP + 1):
        s.step()
        if s.snapshot()["tour"]["index"] > index:
            return n
    raise AssertionError(f"step {index + 1} never completed: {s.snapshot()['tour']['say']}")


@pytest.mark.parametrize("w", WALKTHROUGHS, ids=[w.id for w in WALKTHROUGHS])
def test_every_walkthrough_runs_to_completion_with_do_it_for_me(w):
    s = LiveSession()
    s.start_tour(w.id)
    for i, step in enumerate(w.steps):
        view = s.snapshot()["tour"]
        assert view["index"] == i and view["say"] == step.say and view["can_do"] == bool(step.do)
        if step.do:
            s.tour_do()
        advance(s, i)
        assert s.snapshot()["tour"]["then"] == step.then
    assert s.snapshot()["tour"]["done"] is True
    assert s.violation is None  # nothing in any walkthrough breaks the physics


@pytest.mark.parametrize("w", WALKTHROUGHS, ids=[w.id for w in WALKTHROUGHS])
def test_no_action_step_completes_before_its_action(w):
    """A step asking the viewer to do something must still be waiting if they
    haven't; otherwise the walkthrough would run ahead of them."""
    s = LiveSession()
    s.start_tour(w.id)
    for i, step in enumerate(w.steps):
        if step.do:
            for _ in range(10):
                s.step()
            assert s.snapshot()["tour"]["index"] == i, f"step {i + 1} completed without its action"
            s.tour_do()
        advance(s, i)


def test_pressing_the_real_buttons_works_the_same_as_do_it_for_me():
    s = LiveSession()
    s.start_tour("normal")
    s.command("start")
    advance(s, 0)
    advance(s, 1)
    advance(s, 2)
    s.command("stop")
    advance(s, 3)
    advance(s, 4)
    assert s.snapshot()["tour"]["done"] is True


def test_every_highlight_target_exists_on_the_page():
    from services.visualization.page import assemble

    page = assemble("live_template.html")
    import re

    js_generated = {  # buttons the page builds from data at load time
        "data-fault": {"estop", "conveyor_trip", "feeder_trip", "conveyor_fail_to_start", "feeder_fail_to_start",
                       "gate_stuck", "belt_slip", "feeder_jam"},
        "data-inst": {"WT-105", "LSH-105", "LSHH-105"},
    }
    for w in WALKTHROUGHS:
        for step in w.steps:
            if not step.target:
                continue
            for attr, value in re.findall(r'\[([\w-]+)="([^"]+)"\]', step.target):
                if attr == "data-kind":
                    assert value in ("stuck", "failed", "restored")
                elif attr == "data-cmd":
                    assert value in COMMANDS, (w.id, step.target)  # the page builds these from the config
                elif attr in js_generated:
                    assert value in js_generated[attr], (w.id, step.target)
                    assert f'"{value}"' in page, (w.id, step.target)  # the page's own list names it
                else:
                    assert f'{attr}="{value}"' in page, (w.id, step.target)


def test_new_session_ends_the_walkthrough_and_bad_requests_are_refused():
    s = LiveSession()
    s.start_tour("estop")
    s.restart()
    assert s.snapshot()["tour"] is None
    with pytest.raises(ValueError):
        s.start_tour("nope")
    with pytest.raises(ValueError):
        s.tour_do()  # no walkthrough active
    with pytest.raises(ValueError):
        LiveSession(external=True).start_tour("normal")
