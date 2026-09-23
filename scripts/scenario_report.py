#!/usr/bin/env python
"""Runs every scenario under scenarios/ and prints the commissioning
report: pass/fail per scenario, then the interlock coverage matrix
(docs/CONTROL-LAB.md §6.3) built from it.

    python scripts/scenario_report.py
    python scripts/scenario_report.py --out coverage_report.txt
    python scripts/scenario_report.py --markdown commissioning_report.md

--out saves the console text below. --markdown writes the full
commissioning report (services/testing/commissioning_report.py): the same
results and coverage matrix, plus each scenario's timing margin and its
recorded event/alarm sequence. Both come from the same single scenario
run -- the suite never runs twice.

All the actual logic lives in services/testing/report.py and
commissioning_report.py (tested in tests/unit/) -- this file is only
console formatting and a CLI entry point.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from services.testing.commissioning_report import render_markdown
from services.testing.report import CoverageReport, build_report
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario, ScenarioLoadError

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = REPO_ROOT / "scenarios"

STATUS_LABEL = {
    "covered": "OK",
    "covered_but_failing": "FAILING",
    "not_covered": "GAP",
    "not_applicable": "N/A",
}


def render(report: CoverageReport) -> str:
    lines: list[str] = []
    lines.append("ControlLab -- Commissioning Scenario Report")
    lines.append("=" * 44)
    lines.append("")
    lines.append(f"Scenarios run: {len(report.results)}")
    lines.append(f"  Passed: {report.passed_count}")
    lines.append(f"  Failed: {len(report.results) - report.passed_count}")
    lines.append("")
    lines.append("Results:")
    for scenario, result in report.results:
        rel = scenario.path.relative_to(SCENARIOS_DIR).as_posix()
        mark = "PASS" if result.passed else "FAIL"
        lines.append(f"  {mark}  {scenario.name}  (t={result.elapsed_s:.2f}s)  {rel}")
        if not result.passed:
            lines.append(f"        {result.detail}")
    lines.append("")

    # "section 6.3", not "§6.3" -- the report prints to a plain console,
    # and Windows terminals default to a codepage that mangles §.
    lines.append("Interlock Coverage (docs/CONTROL-LAB.md, section 6.3)")
    lines.append("=" * 44)
    for row_cov in report.rows:
        label = STATUS_LABEL[row_cov.status]
        row = row_cov.row
        if row_cov.status == "not_applicable":
            detail = f"not applicable yet -- {row.note}"
        elif row_cov.scenarios:
            names = ", ".join(n for n, _ in row_cov.scenarios)
            detail = f"{len(row_cov.scenarios)} scenario(s): {names}"
            if row.note:
                detail += f"  [{row.note}]"
        else:
            detail = "no scenario tags this row"
        lines.append(f"  [{label:7}] {row.name:32} {detail}")
    lines.append("")

    if report.unknown_tags:
        lines.append("WARNING -- interlock: tags matching no known section 6.3 row (likely a typo):")
        for tag in report.unknown_tags:
            lines.append(f"  - {tag!r}")
        lines.append("")

    total = len(report.rows)
    lines.append(
        f"{report.covered_count}/{total} interlocks covered by at least one passing scenario "
        f"({report.not_applicable_count} not yet applicable, {report.gap_count} real gap(s))."
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="also write the console report to this file")
    parser.add_argument(
        "--markdown", type=Path, default=None, help="also write the full Markdown commissioning report to this file"
    )
    args = parser.parse_args()

    scenarios = Scenario.discover(SCENARIOS_DIR)
    results: list[tuple[Scenario, object]] = []
    for scenario in scenarios:
        try:
            result = run_scenario(scenario)
        except ScenarioLoadError as e:
            print(f"FATAL: {e}", file=sys.stderr)
            return 2
        results.append((scenario, result))

    report = build_report(results)
    text = render(report)
    print(text)

    if args.out is not None:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"\nWrote {args.out}")

    if args.markdown is not None:
        args.markdown.write_text(render_markdown(report, SCENARIOS_DIR), encoding="utf-8")
        print(f"\nWrote {args.markdown}")

    return 0 if report.gap_count == 0 and report.passed_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
