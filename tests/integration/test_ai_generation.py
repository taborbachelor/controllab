"""AI candidate generation (Phase 8 step 2b) against a fake provider --
no model, no network. What's under test is everything around the model:
the bounded context, the request sent, the limits, where files go, and
that every candidate goes through the review gate and nothing reaches
scenarios/ on its own."""
import json
from pathlib import Path

import pytest

from services.ai.context import VALUE_SHAPES, build_context
from services.ai.generate import generate_candidates, output_schema
from services.ai.limits import MAX_CONTEXT_CHARS, MAX_GENERATION_OUTPUT_TOKENS, MAX_SCENARIOS_PER_REQUEST
from services.ai.provider import Completion
from services.simulation.engine.plant_io import build_line_io_image
from services.testing.candidates import NEEDS_JUDGMENT, READY, REJECTED
from services.testing.report import INTERLOCKS
from services.testing.scenario import Scenario
from services.testing.vocabulary import APPLY_ACTIONS, READ_FIELDS

SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"


def entries(**kv):
    return [{"key": k, "value": json.dumps(v)} for k, v in kv.items()]


GOOD = {
    "name": "Belt Slip Closes The Gate", "rationale": "Motion loss mid-run must stop feeding.",
    "given": entries(line_state="running"), "when": entries(belt_slip=True),
    "expect": entries(line_state="faulted", gate_open=False), "within_seconds": 1.0,
    "interlock": "Conveyor proven running",
}
VACUOUS = {
    "name": "Idle Stays Idle", "rationale": "Nothing happens.",
    "given": entries(bin_level_pct=5.0), "when": entries(start=True),
    "expect": entries(line_state="idle"), "within_seconds": 0.5, "interlock": "Bin not low",
}
WRONG = {**GOOD, "name": "Stop Keeps Feeding", "when": entries(stop=True),
         "expect": entries(feeder_running=True, line_state="stopping"), "interlock": None}


class FakeProvider:
    name = "fake"

    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = []

    def complete_json(self, *, system, user, schema, max_tokens):
        self.calls.append({"system": system, "user": user, "schema": schema, "max_tokens": max_tokens})
        return Completion(data={"candidates": self.candidates}, model="fake-model", input_tokens=1, output_tokens=2)


# ---- context -----------------------------------------------------------------------

def test_value_shapes_cover_exactly_the_vocabulary():
    assert set(VALUE_SHAPES) == set(APPLY_ACTIONS) | set(READ_FIELDS)


def test_context_describes_the_real_line_and_stays_bounded():
    context = build_context(SCENARIOS)
    assert len(context) <= MAX_CONTEXT_CHARS
    assert context == build_context(SCENARIOS)  # deterministic
    for tag in build_line_io_image().names():
        assert tag in context
    for row in INTERLOCKS:
        assert row.name in context
    for s in Scenario.discover(SCENARIOS):
        assert s.name in context  # existing scenarios, so the model can avoid duplicates


def test_schema_only_lets_the_model_name_real_vocabulary_keys():
    item = output_schema()["properties"]["candidates"]["items"]["properties"]
    assert set(item["when"]["items"]["properties"]["key"]["enum"]) == set(APPLY_ACTIONS)
    assert set(item["expect"]["items"]["properties"]["key"]["enum"]) == set(READ_FIELDS)
    assert set(item["given"]["items"]["properties"]["key"]["enum"]) == set(APPLY_ACTIONS) | {"line_state"}


# ---- generation --------------------------------------------------------------------

def test_every_candidate_is_written_as_a_proposal_and_reviewed(tmp_path):
    before = sorted(p for p in SCENARIOS.rglob("*.yaml"))
    provider = FakeProvider([GOOD, VACUOUS, WRONG])
    result = generate_candidates(provider, "cover belt and stop behavior", 3, tmp_path / "cand", SCENARIOS)

    assert [r.verdict for r in result.reviews] == [READY, REJECTED, NEEDS_JUDGMENT]
    for f in result.files:
        text = f.read_text(encoding="utf-8")
        assert text.startswith("# AI-GENERATED CANDIDATE -- a proposal, not a test (fake / fake-model).")
        assert tmp_path in f.parents
    assert "READY FOR REVIEW" in result.report.read_text(encoding="utf-8")
    assert sorted(p for p in SCENARIOS.rglob("*.yaml")) == before  # nothing reached scenarios/


def test_the_request_is_bounded(tmp_path):
    provider = FakeProvider([GOOD])
    generate_candidates(provider, "belt slip", 1, tmp_path, SCENARIOS)
    call = provider.calls[0]
    assert call["max_tokens"] == MAX_GENERATION_OUTPUT_TOKENS
    assert call["system"] == build_context(SCENARIOS)
    assert "exactly 1 new candidate" in call["user"] and "belt slip" in call["user"]


@pytest.mark.parametrize("count", [0, MAX_SCENARIOS_PER_REQUEST + 1])
def test_count_outside_the_limit_is_refused_before_any_call(tmp_path, count):
    provider = FakeProvider([GOOD])
    with pytest.raises(ValueError, match="count must be"):
        generate_candidates(provider, "x", count, tmp_path, SCENARIOS)
    assert provider.calls == []


def test_an_oversized_request_is_refused_before_any_call(tmp_path):
    provider = FakeProvider([GOOD])
    with pytest.raises(ValueError, match="limit"):
        generate_candidates(provider, "x" * 5000, 1, tmp_path, SCENARIOS)
    assert provider.calls == []


def test_extra_candidates_from_the_model_are_dropped_and_noted(tmp_path):
    result = generate_candidates(FakeProvider([GOOD, WRONG, GOOD]), "x", 1, tmp_path, SCENARIOS)
    assert len(result.files) == 1
    assert "only the first 1 were kept" in result.notes[0]


def test_it_refuses_to_write_into_scenarios(tmp_path):
    provider = FakeProvider([GOOD])
    with pytest.raises(ValueError, match="outside scenarios"):
        generate_candidates(provider, "x", 1, SCENARIOS / "ai", SCENARIOS)
    assert provider.calls == []


def test_earlier_proposals_are_never_overwritten(tmp_path):
    generate_candidates(FakeProvider([GOOD]), "x", 1, tmp_path, SCENARIOS)
    generate_candidates(FakeProvider([GOOD]), "x", 1, tmp_path, SCENARIOS)
    assert sorted(p.name for p in tmp_path.glob("*.yaml")) == ["belt_slip_closes_the_gate.yaml", "belt_slip_closes_the_gate_2.yaml"]


def test_a_malformed_candidate_is_skipped_not_fatal(tmp_path):
    broken = {k: v for k, v in GOOD.items() if k != "expect"}
    result = generate_candidates(FakeProvider([broken, GOOD]), "x", 2, tmp_path, SCENARIOS)
    assert len(result.files) == 1 and any("malformed" in n for n in result.notes)
