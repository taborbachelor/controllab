#!/usr/bin/env python
"""The whole AI engineering-assistance loop, end to end (docs/AI.md):

    engineer request -> AI proposal -> schema validation -> review gate
      -> engineer approval -> deterministic execution -> AI run analysis -> engineer

    python examples/ai_assist/run_flow.py                  # scripted stand-in: no key, no network
    python examples/ai_assist/run_flow.py --live           # Claude (pip install -e ".[ai]", ANTHROPIC_API_KEY)
    python examples/ai_assist/run_flow.py --approve NAME   # approve a candidate by (part of) its file name

Nothing here touches scenarios/, the controller, or the plant's logic:
candidates and analyses are written under --out, and "approval" is the
engineer naming a candidate on the command line -- the only way one gets
executed. The default stand-in returns hand-written canned answers (not
model output; see scripted_provider.py) so the flow can be run and tested
anywhere; every file it writes says so in its provenance line.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from services.ai import AIUnavailable, ProviderError, get_provider  # noqa: E402
from services.ai.analyze import analyze_run  # noqa: E402
from services.ai.generate import generate_candidates  # noqa: E402
from services.testing.candidates import NEEDS_JUDGMENT, READY  # noqa: E402
from services.testing.runner import run_scenario  # noqa: E402
from services.testing.scenario import Scenario  # noqa: E402

REQUEST = "Cover feeder jams and hopper weight transmitter failures that the existing scenarios don't."


def main(argv: list[str] | None = None, out: Path | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="use the Anthropic provider instead of the scripted stand-in")
    ap.add_argument("--request", default=REQUEST)
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--out", type=Path, default=out or REPO / "candidates" / "ai_assist_example")
    ap.add_argument("--approve", action="append", default=[], metavar="NAME",
                    help="the engineer's approval: execute the candidate whose file name contains NAME")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    if args.live:
        provider = get_provider("anthropic")
    else:
        from scripted_provider import ScriptedProvider
        provider = ScriptedProvider()

    print(f"1. Engineer request: {args.request!r}")
    try:
        gen = generate_candidates(provider, args.request, args.count, args.out, REPO / "scenarios")
    except (AIUnavailable, ProviderError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"2. {provider.name} proposed {len(gen.files)} candidate(s) -> schema-validated -> review gate:")
    for note in gen.notes:
        print(f"     note: {note}")
    for f, r in zip(gen.files, gen.reviews):
        print(f"     {r.verdict:17} {f.name}")
    print(f"   Review: {gen.report}")

    approved = [f for f in gen.files if any(a in f.name for a in args.approve)]
    not_ready = [f.name for f, r in zip(gen.files, gen.reviews) if f in approved and r.verdict != READY]
    if not_ready:
        print(f"error: only a READY FOR REVIEW candidate can be approved, not {', '.join(not_ready)}", file=sys.stderr)
        return 2
    if approved:
        print("3. Engineer approved: " + ", ".join(f.name for f in approved))
    else:
        print("3. No candidate approved. An engineer reads the review and approves by name, e.g.")
        for f, r in zip(gen.files, gen.reviews):
            if r.verdict == READY:
                print(f"     python examples/ai_assist/run_flow.py --approve {f.stem}")

    print("4. Deterministic execution of the approved candidates (the same runner every scenario uses):")
    failed = []
    for f in approved:
        scenario = Scenario.load(f)
        result = run_scenario(scenario)
        print(f"     {'PASS' if result.passed else 'FAIL'}  {scenario.name} -- {result.detail}")
        if not result.passed:
            failed.append((scenario, result))

    # A NEEDS JUDGMENT candidate failed deterministically inside the gate:
    # a wrong test or a real finding. The engineer asks for hypotheses.
    for f, r in zip(gen.files, gen.reviews):
        if r.verdict == NEEDS_JUDGMENT:
            scenario = Scenario.load(f)
            failed.append((scenario, run_scenario(scenario)))
    print(f"5. AI run analysis of {len(failed)} failed run(s) -- hypotheses, never changes:")
    for scenario, result in failed:
        path = args.out / "analyses" / f"{Path(scenario.path).stem}.md"
        try:
            analyze_run(provider, scenario, result, path)
        except (AIUnavailable, ProviderError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"     {scenario.name}: {path}")
    print("6. Back to the engineer: nothing in scenarios/, the controller, or the plant was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
