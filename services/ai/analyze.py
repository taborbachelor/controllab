"""AI run analysis (docs/CONTROL-LAB.md §10, Phase 8 step 3): given a
scenario and its recorded result, a model proposes *hypotheses* about why
it failed, for an engineer to verify.

What it consumes is a bounded, structured digest -- never the complete
telemetry history:

- the scenario definition (every stage, and its declared trigger) and the
  outcome: pass/fail, detail, timing, and -- structured, not parsed from
  text -- the failing stage, each expectation still unmet as expected vs
  actual, and the **first divergence**: the earliest point the run is
  KNOWN to depart from the scenario (a stage's deadline passing, or an
  invariant tripping), with the explicit caveat that the cause may lie
  earlier, which is what the model is asked to look for;
- the events nearest the failure point (at most MAX_ANALYSIS_EVENTS);
- only the discrete tag *transitions* inside a window around the failure
  (at most MAX_TAG_CHANGES), with each analog tag summarized as
  start/end/min/max -- not every tag on every tick;
- and, if all that serializes past MAX_ANALYSIS_INPUT_CHARS, the oldest
  items are dropped first. Every omission is counted *in the digest
  itself*, so the model is told it is looking at a window, not the run.

What it produces is validated before anything is written (a malformed
answer is rejected, and no file appears), and advisory and labelled that
way regardless of what the model writes: a summary, the first divergence
it can see in the evidence, hypotheses, recommended investigation steps,
and an overall confidence with its uncertainty stated; every hypothesis carries a confidence, the evidence for
it, the evidence against or missing, and a check that would confirm or
rule it out, and the renderer stamps each one "unverified". The output
schema makes "the test itself may be wrong" a first-class answer. It
writes one Markdown file and nothing else -- it never changes controller
behavior, never edits a scenario, and never re-runs anything on its own
(the run it analyzes was produced by the deterministic runner first).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from services.ai.limits import (
    ANALYSIS_WINDOW_S,
    MAX_ANALYSIS_EVENTS,
    MAX_ANALYSIS_INPUT_CHARS,
    MAX_ANALYSIS_OUTPUT_TOKENS,
    MAX_TAG_CHANGES,
)
from services.ai.provider import Provider, ProviderError
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
    "controller. `outcome.first_divergence` is where the run is known to have departed from the scenario; look in "
    "the events and tag changes for the EARLIEST sign of the departure, which may come before it, and report it as "
    "first_observed_divergence (null t if the digest doesn't show one). Recommend concrete investigation steps, most "
    "useful first. State your overall confidence and what would change it. Never claim a cause is proven: the digest "
    "can support hypotheses only. You cannot change anything and must not suggest that anything be changed "
    "automatically; your output is read by an engineer."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "two or three sentences on what the digest shows"},
        "first_observed_divergence": {
            "type": "object",
            "properties": {
                "t": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                "description": {"type": "string", "description": "what departs from the scenario there, citing the digest"},
            },
            "required": ["t", "description"],
            "additionalProperties": False,
        },
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
        "recommended_investigation": {"type": "array", "items": {"type": "string"},
                                      "description": "concrete steps for the engineer, most useful first"},
        "overall_confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "uncertainty": {"type": "string", "description": "what the digest can't show, and what would change the picture"},
    },
    "required": ["summary", "first_observed_divergence", "hypotheses", "recommended_investigation",
                 "overall_confidence", "uncertainty"],
    "additionalProperties": False,
}

_HYPOTHESIS_KEYS = {"cause": str, "kind": str, "confidence": str, "supporting_evidence": list,
                    "contradicting_or_missing_evidence": list, "check_to_confirm": str}
_KINDS = {"controller", "plant_or_fault_injection", "scenario_expectation", "timing_limit", "other"}
_LEVELS = {"low", "medium", "high"}
_CERTAINTY = re.compile(r"\b(proven|proves|definitely|certainly|confirmed|undoubtedly|root cause is)\b", re.I)


def validate_analysis(data: object) -> str | None:
    """Why the model's answer is unusable, or None. Checked in code, not
    trusted to the schema the provider was given."""
    if not isinstance(data, dict):
        return "not an object"
    missing = [k for k in SCHEMA["required"] if k not in data]
    if missing:
        return f"missing {', '.join(missing)}"
    if not isinstance(data["summary"], str) or not data["summary"].strip():
        return "summary must be non-empty text"
    d = data["first_observed_divergence"]
    if not isinstance(d, dict) or "description" not in d or not isinstance(d.get("t"), (int, float, type(None))) \
            or isinstance(d.get("t"), bool):
        return "first_observed_divergence must be {t: number or null, description}"
    if not isinstance(data["hypotheses"], list) or not data["hypotheses"]:
        return "at least one hypothesis is required"
    for i, h in enumerate(data["hypotheses"], 1):
        if not isinstance(h, dict) or any(not isinstance(h.get(k), t) for k, t in _HYPOTHESIS_KEYS.items()):
            return f"hypothesis {i} is missing a field or has one of the wrong type"
        if h["kind"] not in _KINDS or h["confidence"] not in _LEVELS:
            return f"hypothesis {i} has an unknown kind or confidence"
    if not isinstance(data["recommended_investigation"], list) or not all(
            isinstance(x, str) for x in data["recommended_investigation"]):
        return "recommended_investigation must be a list of text"
    if data["overall_confidence"] not in _LEVELS:
        return "overall_confidence must be low, medium, or high"
    return None


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

    kind = ("invariant violated" if "invariant violated" in result.detail
            else "not observable" if result.not_observable
            else "expectations unmet by the deadline" if result.unmet else "other")
    digest = {
        "scenario": {
            "name": scenario.name, "given": scenario.given, "when": scenario.when, "expect": scenario.expect,
            "within_s": scenario.within_s, "interlock": scenario.interlock, "trigger": list(scenario.trigger),
            "then": [{"when": st.when, "expect": st.expect, "within_s": st.within_s} for st in scenario.then],
        },
        "outcome": {
            "passed": result.passed, "detail": result.detail, "response_time_s": result.elapsed_s,
            "when_applied_t": result.when_applied_t, "run_ended_t": t_end,
            "stages_passed": len(result.stage_elapsed),
            "failed_stage": result.failed_stage,
            "expected_vs_actual": result.unmet,
            "first_divergence": {
                "t": t_end, "stage": result.failed_stage, "stage_when_applied_t": result.failed_stage_applied_t,
                "kind": kind, "unmet": result.unmet,
                "note": "the earliest point the run is KNOWN to depart from the scenario; the cause may be earlier",
            },
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
        f"**Where the run departed from the scenario (deterministic, from the runner):** "
        f"t = {o['first_divergence']['t']:.2f} s, stage {o['first_divergence']['stage'] or '—'}, "
        f"{o['first_divergence']['kind']}"
        + (f"; expected vs actual: {_expected_vs_actual(o['expected_vs_actual'])}" if o["expected_vs_actual"] else "")
        + ".",
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
        f"*Model's overall confidence: {analysis.get('overall_confidence', '?')}.* {analysis.get('uncertainty', '')}".rstrip(),
        "",
        "## First observed divergence (model's reading of the evidence)",
        "",
        _divergence(analysis.get("first_observed_divergence") or {}),
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
            *(["> ⚠️ The model's wording claims certainty. The digest can only support a hypothesis; treat it as one.", ""]
              if _CERTAINTY.search(str(h.get("cause", ""))) else []),
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
    steps = analysis.get("recommended_investigation") or []
    lines += ["## Recommended investigation", ""]
    lines += [f"{i}. {s}" for i, s in enumerate(steps, 1)] or ["*None offered.*"]
    lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _expected_vs_actual(unmet: dict) -> str:
    return "; ".join(f"`{k}` expected {v.get('expected')!r}, was {v.get('actual')!r}" for k, v in unmet.items())


def _divergence(d: dict) -> str:
    t = d.get("t")
    where = f"t = {t:.2f} s" if isinstance(t, (int, float)) else "no specific time in the digest"
    return f"{where}: {d.get('description', '')}"


def analyze_run(provider: Provider, scenario: Scenario, result: ScenarioResult, out_path: Path) -> Path:
    """Send the bounded digest, write the analysis to `out_path`, return it.
    The only side effect is that one file."""
    if result.passed:
        raise ValueError("nothing to analyze: the run passed")
    digest = build_digest(scenario, result)
    completion = provider.complete_json(
        system=SYSTEM,
        user="Digest of the run (JSON):\n" + json.dumps(digest, default=str),
        schema=SCHEMA,
        max_tokens=MAX_ANALYSIS_OUTPUT_TOKENS,
    )
    problem = validate_analysis(completion.data)
    if problem is not None:
        raise ProviderError(f"the model's analysis was malformed and was not written: {problem}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_markdown(scenario, digest, completion.data, f"{provider.name} / {completion.model}"),
                        encoding="utf-8")
    return out_path
