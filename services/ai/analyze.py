"""AI run analysis (docs/CONTROL-LAB.md §10, Phase 8 step 3): given a
scenario and its recorded result, a model proposes *hypotheses* about why
it failed, for an engineer to verify.

What it consumes is a bounded, structured digest -- never the complete
telemetry history:

- the scenario definition and outcome (pass/fail, detail, timing);
- the events nearest the failure point (at most MAX_ANALYSIS_EVENTS);
- only the discrete tag *transitions* inside a window around the failure
  (at most MAX_TAG_CHANGES), with each analog tag summarized as
  start/end/min/max -- not every tag on every tick;
- and, if all that serializes past MAX_ANALYSIS_INPUT_CHARS, the oldest
  items are dropped first. Every omission is counted *in the digest
  itself*, so the model is told it is looking at a window, not the run.

What it produces is advisory and labelled that way regardless of what the
model writes: every hypothesis carries a confidence, the evidence for
it, the evidence against or missing, and a check that would confirm or
rule it out, and the renderer stamps each one "unverified". The output
schema makes "the test itself may be wrong" a first-class answer. It
writes one Markdown file and nothing else -- it never changes controller
behavior, never edits a scenario, and never re-runs anything on its own
(the run it analyzes was produced by the deterministic runner first).
"""
from __future__ import annotations

import json
from pathlib import Path

from services.ai.limits import (
    ANALYSIS_WINDOW_S,
    MAX_ANALYSIS_EVENTS,
    MAX_ANALYSIS_INPUT_CHARS,
    MAX_ANALYSIS_OUTPUT_TOKENS,
    MAX_TAG_CHANGES,
)
from services.ai.provider import Provider
from services.testing.runner import ScenarioResult
from services.testing.scenario import Scenario

SYSTEM = (
    "You help a commissioning engineer understand a result from a deterministic control-system test on a simulated "
    "bulk-material line (bin -> gate -> feeder -> conveyor -> hopper). You receive a structured digest of one "
    "scenario run: its definition, its outcome, the events nearest the failure, and the tag transitions in a window "
    "around it. The digest is deliberately partial; its `omitted` fields say what was left out.\n\n"
    "Produce hypotheses, not conclusions. For each: cite evidence from the digest by time and tag or event, list "
    "what contradicts it or what evidence is missing, and give a concrete check an engineer could run to confirm or "
    "rule it out. Always consider that the scenario's own expectation or time limit may be what is wrong, not the "
    "controller. Never claim a cause is proven. You cannot change anything and must not suggest that anything be "
    "changed automatically; your output is read by an engineer."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "two or three sentences on what the digest shows"},
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cause": {"type": "string"},
                    "kind": {"type": "string", "enum": ["controller", "plant_or_fault_injection", "scenario_expectation", "timing_limit", "other"]},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "supporting_evidence": {"type": "array", "items": {"type": "string"}},
                    "contradicting_or_missing_evidence": {"type": "array", "items": {"type": "string"}},
                    "check_to_confirm": {"type": "string"},
                },
                "required": ["cause", "kind", "confidence", "supporting_evidence", "contradicting_or_missing_evidence", "check_to_confirm"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "hypotheses"],
    "additionalProperties": False,
}


def _nearest(items: list[dict], t_ref: float, limit: int) -> tuple[list[dict], int]:
    """The `limit` items closest in time to t_ref, returned in time order."""
    if len(items) <= limit:
        return items, 0
    kept = sorted(sorted(items, key=lambda x: abs(x["t"] - t_ref))[:limit], key=lambda x: x["t"])
    return kept, len(items) - limit


