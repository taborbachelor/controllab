"""AI run analysis (Phase 8 step 3) against a fake provider -- no model,
no network. Under test: what is sent (bounded, structured, a window --
never the full history), what comes back (always labelled as unverified
hypotheses), and that nothing else changes."""
import json
from pathlib import Path

import pytest

from services.ai import analyze
from services.ai.analyze import SCHEMA, analyze_run, build_digest
from services.ai.limits import MAX_ANALYSIS_EVENTS, MAX_ANALYSIS_INPUT_CHARS, MAX_ANALYSIS_OUTPUT_TOKENS, MAX_TAG_CHANGES
from services.ai.provider import Completion
from services.telemetry.events import Event
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario

SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"

FAILING = """
name: Stop Keeps Feeding (wrong on purpose)
given: {line_state: running}
when: {stop: true}
expect: {feeder_running: true, line_state: stopping}
within: {seconds: 1.0}
"""

ANSWER = {
    "summary": "The feeder stopped on the stop command, as the upstream-first sequence requires.",
    "hypotheses": [{
        "cause": "The scenario expects the feeder to keep running during a stop, which contradicts the sequence.",
        "kind": "scenario_expectation", "confidence": "high",
        "supporting_evidence": ["t=1.7: command stop; M-103.RUN 1 -> 0 on the same tick"],
        "contradicting_or_missing_evidence": ["no evidence the controller mis-sequenced"],
        "check_to_confirm": "compare with scenarios/shutdown/normal_stop.yaml",
    }],
}


class FakeProvider:
    name = "fake"

    def __init__(self, answer=ANSWER):
        self.answer, self.calls = answer, []

    def complete_json(self, *, system, user, schema, max_tokens):
        self.calls.append({"system": system, "user": user, "schema": schema, "max_tokens": max_tokens})
        return Completion(data=self.answer, model="fake-model", input_tokens=1, output_tokens=2)


@pytest.fixture
def failed(tmp_path):
    p = tmp_path / "failing.yaml"
    p.write_text(FAILING, encoding="utf-8")
    scenario = Scenario.load(p)
    result = run_scenario(scenario)
    assert not result.passed
    return scenario, result


def test_digest_is_a_window_of_transitions_not_the_history(failed):
    scenario, result = failed
    digest = build_digest(scenario, result)
    full_history = sum(len(s.values) for s in result.tags.samples)
    assert len(digest["tag_changes_in_window"]) < full_history / 10
    assert all(c["from"] != c["to"] for c in digest["tag_changes_in_window"])  # transitions only
    assert digest["outcome"]["passed"] is False and "timed out" in digest["outcome"]["detail"]
    assert len(json.dumps(digest, default=str)) <= MAX_ANALYSIS_INPUT_CHARS


def test_long_runs_are_capped_and_the_omission_is_stated(failed, monkeypatch):
    scenario, result = failed
    result.events = [Event(t=round(i * 0.01, 3), type="state_changed", data={"from": "a", "to": "b", "fault_reason": "x" * 50})
                     for i in range(500)]
    digest = build_digest(scenario, result)
    assert len(digest["events"]) <= MAX_ANALYSIS_EVENTS
    assert digest["omitted"]["events"] >= 500 - MAX_ANALYSIS_EVENTS
    assert len(digest["tag_changes_in_window"]) <= MAX_TAG_CHANGES

    monkeypatch.setattr(analyze, "MAX_ANALYSIS_INPUT_CHARS", 3_000)
    small = build_digest(scenario, result)
    assert len(json.dumps(small, default=str)) <= 3_000
    assert small["omitted"]["events"] > digest["omitted"]["events"]  # shrunk further, and said so


def test_request_is_bounded_and_asks_for_hypotheses(failed, tmp_path):
    scenario, result = failed
    provider = FakeProvider()
    analyze_run(provider, scenario, result, tmp_path / "a.md")
    call = provider.calls[0]
    assert call["max_tokens"] == MAX_ANALYSIS_OUTPUT_TOKENS and call["schema"] == SCHEMA
    assert "Produce hypotheses, not conclusions" in call["system"]
    assert "Never claim a cause is proven" in call["system"]
    assert len(call["user"]) <= MAX_ANALYSIS_INPUT_CHARS + 100
    kinds = SCHEMA["properties"]["hypotheses"]["items"]["properties"]["kind"]["enum"]
    assert "scenario_expectation" in kinds  # "the test is wrong" is a first-class answer


def test_output_is_labelled_unverified_whatever_the_model_says(failed, tmp_path):
    scenario, result = failed
    overconfident = {**ANSWER, "hypotheses": [{**ANSWER["hypotheses"][0], "cause": "PROVEN: the controller is broken"}]}
    text = analyze_run(FakeProvider(overconfident), scenario, result, tmp_path / "a.md").read_text(encoding="utf-8")
    assert "Hypotheses for an engineer to verify — not conclusions" in text
    assert "nothing was changed" in text
    assert "*Unverified hypothesis" in text
    assert "not the full telemetry" in text


def test_analysis_changes_nothing_but_its_own_file(failed, tmp_path):
    scenario, result = failed
    before = {p: p.read_bytes() for p in SCENARIOS.rglob("*.yaml")}
    source_before = scenario.path.read_bytes()
    out = analyze_run(FakeProvider(), scenario, result, tmp_path / "out" / "a.md")
    assert {p: p.read_bytes() for p in SCENARIOS.rglob("*.yaml")} == before
    assert scenario.path.read_bytes() == source_before
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == ["a.md", "failing.yaml"]
    assert out.exists()


def test_analog_drift_is_summarized_not_listed_tick_by_tick(failed):
    """A level drifting every scan would crowd discrete transitions out of
    the cap; analogs get one start/end/min/max line each instead."""
    scenario, result = failed
    digest = build_digest(scenario, result)
    assert all(isinstance(c["to"], bool) for c in digest["tag_changes_in_window"])
    assert set(digest["analog_in_window"]) == {"LT-101", "SC-103", "WT-105"}
    assert set(digest["analog_in_window"]["LT-101"]) == {"start", "end", "min", "max"}
    stop = [c for c in digest["tag_changes_in_window"] if c["tag"] == "M-103.RUN" and c["to"] is False]
    assert stop, "the discrete transition that explains this failure must survive"
