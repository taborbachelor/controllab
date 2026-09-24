"""The candidate-scenario review gate (Phase 8 step 1), on hand-written
candidates -- one per failure mode the gate exists to catch -- plus the
real finding it made on its first run over the existing suite."""
from pathlib import Path

import pytest

from services.testing.candidates import NEEDS_JUDGMENT, READY, REJECTED, render_markdown, review
from services.testing.scenario import Scenario

SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "scenarios"
EXISTING = Scenario.discover(SCENARIOS_DIR)


def candidate(tmp_path, text: str) -> Path:
    p = tmp_path / "candidate.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def levels(r):
    return {f.check: f.level for f in r.findings}


GOOD = """
name: Belt Slip Closes The Gate
given: {line_state: running}
when: {belt_slip: true}
expect: {line_state: faulted, gate_open: false}
within: {seconds: 1.0}
interlock: "Conveyor proven running"
"""


def test_a_sound_new_candidate_is_ready_for_review(tmp_path):
    r = review(candidate(tmp_path, GOOD), EXISTING)
    assert r.verdict == READY, r.findings
    assert all(level == "ok" for level in levels(r).values())


def test_malformed_yaml_is_rejected_at_load(tmp_path):
    r = review(candidate(tmp_path, "name: [unclosed"), EXISTING)
    assert (r.verdict, levels(r)) == (REJECTED, {"load": "error"})


def test_invented_vocabulary_is_rejected_before_anything_runs(tmp_path):
    r = review(candidate(tmp_path, GOOD.replace("belt_slip", "belt_snap").replace("gate_open", "gate_ajar")), EXISTING)
    assert r.verdict == REJECTED
    assert "when.belt_snap" in r.findings[-1].message and "expect.gate_ajar" in r.findings[-1].message
    assert "built-in" not in levels(r)  # never executed


def test_an_unknown_interlock_row_is_rejected(tmp_path):
    r = review(candidate(tmp_path, GOOD.replace("Conveyor proven running", "Belt feelings")), EXISTING)
    assert levels(r)["interlock"] == "error"


def test_a_vacuous_candidate_is_rejected(tmp_path):
    """Expectations that already hold without the stimulus: 'the line is
    idle' is true whether or not start was refused -- or pressed at all."""
    text = """
name: Start Refused At High-High (vacuous)
given: {hopper_level_pct: 97.5}
when: {start: true}
expect: {line_state: idle}
within: {seconds: 0.5}
interlock: "Hopper not high-high"
"""
    r = review(candidate(tmp_path, text), EXISTING)
    assert (r.verdict, levels(r)["vacuous"]) == (REJECTED, "error")


def test_a_failing_candidate_needs_judgment_not_rejection(tmp_path):
    """It might be a wrong test -- or the controller might be wrong. Only an
    engineer can say, so the gate refuses to decide."""
    r = review(candidate(tmp_path, GOOD.replace("line_state: faulted", "line_state: running")), EXISTING)
    assert (r.verdict, levels(r)["built-in"]) == (NEEDS_JUDGMENT, "judgment")
    assert levels(r)["determinism"] == "ok" and levels(r)["external"] == "ok"


def test_a_brittle_margin_is_flagged(tmp_path):
    r = review(candidate(tmp_path, GOOD.replace("seconds: 1.0", "seconds: 0.2")), EXISTING)
    assert r.verdict == READY
    assert levels(r)["margin"] == "warning"


def test_a_copy_of_an_existing_scenario_is_flagged_as_a_duplicate(tmp_path):
    original = SCENARIOS_DIR / "safety" / "estop_from_running.yaml"
    r = review(candidate(tmp_path, original.read_text(encoding="utf-8").replace("Conveyor Emergency Stop", "Copy")), EXISTING)
    assert levels(r)["duplicate"] == "warning"


def test_no_existing_scenario_is_vacuous():
    """The gate's first run over the suite found four start-blocked
    scenarios that still passed with `start` removed -- they couldn't tell a
    refused start from no start. Fixed by the StartInhibit observable
    (start_inhibit in the vocabulary); this keeps the whole suite honest."""
    flagged = sorted(
        s.path.name for s in EXISTING
        if {"vacuous", "stages"} & {
            f.check for f in review(s.path, [o for o in EXISTING if o.path != s.path]).findings if f.level == "error"
        }
    )
    assert flagged == []


def test_a_later_stage_whose_stimulus_changes_nothing_is_rejected(tmp_path):
    """The first-stage checks can't see this: stage 2 acknowledges, but a
    faulted line is still faulted without it, so the stage tests nothing."""
    text = """
name: Belt Slip Trips, Then An Acknowledge That Proves Nothing
given: {line_state: running}
when: {belt_slip: true}
trigger: belt_slip
expect: {line_state: faulted}
within: {seconds: 1.0}
then:
  - when: {acknowledge: true}
    expect: {line_state: faulted}
    within: {seconds: 0.5}
interlock: "Conveyor proven running"
"""
    r = review(candidate(tmp_path, text), EXISTING)
    assert (r.verdict, levels(r)["stages"]) == (REJECTED, "error")
    assert levels(r)["vacuous"] == "ok" and levels(r)["trigger"] == "ok"  # the first stage is sound
    assert "stage 2 (acknowledge)" in next(f.message for f in r.findings if f.check == "stages")


def test_a_multi_stage_scenario_whose_every_stage_matters_passes_the_stages_check(tmp_path):
    original = SCENARIOS_DIR / "faults" / "feeder_jam_recovery.yaml"
    r = review(candidate(tmp_path, original.read_text(encoding="utf-8")), EXISTING)
    assert levels(r)["stages"] == "ok"


def test_report_is_deterministic_and_relative(tmp_path):
    p = candidate(tmp_path, GOOD)
    a = render_markdown([review(p, EXISTING)], root=tmp_path)
    b = render_markdown([review(p, EXISTING)], root=tmp_path)
    assert a == b
    assert "`candidate.yaml`" in a and str(tmp_path) not in a
    assert "1 ready for review" in a
