"""`controllab test` -- run commissioning scenarios against a control runtime
and print an engineering result for each.

    controllab test                                 # every scenario, Python controller
    controllab test feeder_jam_recovery             # scenarios whose file or name matches
    controllab test my_scenarios/                   # your own scenario files (a .yaml file or a directory)
    controllab test --runtime modbus                # the same controller, out of process, over Modbus TCP
    controllab test --runtime openplc jam           # OpenPLC in real time (examples/openplc set up first)
    controllab test --runtime external my_scenarios/    # your own controller, polling the plant on 5020
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

from services.testing.realtime import ControllerRestartError
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


REALTIME = ("openplc", "external")  # free-running controllers: the plant is served, paced on the wall clock
EXTERNAL_LABEL = "Your controller over Modbus TCP (real time)"


def _controller(args):
    """The free-running controller under test, for a real-time runtime."""
    if args.runtime == "openplc":
        from services.protocols.openplc import OpenPLCController

        return OpenPLCController(args.plc)
    from services.testing.realtime import ExternalController

    return ExternalController(args.restart_cmd)


def _register_map(args):
    from services.protocols.line_map import LINE_REGISTER_MAP

    if args.map is None:
        return LINE_REGISTER_MAP
    from services.protocols.map_file import load_map
    from services.simulation.engine.plant_io import build_line_io_image

    return load_map(args.map, build_line_io_image())[0]


def _run_all(scenarios, args, regression, controller):
    if args.runtime in REALTIME:
        from services.protocols.modbus import exposure_warning
        from services.testing.realtime import RealtimePlant, run_realtime

        register_map = _register_map(args)
        status = not args.no_status and bool(register_map.status_registers)
        warning = exposure_warning(args.bind)
        if warning:
            print(warning, file=sys.stderr, flush=True)
        plant = RealtimePlant(host=args.bind, port=args.modbus_port, register_map=register_map)
        if args.runtime == "external":
            print(f"Plant served on {plant.host}:{plant.port}: your controller should be polling it now.\n",
                  flush=True)
        try:
            for s in scenarios:
                t0 = time.monotonic()
                yield s, run_realtime(s, plant, controller, status=status), time.monotonic() - t0
        finally:
            controller.close()
            plant.close()
        return
    for s in scenarios:
        t0 = time.monotonic()
        result = run_scenario(s, external=args.runtime == "modbus", line_cls=regression.cls if regression else None)
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
    realtime_only = [flag for flag, used in (("--restart-cmd", args.restart_cmd), ("--map", args.map),
                                            ("--no-status", args.no_status),
                                            ("--bind", args.bind != "127.0.0.1"),
                                            ("--modbus-port", args.modbus_port != 5020)) if used]
    if realtime_only and args.runtime not in REALTIME:
        raise SystemExit(f"{', '.join(realtime_only)}: only for a real-time runtime (--runtime openplc or external)")
    if args.restart_cmd and args.runtime != "external":
        raise SystemExit("--restart-cmd is for --runtime external (ControlLab restarts OpenPLC itself)")
    scenarios = select(args.patterns)
    controller = _controller(args) if args.runtime in REALTIME else None
    label = f"{EXTERNAL_LABEL}: {controller.name}" if args.runtime == "external" else RUNTIMES[args.runtime]
    runtime = label
    if regression:
        runtime += f" -- build with deliberate regression '{regression.name}'"
    print(f"Runtime: {runtime}")
    if regression:
        print(f"Regression under test: {regression.change}")
    print(f"{len(scenarios)} scenario(s)\n")

    summaries = []
    try:
        for scenario, result, wall in _run_all(scenarios, args, regression, controller):
            s = summarize(scenario, result, label, wall_time_s=wall, root=SCENARIOS_DIR,
                          regression=regression.name if regression else None)
            summaries.append(s)
            mark = s.verdict + ("*" if s.qualifier else "")
            print(f"  {mark:<15} {s.checks_passed:>2}/{s.checks_evaluated:<2} checks  {s.file}", flush=True)
    except ScenarioLoadError as e:
        # A malformed scenario (an unknown key, a value of the wrong shape)
        # is found as it runs: say which and why, not a traceback.
        raise SystemExit(f"scenario error: {e}") from None
    except ControllerRestartError as e:
        raise SystemExit(f"stopped: {e}") from None

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
    t.add_argument("--runtime", choices=(*RUNTIMES, "external"), default="python",
                   help="external: your own controller, polling the plant ControlLab serves (docs/CONNECTING-A-CONTROLLER.md)")
    t.add_argument("--regression", help="run a deliberately broken controller build (a testing fixture)")
    t.add_argument("--list-regressions", action="store_true")
    t.add_argument("--plc", default="http://127.0.0.1:8080", help="OpenPLC web UI (--runtime openplc)")
    t.add_argument("-v", "--verbose", action="store_true", help="print the full result for every scenario")
    rt = t.add_argument_group("real-time runtimes (openplc, external)")
    rt.add_argument("--modbus-port", type=int, default=5020, help="port the plant is served on (default 5020)")
    rt.add_argument("--bind", default="127.0.0.1",
                    help="address the plant is served on (default 127.0.0.1, this machine only); another address "
                    "exposes unauthenticated Modbus to the network: an isolated bench network only")
    rt.add_argument("--map", type=Path, default=None,
                    help="serve the plant at the addresses in this I/O map file (configs/io/)")
    rt.add_argument("--no-status", action="store_true",
                    help="the controller publishes no status block: expectations on its state are not observed")
    rt.add_argument("--restart-cmd", default=None,
                    help="--runtime external: a shell command that restarts your controller before every scenario "
                    "(must exit 0); without it, each scenario starts from acknowledge + reset to a clean IDLE")
    t.set_defaults(func=cmd_test)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