def build_digest(scenario: Scenario, result: ScenarioResult) -> dict:
    samples = result.tags.samples if result.tags is not None else []
    t_end = samples[-1].t if samples else 0.0
    t_fail = t_end  # a failed run stops at the failing point (timeout or invariant)
    lo, hi = t_fail - ANALYSIS_WINDOW_S, t_fail

    events = [{"t": e.t, "type": e.type, **e.data} for e in result.events]
    events, events_omitted = _nearest(events, t_fail, MAX_ANALYSIS_EVENTS)

    # Discrete tags: every transition in the window. Analog tags change on
    # nearly every tick (a level drifting 20.000 -> 19.995 -> ...), which
    # would crowd the discrete transitions -- the ones that explain a
    # sequencing failure -- out of the cap; so each analog in the window is
    # summarized instead, the way a historian applies a deadband.
    changes: list[dict] = []
    analog: dict[str, dict] = {}
    window_start: dict = {}
    previous = None
    for sample in samples:
        in_window = lo <= sample.t <= hi
        for tag, value in sample.values.items():
            if isinstance(value, bool):
                if in_window and previous is not None and previous.values.get(tag) != value:
                    changes.append({"t": sample.t, "tag": tag, "from": previous.values.get(tag), "to": value})
            elif in_window:
                a = analog.setdefault(tag, {"start": value, "end": value, "min": value, "max": value})
                a["end"], a["min"], a["max"] = value, min(a["min"], value), max(a["max"], value)
        if sample.t <= lo or not window_start:
            window_start = {"t": sample.t, "values": dict(sample.values)}
        previous = sample
    changes, changes_omitted = _nearest(changes, t_fail, MAX_TAG_CHANGES)
    analog = {t: {k: round(v, 3) for k, v in a.items()} for t, a in sorted(analog.items())}

    digest = {
        "scenario": {
            "name": scenario.name, "given": scenario.given, "when": scenario.when, "expect": scenario.expect,
            "within_s": scenario.within_s, "interlock": scenario.interlock,
        },
        "outcome": {
            "passed": result.passed, "detail": result.detail, "response_time_s": result.elapsed_s,
            "when_applied_t": result.when_applied_t, "run_ended_t": t_end,
        },
        "tag_snapshot_at_window_start": window_start,
        "events": events,
        "tag_changes_in_window": changes,
        "analog_in_window": analog,
        "omitted": {
            "events": events_omitted, "tag_changes": changes_omitted,
            "note": f"discrete tag changes only within {ANALYSIS_WINDOW_S:g} s before the run ended; analog "
                    "tags there are summarized (start/end/min/max); tags that never changed are only in the snapshot",
        },
    }
    # Hard cap on what is sent: drop the oldest items first, and say so.
    while len(json.dumps(digest, default=str)) > MAX_ANALYSIS_INPUT_CHARS:
        if len(digest["tag_changes_in_window"]) >= len(digest["events"]) and digest["tag_changes_in_window"]:
            digest["tag_changes_in_window"].pop(0)
            digest["omitted"]["tag_changes"] += 1
        elif digest["events"]:
            digest["events"].pop(0)
            digest["omitted"]["events"] += 1
        else:
            raise ValueError("the scenario definition alone exceeds the analysis input limit")
    return digest


def render_markdown(scenario: Scenario, digest: dict, analysis: dict, provenance: str) -> str:
    o = digest["outcome"]
    lines = [
        f"# AI analysis — {scenario.name}",
        "",
        f"> **AI-generated ({provenance}). Hypotheses for an engineer to verify — not conclusions.** "
        "No cause below has been proven, and nothing was changed: no controller behavior, no scenario, no re-run.",
        "",
        f"**Run:** {'PASS' if o['passed'] else 'FAIL'} — {o['detail']}",
        "",
        f"**What the model saw:** the scenario definition, {len(digest['events'])} event(s) and "
        f"{len(digest['tag_changes_in_window'])} tag change(s) nearest the end of the run "
        f"({digest['omitted']['events']} event(s) and {digest['omitted']['tag_changes']} tag change(s) omitted), "
        "not the full telemetry.",
        "",
        "## Summary",
        "",
        str(analysis.get("summary", "")).strip(),
        "",
        "## Hypotheses",
        "",
    ]
    for i, h in enumerate(analysis.get("hypotheses", []), 1):
        lines += [
            f"### {i}. {h.get('cause', '')}",
            "",
            f"*Unverified hypothesis — kind: {h.get('kind', '?')}, model confidence: {h.get('confidence', '?')}.*",
            "",
            "**Supporting evidence**",
            *[f"- {x}" for x in h.get("supporting_evidence", [])],
            "",
            "**Against, or missing**",
            *[f"- {x}" for x in h.get("contradicting_or_missing_evidence", [])],
            "",
            f"**Check to confirm or rule out:** {h.get('check_to_confirm', '')}",
            "",
        ]
    if not analysis.get("hypotheses"):
        lines += ["*The model offered no hypotheses.*", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def analyze_run(provider: Provider, scenario: Scenario, result: ScenarioResult, out_path: Path) -> Path:
    """Send the bounded digest, write the analysis to `out_path`, return it.
    The only side effect is that one file."""
    digest = build_digest(scenario, result)
    completion = provider.complete_json(
        system=SYSTEM,
        user="Digest of the run (JSON):\n" + json.dumps(digest, default=str),
        schema=SCHEMA,
        max_tokens=MAX_ANALYSIS_OUTPUT_TOKENS,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_markdown(scenario, digest, completion.data, f"{provider.name} / {completion.model}"),
                        encoding="utf-8")
    return out_path
