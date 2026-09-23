"""Unit tests for the Markdown commissioning report renderer, using the
same lightweight-fake approach as test_report.py -- render_markdown()
only reads a handful of fields off Scenario/ScenarioResult, so no YAML
or rig is needed to pin its behavior down.
"""
from dataclasses import dataclass, field
from pathlib import Path

from services.telemetry.events import Event
from services.testing.commissioning_report import RealtimeConditions, describe, render_markdown
from services.testing.report import build_report

ROOT = Path("/somewhere/on/a/build/machine/scenarios")


@dataclass
class FakeScenario:
    name: str
    within_s: float = 1.0
    interlock: str | None = None
    path: Path = ROOT / "faults" / "fake.yaml"


@dataclass
class FakeResult:
    passed: bool
    elapsed_s: float = 0.3
    detail: str = "all expectations met"
    events: list[Event] = field(default_factory=list)
    when_applied_t: float | None = 1.0
    within_tolerance: bool = False
    not_observable: bool = False
    not_observed: tuple = ()


def render(*pairs) -> str:
    return render_markdown(build_report(list(pairs)), ROOT)


def test_overall_verdict_fails_on_any_failed_scenario():
    assert "**Overall: FAIL**" in render((FakeScenario("S1"), FakeResult(False, detail="timed out")))


def test_overall_verdict_fails_on_a_coverage_gap_even_when_every_scenario_passes():
    # No scenario tags any §6.3 row, so every row is a gap.
    assert "**Overall: FAIL**" in render((FakeScenario("S1"), FakeResult(True)))


def test_timing_margin_is_the_limit_minus_the_response_time():
    md = render((FakeScenario("S1", within_s=0.5), FakeResult(True, elapsed_s=0.2)))
    assert "| 0.20 s | 0.50 s | 0.30 s |" in md


def test_a_failure_shows_no_margin_and_lists_its_detail():
    md = render((FakeScenario("S1"), FakeResult(False, detail="timed out after 1.0s")))
    assert "| — | 1.00 s | — |" in md
    assert "- **S1** — timed out after 1.0s" in md


def test_events_are_split_into_setup_and_response_at_when_applied_t():
    events = [
        Event(t=0.1, type="command_issued", data={"command": "start"}),
        Event(t=1.0, type="state_changed", data={"from": "starting", "to": "running", "fault_reason": None}),
        Event(t=1.1, type="command_issued", data={"command": "stop"}),
    ]
    md = render((FakeScenario("S1"), FakeResult(True, events=events, when_applied_t=1.0)))
    assert "| 0.10 | setup | Operator command: **start** |" in md
    assert "| 1.00 | setup | Line state starting → **running** |" in md  # at the boundary = still setup
    assert "| 1.10 | response | Operator command: **stop** |" in md


def test_a_run_that_never_reached_when_labels_everything_setup():
    events = [Event(t=0.5, type="command_issued", data={"command": "start"})]
    md = render((FakeScenario("S1"), FakeResult(False, events=events, when_applied_t=None)))
    assert "| 0.50 | setup |" in md


def test_output_contains_no_absolute_path():
    md = render((FakeScenario("S1"), FakeResult(True)))
    assert "`faults/fake.yaml`" in md
    assert "/somewhere" not in md


def test_pipes_in_free_text_cannot_break_a_table_row():
    md = render((FakeScenario("A | B"), FakeResult(True)))
    assert r"A \| B" in md


def test_describe_marks_first_out_and_distinguishes_warnings():
    alarm = {"alarm_id": "X.1", "description": "Thing", "is_warning": False, "first_out": True}
    assert describe(Event(0.0, "alarm_activated", alarm)) == "Alarm **X.1** active — Thing · **first-out**"
    warning = {**alarm, "is_warning": True, "first_out": False}
    assert describe(Event(0.0, "alarm_activated", warning)) == "Warning **X.1** active — Thing"


def test_fault_reason_only_shown_on_entering_a_fault_state():
    """LineController clears fault_reason on reset, but a stale value
    riding along on a non-fault transition must not read as a cause."""
    into_fault = {"from": "running", "to": "faulted", "fault_reason": "feeder trip"}
    assert describe(Event(0.0, "state_changed", into_fault)).endswith("(feeder trip)")
    out_of_fault = {"from": "faulted", "to": "idle", "fault_reason": "feeder trip"}
    assert "feeder trip" not in describe(Event(0.0, "state_changed", out_of_fault))


def test_an_unknown_event_type_renders_instead_of_raising():
    assert describe(Event(0.0, "something_new", {"k": 1})) == "something_new: {'k': 1}"


def test_a_realtime_report_states_its_conditions_and_marks_tolerance_passes():
    s1, s2 = FakeScenario("On time", path=ROOT / "a.yaml"), FakeScenario("Late", within_s=0.3, path=ROOT / "b.yaml")
    rt = RealtimeConditions(latency_s=0.5, speed=1.0, passes=3,
                            responses={s1.path: [0.2, 0.3, 0.2], s2.path: [0.4, None, 0.3]})
    md = render_markdown(build_report([(s1, FakeResult(True, 0.3)), (s2, FakeResult(True, 0.4, within_tolerance=True))]),
                         ROOT, "a PLC", rt)
    assert "## Real-time conditions" in md
    assert "**Latency tolerance: 0.5 s**" in md and "**Passes: 3.**" in md
    assert "| 🟡 PASS within tolerance | Late | 0.40 s | 0.30 s | -0.10 s |" in md  # the overrun shows, not hidden
    assert "| Late | 2/3 | 0.30 s | 0.40 s | 0.40, fail, 0.30 |" in md


def test_without_realtime_the_report_has_no_realtime_sections():
    md = render((FakeScenario("S1"), FakeResult(True)))
    assert "Real-time conditions" not in md and "across" not in md


def test_unobserved_expectations_are_named_and_never_shown_as_a_plain_pass():
    s1, s2 = FakeScenario("Partly", path=ROOT / "a.yaml"), FakeScenario("Blind", path=ROOT / "b.yaml")
    md = render((s1, FakeResult(True, not_observed=("line_state",))),
                (s2, FakeResult(False, detail="not observable: ...", not_observable=True)))
    assert "| ✅ PASS, partly observed | Partly |" in md
    assert "| 👁️ NOT OBSERVABLE | Blind | — |" in md
    assert "- **Partly** — `line_state`" in md
    assert "**Failures:**" not in md  # not observable is not a failure
    assert "### Blind — NOT OBSERVABLE" in md


def test_a_not_observable_row_still_names_its_scenarios():
    md = render((FakeScenario("Blind", interlock="Hopper not high-high"), FakeResult(False, not_observable=True)))
    assert "| 👁️ not observable (no status block) | Hopper not high-high | Permissive | Blind (not observable) |" in md
