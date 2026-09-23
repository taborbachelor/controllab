#!/usr/bin/env python
"""Ask a model to propose candidate scenarios (docs/CONTROL-LAB.md §10,
Phase 8). Optional -- needs `pip install -e ".[ai]"` and ANTHROPIC_API_KEY.

    python scripts/ai_generate.py "cover gate faults during shutdown" --count 3

Flow: AI proposal -> deterministic review gate -> engineer approval ->
deterministic execution. This script does the first two: candidates land
in --out (default candidates/, outside scenarios/) with REVIEW.md beside
them. To accept one, an engineer reads it and moves it into scenarios/;
nothing here does that.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from services.ai import AIUnavailable, ProviderError, get_provider
from services.ai.generate import generate_candidates
from services.ai.limits import MAX_SCENARIOS_PER_REQUEST
from services.testing.candidates import REJECTED

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("request", help="what the candidates should test, in plain words")
    ap.add_argument("--count", type=int, default=3, help=f"1-{MAX_SCENARIOS_PER_REQUEST}")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "candidates")
    ap.add_argument("--provider", default="anthropic")
    ap.add_argument("--model", default=None, help="override the provider's default model")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")

    provider = get_provider(args.provider, **({"model": args.model} if args.model else {}))
    try:
        result = generate_candidates(provider, args.request, args.count, args.out, REPO_ROOT / "scenarios")
    except (AIUnavailable, ProviderError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"{len(result.files)} candidate(s) from {result.model} "
          f"({result.input_tokens} input / {result.output_tokens} output tokens):")
    for f, r in zip(result.files, result.reviews):
        print(f"  {r.verdict:17} {f}")
    for n in result.notes:
        print(f"  note: {n}")
    print(f"Review: {result.report}\nNothing was added to scenarios/ -- accepting a candidate is an engineer's decision.")
    return 1 if any(r.verdict == REJECTED for r in result.reviews) else 0


if __name__ == "__main__":
    raise SystemExit(main())
