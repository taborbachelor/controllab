"""`controllab test` -- run commissioning scenarios against a control runtime
and print an engineering result for each.

    controllab test                                 # every scenario, Python controller
    controllab test feeder_jam_recovery             # scenarios whose file or name matches
    controllab test my_scenarios/                   # your own scenario files (a .yaml file or a directory)
    controllab test --runtime modbus                # the same controller, out of process, over Modbus TCP
    controllab test --runtime openplc jam           # OpenPLC in real time (examples/openplc set up first)
    controllab test --regression jam-trip-removed   # prove the suite catches a deliberate regression
    controllab test --list-regressions

(`python -m services.cli ...` works without installing.) A thin front end:
the scenarios, runner, runtimes and run summaries are the existing ones
(services/testing/); scripts/scenario_report.py remains the coverage
matrix and commissioning report. Exit status 1 when anything fails --
including when a deliberate regression is caught, which is the point.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from services.testing.regressions import REGRESSIONS
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario, ScenarioLoadError
from services.testing.verdict import RUNTIMES, render_text, summarize

SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "scenarios"


def select(patterns: list[str]) -> list[Scenario]:
    """The scenarios to run. A pattern that is an existing .yaml file or a
    directory is loaded from there, so an engineer's own scenarios run
    without being added to the repository's suite; any other pattern is a
    fragment of a suite scenario's file or name."""
    paths = [Path(p) for p in patterns if Path(p).is_dir() or (Path(p).is_file() and p.endswith((".yaml", ".yml")))]
    fragments = [p for p in patterns if Path(p) not in paths]
    chosen: list[Scenario] = []
    for path in paths:
        try:
            found = Scenario.discover(path) if path.is_dir() else [Scenario.load(path)]
        except ScenarioLoadError as e:
            raise SystemExit(f"cannot load scenario: {e}") from None
        if not found:
            raise SystemExit(f"no scenario files (*.yaml) under {path}")
        chosen += found
    if fragments or not patterns:
        suite = Scenario.discover(SCENARIOS_DIR)
        matched = [s for s in suite
                   if not fragments or any(p.lower() in s.path.relative_to(SCENARIOS_DIR).as_posix().lower()
                                           or p.lower() in s.name.lower() for p in fragments)]
        if not matched:
            raise SystemExit(f"no scenario matches {', '.join(fragments)}")
        chosen += matched
    return chosen


def _run_all(scenarios, runtime, regression, plc_url):
    if runtime == "openplc":
        from services.protocols.openplc import OpenPLCController
        from services.testing.realtime import RealtimePlant, run_realtime

        plant, controller = RealtimePlant(), OpenPLCController(plc_url)
        try:
            for s in scenarios:
                t0 = time.monotonic()
                yield s, run_realtime(s, plant, controller), time.monotonic() - t0
        finally:
            controller.close()
            plant.close()
        return
    for s in scenarios:
        t0 = time.monotonic()
        result = run_scenario(s, external=runtime == "modbus", line_cls=regression.cls if regression else None)
        yield s, result, time.monotonic() - t0


def cmd_test(args) -> int:
    if args.list_regressions:
        for r in REGRESSIONS.values():
            print(f"{r.name:28} {r.change}\n{'':28} demonstrated by {r.demo_scenario}")
        return 0
    regression = None
    if args.regression:
        if args.regression not in REGRESSIONS:
            raise SystemExit(f"unknown regression {args.regression!r} (see --list-regressions)")
        if args.runtime != "python":
            raise SystemExit("--regression swaps the in-process Python controller; use --runtime python")
        regression = REGRESSIONS[args.regression]
    scenarios = select(args.patterns)
    runtime = RUNTIMES[args.runtime]
    if regression:
        runtime += f" -- build with deliberate regression '{regression.name}'"
    print(f"Runtime: {runtime}")
    if regression:
        print(f"Regression under test: {regression.change}")
    print(f"{len(scenarios)} scenario(s)\n")

    summaries = []
    try:
        for scenario, result, wall in _run_all(scenarios, args.runtime, regression, args.plc):
            s = summarize(scenario, result, RUNTIMES[args.runtime], wall_time_s=wall, root=SCENARIOS_DIR,
                          regression=regression.name if regression else None)
            summaries.append(s)
            mark = s.verdict + ("*" if s.qualifier else "")
            print(f"  {mark:<15} {s.checks_passed:>2}/{s.checks_evaluated:<2} checks  {s.file}", flush=True)
    except ScenarioLoadError as e:
        # A malformed scenario (an unknown key, a value of the wrong shape)
        # is found as it runs: say which and why, not a traceback.
        raise SystemExit(f"scenario error: {e}") from None

    failed = [s for s in summaries if not s.passed]
    detail = failed if not args.verbose else summaries
    if len(summaries) == 1:
        detail = summaries
    for s in detail:
        print("\n" + render_text(s))

    passed = len(summaries) - len(failed)
    checks = sum(s.checks_passed for s in summaries), sum(s.checks_evaluated for s in summaries)
    print(f"\n{passed}/{len(summaries)} scenarios passed; {checks[0]}/{checks[1]} checks matched.")
    if regression:
        if failed:
            print(f"REGRESSION DETECTED: {len(failed)} scenario(s) caught '{regression.name}' "
                  f"(expected behavior: {regression.expected}).")
        else:
            print(f"NOT DETECTED: no selected scenario caught '{regression.name}'.")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # a Windows console is cp1252 by default
    parser = argparse.ArgumentParser(prog="controllab", description="ControlLab: virtual commissioning and "
                                     "controls validation.")
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("test", help="run scenarios against a control runtime")
    t.add_argument("patterns", nargs="*", help="scenario name fragments, or paths to your own .yaml files or directories "
                   "(default: the whole suite)")
    t.add_argument("--runtime", choices=tuple(RUNTIMES), default="python")
    t.add_argument("--regression", help="run a deliberately broken controller build (a testing fixture)")
    t.add_argument("--list-regressions", action="store_true")
    t.add_argument("--plc", default="http://127.0.0.1:8080", help="OpenPLC web UI (--runtime openplc)")
    t.add_argument("-v", "--verbose", action="store_true", help="print the full result for every scenario")
    t.set_defaults(func=cmd_test)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
