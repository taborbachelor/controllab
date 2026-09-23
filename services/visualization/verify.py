"""Scenario verification from the dashboard: run a commissioning scenario
against a chosen control runtime, or against every available one, and keep
the engineering result (services/testing/verdict.py) for the page.

Nothing here judges anything. Each runtime goes through the path the CLI
and the test suite already use:

- **python**: runner.execute() on the dashboard's own line
  (LiveSession.run_live), so the picture shows the verification happening;
- **modbus**: run_scenario(external=True), the same controller in a
  separate process, reached only over Modbus TCP;
- **openplc**: run_realtime() against OpenPLC, when its web UI answers.

One job at a time, on a background thread; the page polls for the result.
Comparing runtimes reports each runtime's own verdict and checks, and says
exactly what was compared: two lockstep runs are compared event for event
(identical or not); a real-time run can't be bit-exact (response times
depend on where in the PLC's scan a change lands), so it is compared by
verdict and checks only -- and the page says so.
"""
from __future__ import annotations

import threading
import time
import urllib.request
from pathlib import Path

from services.testing.regressions import REGRESSIONS
from services.testing.rig import DT
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario
from services.testing.verdict import RUNTIMES, event_signature, plan, summarize

SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "scenarios"

# The scenarios the dashboard leads with: (file, card title, guided
# walkthrough id or None). Every other scenario runs from `controllab test`.
SHOWCASE: tuple[tuple[str, str, str | None], ...] = (
    ("startup/normal_operation.yaml", "Normal operation", "normal"),
    ("faults/feeder_jam_recovery.yaml", "Feeder jam recovery", None),
    ("faults/conveyor_trip_recovery.yaml", "Conveyor fault recovery", None),
    ("faults/hopper_weight_failure_recovery.yaml", "Failed hopper weight transmitter", None),
    ("faults/hopper_high_high_switch_stuck_weight_trips.yaml", "Overfill protection: failed level switch", "overfill"),
)


def showcase() -> list[dict]:
    out = []
    for file, title, tour in SHOWCASE:
        s = Scenario.load(SCENARIOS_DIR / file)
        out.append({
            "file": file,
            "title": title,
            "name": s.name,
            "description": s.description,
            "stages": len(s.stages),
            "walkthrough": tour,
        })
    return out


def regressions() -> list[dict]:
    return [{"name": r.name, "change": r.change, "demo_scenario": r.demo_scenario} for r in REGRESSIONS.values()]


