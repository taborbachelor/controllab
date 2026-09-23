"""A stand-in for a model, for running the AI flow with no API key and no
network (examples/ai_assist/run_flow.py, and nothing else).

It returns hand-written canned answers from ./canned/ -- NOT model output --
whatever it is asked. Its name and "model" say so, and both appear in the
provenance line of every candidate file and analysis it produces, so a
canned answer can never be mistaken for a real one. Everything around it
is the real pipeline: the output schema and validation, the review gate,
the deterministic runner, and the analysis validation and rendering.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.ai.provider import Completion

CANNED = Path(__file__).with_name("canned")


class ScriptedProvider:
    name = "scripted stand-in (no model)"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete_json(self, *, system: str, user: str, schema: dict, max_tokens: int) -> Completion:
        self.calls.append({"system_chars": len(system), "user_chars": len(user), "max_tokens": max_tokens})
        kind = "analysis" if "hypotheses" in schema.get("properties", {}) else "generation"
        data = json.loads((CANNED / f"{kind}.json").read_text(encoding="utf-8"))
        return Completion(data=data, model="canned response, hand-written", input_tokens=0, output_tokens=0)
