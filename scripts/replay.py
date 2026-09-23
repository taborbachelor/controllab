#!/usr/bin/env python
"""Runs one scenario and writes a self-contained HTML replay of it
(docs/CONTROL-LAB.md §10, Phase 6 step 2) -- open the file in any
browser, no server needed.

    python scripts/replay.py scenarios/safety/estop_from_running.yaml
    python scripts/replay.py scenarios/faults/gate_travel_timeout.yaml --out gate.html
    python scripts/replay.py scenarios/faults/feeder_jam_recovery.yaml --regression reset-ignores-jam

The replay is built from the run's own telemetry (the events and tag
history run_scenario() always records), not from a second simulation.
All the logic lives in services/visualization/replay.py -- this file only
runs the scenario and writes the file.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from services.testing.regressions import REGRESSIONS
from services.testing.rig import DEFAULT_PLANT_CONFIG
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario
from services.testing.verdict import RUNTIMES, summarize
from services.visualization.replay import build_replay, render_html

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = REPO_ROOT / "scenarios"

# run_scenario() always builds its rig from rig.py's defaults (scenarios
# have no plant-config overrides), so these are the constants the run used.
PLANT = {
    key: DEFAULT_PLANT_CONFIG[key]
    for key in ("hopper_capacity_kg", "hopper_high_pct", "hopper_high_high_pct", "bin_capacity_kg")
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", type=Path, help="path to a scenario YAML file")
    parser.add_argument("--out", type=Path, default=None, help="output HTML file (default: <scenario-name>.replay.html)")
    parser.add_argument("--regression", choices=sorted(REGRESSIONS), default=None,
                        help="run against a deliberately broken controller build (services/testing/regressions.py)")
    args = parser.parse_args()
    out = args.out or Path(args.scenario.stem + ".replay.html")
    passed = write_replay(args.scenario, out, args.regression)
    print(f"{'PASS' if passed else 'FAIL'}  {args.scenario}")
    print(f"Wrote {out}")
    return 0


def write_replay(path: Path, out: Path, regression: str | None = None, extra_meta: dict | None = None) -> bool:
    """Runs the scenario (against a regression build if named) and writes
    its self-explaining replay: the recording plus the run summary.
    Returns whether the run passed."""
    scenario = Scenario.load(path)
    reg = REGRESSIONS[regression] if regression else None
    result = run_scenario(scenario, line_cls=reg.cls if reg else None)
    summary = summarize(scenario, result, RUNTIMES["python"], root=SCENARIOS_DIR, regression=regression)
    try:
        file = scenario.path.resolve().relative_to(SCENARIOS_DIR).as_posix()
    except ValueError:
        file = scenario.path.name

    replay = build_replay(
        scenario.name,
        result.events,
        result.tags,
        PLANT,
        meta={
            "passed": result.passed,
            "file": file,
            "detail": result.detail,
            "when_applied_t": result.when_applied_t,
            "regression_change": reg.change if reg else None,
            **(extra_meta or {}),
        },
        summary=summary.to_dict(),
    )
    out.write_text(render_html(replay), encoding="utf-8")
    return result.passed


if __name__ == "__main__":
    raise SystemExit(main())