class Verifier:
    def __init__(self, session, pacer=None, plc_url: str = "http://127.0.0.1:8080") -> None:
        self.session = session
        self.pacer = pacer
        self.plc_url = plc_url
        # While a job runs: {"id", "scenario", "runtime", "step", "of", "plan", "progress"}. `plan` is the
        # test before it runs (verdict.plan); `progress` follows the live Python run stage by stage
        # ({"stage": n being run, "applied_t": its start, "passed": {n: response_s}}), and stays empty
        # for background runtimes, which report only their result.
        self.busy: dict | None = None
        self.latest: dict | None = None  # {"id", "runs": [summary dicts], "comparison"}
        self.latest_result = None  # (scenario, ScenarioResult) of the first run, for the replay
        self._lock = threading.Lock()
        self._plc_checked = (0.0, False)
        self._seq = 0

    # ---- runtimes ------------------------------------------------------

    def openplc_available(self) -> bool:
        """Whether OpenPLC's web UI answers (cached for 5 s: the page polls)."""
        checked_at, ok = self._plc_checked
        if time.monotonic() - checked_at < 5.0:
            return ok
        try:
            with urllib.request.urlopen(self.plc_url + "/login", timeout=0.5) as r:
                ok = r.status == 200
        except OSError:
            ok = False
        self._plc_checked = (time.monotonic(), ok)
        return ok

    def runtimes(self) -> dict:
        return {
            "python": {"label": RUNTIMES["python"], "available": True, "live": True},
            "modbus": {"label": RUNTIMES["modbus"], "available": True, "live": False},
            "openplc": {"label": RUNTIMES["openplc"], "available": self.openplc_available(), "live": False},
        }

    def view(self) -> dict:
        return {"busy": self.busy, "latest": self.latest, "runtimes": self.runtimes()}

    # ---- jobs ----------------------------------------------------------

    def start(self, file: str, runtime: str = "python", regression: str | None = None, compare: bool = False,
              background: bool = True) -> None:
        path = SCENARIOS_DIR / file if isinstance(file, str) else None
        if path is None or not path.is_file() or SCENARIOS_DIR.resolve() not in path.resolve().parents:
            raise ValueError(f"unknown scenario {file!r}")
        if runtime not in RUNTIMES:
            raise ValueError(f"runtime must be one of {', '.join(RUNTIMES)}")
        if regression is not None and regression not in REGRESSIONS:
            raise ValueError(f"unknown regression {regression!r}")
        if regression and (runtime != "python" or compare):
            raise ValueError("a regression fixture swaps the in-process Python controller: run it on the Python "
                             "runtime alone")
        if runtime == "openplc" and not compare and not self.openplc_available():
            raise ValueError("OpenPLC is not reachable (see examples/openplc/README.md)")
        with self._lock:
            if self.busy is not None:
                raise ValueError("a verification is already running")
            self.busy = {"scenario": file, "runtime": RUNTIMES[runtime], "step": 1, "of": 1, "plan": None,
                         "progress": {}, "id": self._seq + 1}
        if background:
            threading.Thread(target=self._job, args=(file, runtime, regression, compare), daemon=True,
                             name="controllab-verify").start()
        else:
            self._job(file, runtime, regression, compare)

    def _pace(self) -> None:
        if self.pacer is None:
            return
        while not self.pacer.running:
            time.sleep(0.05)
        time.sleep(DT / self.pacer.speed)

    def _job(self, file: str, runtime: str, regression: str | None, compare: bool) -> None:
        try:
            scenario = Scenario.load(SCENARIOS_DIR / file)
            test_plan = plan(scenario, root=SCENARIOS_DIR)
            chosen = ["python", "modbus"] + (["openplc"] if self.openplc_available() else []) if compare else [runtime]
            runs = []
            for i, rt in enumerate(chosen, start=1):
                progress: dict = {"stage": None, "applied_t": None, "passed": {}}
                self.busy = {"scenario": scenario.name, "runtime": RUNTIMES[rt], "step": i, "of": len(chosen),
                             "plan": test_plan, "progress": progress if rt == "python" else {}, "id": self._seq + 1,
                             "regression": regression}
                t0 = time.monotonic()
                result = self._run(scenario, rt, regression, progress)
                summary = summarize(scenario, result, RUNTIMES[rt], wall_time_s=time.monotonic() - t0,
                                    root=SCENARIOS_DIR, regression=regression)
                runs.append((rt, result, summary))
            self._seq += 1
            self.latest_result = (scenario, runs[0][1])
            self.latest = {
                "id": self._seq,
                "runs": [s.to_dict() | {"runtime_id": rt} for rt, _, s in runs],
                "comparison": _compare(runs) if len(runs) > 1 else None,
                "not_compared": ([] if not compare or any(rt == "openplc" for rt, _, _ in runs)
                                 else ["OpenPLC (not reachable: see examples/openplc/README.md)"]),
            }
        except Exception as e:  # a broken run must never leave the page stuck on "running"
            self._seq += 1
            self.latest = {"id": self._seq, "error": f"{type(e).__name__}: {e}", "runs": [], "comparison": None}
        finally:
            self.busy = None

    def _run(self, scenario: Scenario, runtime: str, regression: str | None, progress: dict | None = None):
        cls = REGRESSIONS[regression].cls if regression else None
        if runtime == "python":
            def follow(e: dict) -> None:
                if progress is None:
                    return
                if e["event"] == "stage":
                    progress.update(stage=e["n"], applied_t=e["applied_t"])
                else:
                    progress["passed"] = {**progress["passed"], e["n"]: e["elapsed"]}
            return self.session.run_live(scenario, self._pace, line_cls=cls, progress=follow)
        if runtime == "modbus":
            return run_scenario(scenario, external=True)
        from services.protocols.openplc import OpenPLCController
        from services.testing.realtime import RealtimePlant, run_realtime

        plant, controller = RealtimePlant(), OpenPLCController(self.plc_url)
        try:
            return run_realtime(scenario, plant, controller)
        finally:
            controller.close()
            plant.close()


def _compare(runs: list) -> dict:
    """Each runtime against the first (the Python controller), saying exactly
    what was compared."""
    base_rt, base, base_s = runs[0]
    rows = []
    for rt, result, s in runs:
        if rt == base_rt:
            how, same = "reference run", None
        elif rt == "openplc":
            how = "real time: compared by verdict and checks (response times vary with the PLC's scan phase)"
            same = s.verdict == base_s.verdict and s.checks_passed == base_s.checks_passed
        else:
            identical = event_signature(result) == event_signature(base)
            how = "lockstep: event log compared event by event" + (" -- identical" if identical else " -- DIFFERENT")
            same = identical and s.verdict == base_s.verdict
        rows.append({
            "runtime_id": rt, "runtime": s.runtime, "verdict": s.verdict, "checks": f"{s.checks_passed}/{s.checks_evaluated}",
            "stage_response_s": [st.response_s for st in s.stages], "how": how, "agrees": same,
        })
    return {"rows": rows, "all_agree": all(r["agrees"] is not False for r in rows)}
