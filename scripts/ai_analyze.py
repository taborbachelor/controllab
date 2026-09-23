#!/usr/bin/env python
"""Ask a model for hypotheses about why a scenario failed (docs/CONTROL-LAB.md
§10, Phase 8). Optional -- needs `pip install -e ".[ai]"` and ANTHROPIC_API_KEY.

    python scripts/ai_analyze.py candidates/stop_keeps_feeding.yaml
    python scripts/ai_analyze.py scenarios/faults/gate_travel_timeout.yaml --external

The scenario is first run by the deterministic runner, exactly as the
suite runs it; only a failing run is analyzed. The model sees a bounded
digest of that run (not the full telemetry) and its answer is written to
--out as hypotheses for an engineer. Nothing is changed: no controller
behavior, no scenario file, no re-run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from services.ai import AIUnavailable, ProviderError, get_provider
from services.ai.analyze import analyze_run
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario, ScenarioLoadError

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", type=Path)
    ap.add_argument("--external", action="store_true", help="run against the reference external controller over Modbus")
    ap.add_argument("--out", type=Path, default=None, help="default: analyses/<scenario>.md")
    ap.add_argument("--provider", default="anthropic")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")

    try:
        scenario = Scenario.load(args.scenario)
        result = run_scenario(scenario, external=args.external)
    except ScenarioLoadError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if result.passed:
        print(f"PASS -- {scenario.name} passed in {result.elapsed_s:.2f} s; there is no failure to analyze.")
        return 0
    print(f"FAIL -- {result.detail}")

    out = args.out or REPO_ROOT / "analyses" / f"{args.scenario.stem}.md"
    provider = get_provider(args.provider, **({"model": args.model} if args.model else {}))
    try:
        analyze_run(provider, scenario, result, out)
    except (AIUnavailable, ProviderError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"Analysis (hypotheses, unverified): {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
