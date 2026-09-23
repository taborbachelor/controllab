#!/usr/bin/env python
"""Runs every scenario under scenarios/ and prints the commissioning
report: pass/fail per scenario, then the interlock coverage matrix
(docs/CONTROL-LAB.md §6.3) built from it.

    python scripts/scenario_report.py
    python scripts/scenario_report.py --out coverage_report.txt
    python scripts/scenario_report.py --markdown commissioning_report.md
    python scripts/scenario_report.py --external    # same suite, controller across Modbus
    python scripts/scenario_report.py --realtime reference --speed 4
    python scripts/scenario_report.py --realtime openplc --repeat 3 --markdown report.md

--realtime runs the suite against a FREE-RUNNING controller (Phase 9,
services/testing/realtime.py): the plant is served on 127.0.0.1:--modbus-port
and paced on the wall clock. `reference` is ControlLab's own controller in a
thread; `openplc` is an OpenPLC Runtime already set up to poll that port
(examples/openplc/README.md, with scripts/dashboard.py NOT running, since
this takes its port), cold-restarted through its web UI before every
scenario. --repeat runs the whole suite that many times and reports the
response-time spread.

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

from services.testing.commissioning_report import RealtimeConditions, render_markdown
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
        mark = ("PASS~" if result.within_tolerance else "PASS") if result.passed else "FAIL"
        lines.append(f"  {mark:5} {scenario.name}  (t={result.elapsed_s:.2f}s)  {rel}")
        if not result.passed or result.within_tolerance:
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
        "--external", action="store_true",
        help="run every scenario against the reference external controller across Modbus (Phase 7 step 3b)",
    )
    parser.add_argument(
        "--markdown", type=Path, default=None, help="also write the full Markdown commissioning report to this file"
    )
    rt = parser.add_argument_group("real-time run against a free-running controller (Phase 9)")
    rt.add_argument("--realtime", choices=("reference", "openplc"), default=None)
    rt.add_argument("--modbus-port", type=int, default=5020, help="port the plant is served on (the one the PLC polls)")
    rt.add_argument("--repeat", type=int, default=1, help="run the whole suite this many times")
    rt.add_argument("--latency", type=float, default=None, help="I/O latency tolerance, plant seconds (default 0.5)")
    rt.add_argument("--speed", type=float, default=1.0, help="plant speed; reference controller only (a real PLC runs at 1)")
    rt.add_argument("--plc", default="http://127.0.0.1:8080", help="OpenPLC web UI")
    rt.add_argument("--plc-user", default="openplc")
    rt.add_argument("--plc-password", default="openplc")
    args = parser.parse_args()
    if args.realtime and args.external:
        parser.error("--realtime and --external are different modes; pick one")
    if args.realtime == "openplc" and args.speed != 1.0:
        parser.error("a real PLC's timers run on wall time: --realtime openplc runs at --speed 1")

    scenarios = Scenario.discover(SCENARIOS_DIR)
    conditions = None
    controller_name = "reference external controller over Modbus TCP (`--external`)" if args.external else ""
    if args.realtime:
        try:
            results, conditions, controller_name = _run_realtime(args, scenarios)
        except ScenarioLoadError as e:
            print(f"FATAL: {e}", file=sys.stderr)
            return 2
    else:
        results = []
        for scenario in scenarios:
            try:
                result = run_scenario(scenario, external=args.external)
            except ScenarioLoadError as e:
                print(f"FATAL: {e}", file=sys.stderr)
                return 2
            results.append((scenario, result))

    report = build_report(results)
    text = render(report)
    if conditions is not None:
        text = f"Controller under test: {controller_name}\n" + _render_spread(report, conditions) + "\n" + text
    print(text)

    if args.out is not None:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"\nWrote {args.out}")

    if args.markdown is not None:
        args.markdown.write_text(render_markdown(report, SCENARIOS_DIR, controller_name, conditions), encoding="utf-8")
        print(f"\nWrote {args.markdown}")

    return 0 if report.gap_count == 0 and report.passed_count == len(results) else 1


def _run_realtime(args, scenarios):
    from services.testing.realtime import LATENCY_S, RealtimePlant, ReferenceController, run_suite_realtime

    latency = LATENCY_S if args.latency is None else args.latency
    plant = RealtimePlant(port=args.modbus_port)
    if args.realtime == "openplc":
        from services.protocols.openplc import OpenPLCController

        controller = OpenPLCController(args.plc, args.plc_user, args.plc_password)
    else:
        controller = ReferenceController(plant.port, speed=args.speed)

    def progress(n, scenario, result):
        mark = ("PASS~" if result.within_tolerance else "PASS") if result.passed else "FAIL"
        print(f"  pass {n}/{args.repeat}  {mark:5} {result.elapsed_s:5.2f}s  {scenario.name}", flush=True)

    print(f"Real-time run: {controller.name}; plant on 127.0.0.1:{plant.port}, {args.speed:g}x, "
          f"latency tolerance {latency:g}s, {args.repeat} pass(es)", flush=True)
    try:
        runs = run_suite_realtime(scenarios, plant, controller, repeat=args.repeat, speed=args.speed,
                                  latency_s=latency, on_result=progress)
    finally:
        controller.close()
        plant.close()
    print()
    conditions = RealtimeConditions(latency, args.speed, args.repeat, {r.scenario.path: r.responses for r in runs})
    return [(r.scenario, r.combined()) for r in runs], conditions, controller.name


def _render_spread(report: CoverageReport, conditions: RealtimeConditions) -> str:
    lines = [f"Latency tolerance {conditions.latency_s:g}s; PASS~ = met after its limit, inside the tolerance."]
    if conditions.passes > 1:
        lines.append(f"Response time across {conditions.passes} passes (min - max):")
        for scenario, _ in report.results:
            ok = [t for t in conditions.responses.get(scenario.path, []) if t is not None]
            span = f"{min(ok):.2f} - {max(ok):.2f}s" if ok else "no passing run"
            lines.append(f"  {len(ok)}/{conditions.passes}  {span:16} {scenario.name}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
