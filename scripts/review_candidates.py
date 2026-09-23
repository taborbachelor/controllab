#!/usr/bin/env python
"""Reviews candidate scenario files before an engineer considers them
(docs/CONTROL-LAB.md §10, Phase 8 step 1):

    python scripts/review_candidates.py path/to/candidate.yaml [more.yaml ...]
    python scripts/review_candidates.py candidates/ --out review.md

Each candidate -- from a person or, later, a model -- goes through the
fixed checks in services/testing/candidates.py: it loads, uses only the
scenario vocabulary, names a real interlock row, isn't a duplicate, runs
deterministically, agrees across Modbus, isn't vacuous (it must fail
without its stimulus), and isn't brittle. Verdict per candidate: READY
FOR REVIEW, NEEDS JUDGMENT (it fails against the controller -- a wrong
test or a real finding), or REJECTED.

Keep candidates OUTSIDE scenarios/ -- the suite discovers every YAML file
there. Accepting a candidate means an engineer moving it in; this script
never does. Exit code 1 if any candidate is rejected.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from services.testing.candidates import REJECTED, render_markdown, review
from services.testing.scenario import Scenario

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = REPO_ROOT / "scenarios"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=Path, help="candidate .yaml files, or directories of them")
    parser.add_argument("--out", type=Path, default=None, help="also write the Markdown review here")
    args = parser.parse_args()

    files: list[Path] = []
    for p in args.paths:
        files += sorted(p.rglob("*.yaml")) if p.is_dir() else [p]
    inside = [f for f in files if SCENARIOS_DIR in f.resolve().parents]
    if inside:
        parser.error(f"{inside[0]} is already inside scenarios/ -- candidates are reviewed before they go there")

    existing = Scenario.discover(SCENARIOS_DIR)
    reviews = [review(f, existing) for f in files]
    text = render_markdown(reviews, root=Path.cwd())
    # Windows consoles default to a codepage without the report's status
    # marks; degrade them there rather than crash (the --out file keeps them).
    sys.stdout.reconfigure(errors="replace")
    print(text)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    return 1 if any(r.verdict == REJECTED for r in reviews) else 0


if __name__ == "__main__":
    raise SystemExit(main())
