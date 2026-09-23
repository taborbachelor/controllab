"""AI candidate-scenario generation (docs/CONTROL-LAB.md §10, Phase 8
step 2b). The flow is fixed and has no shortcut:

    AI proposal -> deterministic review gate -> engineer approval -> deterministic execution

generate_candidates() does the first two and stops. The model returns
structured JSON (never code, never commands); each candidate is written
as a YAML file under a candidates directory, marked as a proposal; and
the review gate (services/testing/candidates.py) runs on every one of
them in the same call, with its report written alongside. It refuses to
write anywhere inside scenarios/, and nothing here ever moves a file
there -- that's the engineer's approval step, and the only way a
candidate becomes a test.

The output schema makes each given/when/expect entry a {key, value} pair
whose `key` is an enum of the real vocabulary, so the model can't even
express an invented key; values travel as JSON text and are parsed here.
The request text and the candidate count are validated before any call,
and the count is enforced on the answer too -- limits are code, not
instructions (services/ai/limits.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from services.ai.context import build_context
from services.ai.limits import MAX_GENERATION_OUTPUT_TOKENS, MAX_REQUEST_CHARS, MAX_SCENARIOS_PER_REQUEST
from services.ai.provider import Provider
from services.testing.candidates import Review, render_markdown, review
from services.testing.scenario import Scenario
from services.testing.vocabulary import APPLY_ACTIONS, READ_FIELDS


def _entries(keys: list[str]) -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "enum": sorted(keys)},
                "value": {"type": "string", "description": "the value as JSON text, e.g. true, 5.0, \"tripped\", [\"BIN_LOW\"]"},
            },
            "required": ["key", "value"],
            "additionalProperties": False,
        },
    }


def output_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "rationale": {"type": "string", "description": "what behavior this tests and why it matters"},
                        "given": _entries(sorted(APPLY_ACTIONS) + ["line_state"]),
                        "when": _entries(sorted(APPLY_ACTIONS)),
                        "expect": _entries(sorted(READ_FIELDS)),
                        "within_seconds": {"type": "number"},
                        "interlock": {"anyOf": [{"type": "string"}, {"type": "null"}],
                                      "description": "the section 6.3 row name it covers, or null"},
                    },
                    "required": ["name", "rationale", "given", "when", "expect", "within_seconds", "interlock"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["candidates"],
        "additionalProperties": False,
    }


@dataclass
class GenerationResult:
    files: list[Path]
    reviews: list[Review]
    report: Path
    notes: list[str] = field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def _value(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text  # left for the review gate to judge


def _mapping(entries: list[dict]) -> dict:
    return {e["key"]: _value(e["value"]) for e in entries}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60] or "candidate"


def to_yaml(candidate: dict, provenance: str) -> str:
    """One candidate as a scenario file, headed as a proposal."""
    doc = {"name": candidate["name"], "given": _mapping(candidate["given"]), "when": _mapping(candidate["when"]),
           "expect": _mapping(candidate["expect"]), "within": {"seconds": candidate["within_seconds"]}}
    if candidate.get("interlock"):
        doc["interlock"] = candidate["interlock"]
    rationale = " ".join(str(candidate.get("rationale", "")).split())
    header = (
        f"# AI-GENERATED CANDIDATE -- a proposal, not a test ({provenance}).\n"
        "# Reviewed by scripts/review_candidates.py; it becomes a test only when an\n"
        "# engineer moves it into scenarios/.\n"
        f"# Rationale: {rationale}\n"
    )
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def generate_candidates(
    provider: Provider, request: str, count: int, out_dir: Path, scenarios_dir: Path
) -> GenerationResult:
    request = request.strip()
    if not request:
        raise ValueError("describe what the candidates should test")
    if len(request) > MAX_REQUEST_CHARS:
        raise ValueError(f"request is {len(request)} chars; the limit is {MAX_REQUEST_CHARS}")
    if not 1 <= count <= MAX_SCENARIOS_PER_REQUEST:
        raise ValueError(f"count must be 1-{MAX_SCENARIOS_PER_REQUEST}")
    out_dir = out_dir.resolve()
    scenarios_dir = scenarios_dir.resolve()
    if out_dir == scenarios_dir or scenarios_dir in out_dir.parents:
        raise ValueError("candidates must be written outside scenarios/ -- only an engineer moves one in")

    system = build_context(scenarios_dir)
    user = (
        f"Propose exactly {count} new candidate scenario(s) for this request from a commissioning engineer:\n\n"
        f"{request}\n\nEach must follow the rules above. Put each value as JSON text in `value`."
    )
    completion = provider.complete_json(
        system=system, user=user, schema=output_schema(), max_tokens=MAX_GENERATION_OUTPUT_TOKENS
    )
    candidates = completion.data.get("candidates", []) if isinstance(completion.data, dict) else []
    notes = []
    if len(candidates) > count:
        notes.append(f"the model returned {len(candidates)} candidates; only the first {count} were kept")
        candidates = candidates[:count]
    if len(candidates) < count:
        notes.append(f"the model returned {len(candidates)} of the {count} candidates requested")

    out_dir.mkdir(parents=True, exist_ok=True)
    provenance = f"{provider.name} / {completion.model}"
    files: list[Path] = []
    for candidate in candidates:
        path = out_dir / f"{_slug(str(candidate.get('name', '')))}.yaml"
        n = 2
        while path.exists():  # never overwrite an earlier proposal
            path = out_dir / f"{_slug(str(candidate.get('name', '')))}_{n}.yaml"
            n += 1
        try:
            path.write_text(to_yaml(candidate, provenance), encoding="utf-8")
        except (KeyError, TypeError) as e:
            notes.append(f"a candidate was malformed and skipped: {e!r}")
            continue
        files.append(path)

    # The gate is not optional: every written candidate is reviewed here.
    existing = Scenario.discover(scenarios_dir)
    reviews = [review(f, existing) for f in files]
    report = out_dir / "REVIEW.md"
    text = render_markdown(reviews, root=out_dir)
    if notes:
        text += "\n## Generation notes\n\n" + "".join(f"- {n}\n" for n in notes)
    report.write_text(text, encoding="utf-8")
    return GenerationResult(files, reviews, report, notes, completion.model, completion.input_tokens, completion.output_tokens)
