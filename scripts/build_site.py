#!/usr/bin/env python
"""Builds the public demo: a few real scenario runs, recorded and written as
self-explaining replays that link to each other, so someone arriving from
the README can watch ControlLab work without installing anything.

    python scripts/build_site.py                 # writes _site/
    python scripts/build_site.py --out public

Every page is a real run made at build time by the same runner the test
suite uses, recorded from its own telemetry (scripts/replay.py). Nothing is
hand-edited, and CI (.github/workflows/pages.yml) rebuilds it from the
current code on every push, so the demo can't drift from the repository.
Output is deterministic: the same commit builds the same bytes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay import SCENARIOS_DIR, write_replay  # noqa: E402 -- the sibling script, not a package

REPO_URL = "https://github.com/taborbachelor/controllab"
PLC_NOTE = {
    "text": "Recorded on ControlLab's Python reference controller. The same scenario files run unchanged against "
            "OpenPLC executing a Structured Text port of the controller over Modbus TCP, in real time:",
    "link": "the PLC commissioning report",
    "href": f"{REPO_URL}/blob/main/examples/openplc/COMMISSIONING-REPORT.md",
}

# (output file, tab label, scenario, regression build or None). The first is
# the landing page: the fault-and-recovery story shows the most in one run.
RUNS: tuple[tuple[str, str, str, str | None], ...] = (
    ("index.html", "Feeder jam: trip and recovery", "faults/feeder_jam_recovery.yaml", None),
    ("bad-change.html", "A bad code change, caught", "faults/feeder_jam_recovery.yaml", "reset-ignores-jam"),
    ("overfill.html", "Overfill protection with a stuck switch", "faults/hopper_high_high_switch_stuck_weight_trips.yaml", None),
    ("normal.html", "Normal start and stop", "startup/normal_operation.yaml", None),
    ("batch.html", "A batch: load, hold, discharge, clean out", "batch/batch_cycle.yaml", None),
    ("manual.html", "Manual mode: each device by hand", "manual/manual_operation.yaml", None),
)


def build(out: Path) -> list[tuple[str, bool]]:
    """Writes every page into `out`; returns (file, passed) per page. Each
    page's run is made first, so the tabs can show the real verdicts."""
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    for file, _, scenario, regression in RUNS:  # first pass: the verdicts, for the tab badges
        results[file] = write_replay(SCENARIOS_DIR / scenario, out / file, regression)
    for file, _, scenario, regression in RUNS:  # second pass: the same runs, now with the navigation
        nav = [{"href": f, "label": label, "current": f == file, "passed": results[f]} for f, label, _, _ in RUNS]
        passed = write_replay(SCENARIOS_DIR / scenario, out / file, regression, extra_meta={"nav": nav, "repo": REPO_URL, "note": PLC_NOTE})
        assert passed == results[file], f"{file}: the run was not deterministic"
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return [(f, results[f]) for f, _, _, _ in RUNS]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("_site"), help="output directory (default: _site)")
    args = parser.parse_args()
    for file, passed in build(args.out):
        print(f"{'PASS' if passed else 'FAIL'}  {args.out / file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
