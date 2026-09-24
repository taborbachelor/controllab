"""The engineering result of one scenario run: what was set up, what was
done, what was expected at each stage, what actually happened, and the
verdict -- built only from what the runner recorded (ScenarioResult and
its event log), never inferred beyond it.

What each check can honestly say, from the runner's own record:

- a stage that **passed**: every expectation held at the tick the stage
  completed -- the runner only moves on when all of them match -- so each
  check is MATCH, and the actual value IS the expected one;
- the stage that **failed** on its deadline: the runner kept
  `{expected, actual}` for every expectation still unmet (MISMATCH, with
  the real value), so the others held at the deadline (MATCH);
- a stage that failed on an **invariant** (spillage, a motor running during
  E-stop, ...): the run stopped mid-stage, so its checks were NOT REACHED;
- stages after a failure: NOT RUN;
- against a controller that publishes no status block: NOT OBSERVED.

The first divergence is where the run is *known* to have departed from the
scenario (the failed stage, its deadline, what was unmet), the same
definition the AI run analysis is given; the cause may be earlier.

`runtime` names what controlled the plant; the caller supplies it, since
only the caller knows. Pure: no I/O, no clock -- wall time is passed in.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from services.testing.runner import ScenarioResult
from services.testing.scenario import Scenario

# The control runtimes a scenario can run against (the CLI and the dashboard
# name them the same way). The scenario files never change between them.
RUNTIMES: dict[str, str] = {
    "python": "Python controller (in-process, lockstep)",
    "modbus": "Python controller in a separate process, over Modbus TCP (lockstep)",
    "openplc": "OpenPLC Runtime running examples/openplc/controllab_line.st, over Modbus TCP (real time)",
}

# Plain names for the scenario vocabulary's read fields (vocabulary.READ_FIELDS);
# a drift test keeps this complete.
LABELS: dict[str, str] = {
    "line_state": "Line state",
    "fault_reason": "Trip reason",
    "mode": "Mode",
    "conveyor_running": "Conveyor running",
    "feeder_running": "Feeder running",
    "feeder_run_commanded": "Feeder run command",
    "conveyor_run_commanded": "Conveyor run command",
    "gate_open_commanded": "Gate open command",
    "feeder_flowing": "Material flowing from the feeder",
    "gate_open": "Gate open",
    "estop_healthy": "E-stop healthy",
    "spilled_kg": "Material spilled (kg)",
    "spilled": "Any material spilled",
    "belt_empty": "Conveyor belt empty",
    "hopper_level_kg": "Hopper level (kg)",
    "hopper_weight_agrees": "Hopper weight reading true",
    "any_unacknowledged_trip": "Unacknowledged trip alarm",
    "latched_alarm_ids": "Latched alarms",
    "first_out": "First-out alarm",
    "start_inhibit": "Start inhibit",
}

# What each stimulus key IS, for the stage headings. A drift test keeps
# this complete against vocabulary.APPLY_ACTIONS.
_OPERATOR = {"start", "stop", "reset", "acknowledge", "select_manual", "select_auto", "start_conveyor",
             "stop_conveyor", "open_gate", "close_gate", "start_feeder", "stop_feeder"}
_FAULTS = {"conveyor_trip", "feeder_trip", "conveyor_fail_to_start", "feeder_fail_to_start", "gate_stuck",
           "belt_slip", "feeder_jam"}
_FIELD_RESETS = {"feeder_drive_reset", "conveyor_overload_reset", "gate_reset"}
_PROCESS = {"hopper_level_pct", "bin_level_pct"}
_SENSORS = {"sensor_stuck": "fault", "sensor_failed": "fault", "sensor_restored": "repair",
            "sensor_noise": "fault", "sensor_drift": "fault", "sensor_slow": "fault"}

KINDS = {"operator": "Operator action", "fault": "Fault injected", "repair": "Field repair",
         "process": "Process condition"}


def classify(key: str, value: object) -> str:
    """operator / fault / repair / process."""
    if key in _OPERATOR:
        return "operator"
    if key == "estop":
        return "fault" if value == "tripped" else "repair"
    if key in _FAULTS:
        return "fault" if value else "repair"
    if key in _FIELD_RESETS:
        return "repair"
    if key in _SENSORS:
        return _SENSORS[key]
    if key in _PROCESS:
        return "process"
    raise KeyError(key)


# What each stimulus DOES, in a sentence a newcomer can read: the stage
# narration on the replay page. (true-text, false-text); an instrument key
# formats its tag, a level key its percentage. A drift test keeps this
# complete against vocabulary.APPLY_ACTIONS.
_PHRASES: dict[str, tuple[str, str]] = {
    "start": ("Operator presses Start", ""),
    "stop": ("Operator presses Stop", ""),
    "reset": ("Operator presses Reset", ""),
    "acknowledge": ("Operator acknowledges the alarm", ""),
    "select_manual": ("Operator selects Manual mode", ""),
    "select_auto": ("Operator selects Auto mode", ""),
    "start_conveyor": ("Operator starts the conveyor (Manual)", ""),
    "stop_conveyor": ("Operator stops the conveyor (Manual)", ""),
    "open_gate": ("Operator opens the gate (Manual)", ""),
    "close_gate": ("Operator closes the gate (Manual)", ""),
    "start_feeder": ("Operator starts the feeder (Manual)", ""),
    "stop_feeder": ("Operator stops the feeder (Manual)", ""),
    "conveyor_trip": ("The conveyor motor's overload trips", "The cause of the conveyor overload is removed"),
    "feeder_trip": ("The feeder drive faults", "The cause of the feeder drive fault is removed"),
    "conveyor_fail_to_start": ("The conveyor motor will not start when told to", "The conveyor motor is repaired"),
    "feeder_fail_to_start": ("The feeder drive will not start when told to", "The feeder drive is repaired"),
    "gate_stuck": ("The gate actuator sticks", "The gate actuator is freed"),
    "belt_slip": ("The conveyor belt starts slipping (motor on, belt not moving)", "The belt slip is fixed"),
    "feeder_jam": ("The feeder jams: its drive keeps turning but the discharge chute plugs",
                   "The jam is cleared at the feeder"),
    "feeder_drive_reset": ("The feeder drive is reset at the field", ""),
    "conveyor_overload_reset": ("The conveyor overload is reset at the field", ""),
    "gate_reset": ("The gate actuator is reset at the field", ""),
}


def describe_action(key: str, value: object) -> str:
    """A scenario action as a plain sentence."""
    if key == "estop":
        return "Someone presses the E-stop" if value == "tripped" else "The E-stop is released"
    if key == "sensor_stuck":
        return f"{value} sticks at its last reading"
    if key == "sensor_failed":
        return f"{value} loses its signal"
    if key == "sensor_noise":
        return f"{value['tag']} turns noisy (±{value['amplitude']:g} around the true reading)"
    if key == "sensor_drift":
        return f"{value['tag']} drifts out of calibration ({value['rate_per_s']:+g} per second)"
    if key == "sensor_slow":
        return f"{value['tag']} turns slow (it reports what was true {value['seconds']:g} s earlier)"
    if key == "sensor_restored":
        return f"{value} is repaired"
    if key == "hopper_level_pct":
        return f"The hopper is at {value:g} % full"
    if key == "bin_level_pct":
        return f"The bin is at {value:g} % full"
    on, off = _PHRASES[key]
    return on if value or not off else off


def describe_setup(given: dict) -> list[str]:
    """A scenario's `given` as plain sentences: the starting condition."""
    out = []
    for key, value in given.items():
        if key == "line_state":
            out.append("The line is started and running" if value == "running" else "The line is stopped and ready")
        else:
            out.append(describe_action(key, value))
    return out


@dataclass
class Check:
    key: str
    label: str
    expected: object
    actual: object
    status: str  # match | mismatch | not_reached | not_run | not_observed


@dataclass
class StageSummary:
    n: int
    title: str
    actions: list[dict]  # {key, value, kind, text}
    within_s: float
    status: str  # passed | failed | not_run | not_observable
    applied_t: float | None
    response_s: float | None
    checks: list[Check]


@dataclass
class RunSummary:
    scenario: str
    file: str
    description: str
    runtime: str
    verdict: str  # PASS | FAIL | NOT OBSERVABLE
    passed: bool
    qualifier: str  # "", "partly observed", "within latency tolerance", "setup failed"
    detail: str
    setup: dict
    stages: list[StageSummary]
    checks_passed: int
    checks_evaluated: int
    checks_total: int
    invariants: str
    first_out: str | None
    first_divergence: dict | None
    plant_time_s: float | None
    wall_time_s: float | None
    regression: str | None = None
    notes: list[str] = field(default_factory=list)
    setup_text: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def summarize(
    scenario: Scenario,
    result: ScenarioResult,
    runtime: str,
    wall_time_s: float | None = None,
    root=None,
    regression: str | None = None,
) -> RunSummary:
    stages = scenario.stages
    n_passed = len(result.stage_elapsed)  # the runner records a response time for every stage that passed
    invariant_failure = "invariant violated" in result.detail
    setup_failed = result.when_applied_t is None and not result.passed

    applied = result.when_applied_t
    summaries: list[StageSummary] = []
    for n, stage in enumerate(stages, start=1):
        if n <= n_passed:
            status = "passed"
        elif n == result.failed_stage:
            status = "failed"
        elif result.not_observable and n == n_passed + 1:
            status = "not_observable"
        else:
            status = "not_run"
        if status == "failed":
            applied = result.failed_stage_applied_t
        stage_applied = applied if status in ("passed", "failed", "not_observable") else None
        response = result.stage_elapsed[n - 1] if status == "passed" else None

        checks = []
        for key, expected in stage.expect.items():
            label = LABELS.get(key, key)
            if key in result.not_observed or status == "not_observable":
                checks.append(Check(key, label, expected, None, "not_observed"))
            elif status == "passed":
                checks.append(Check(key, label, expected, expected, "match"))
            elif status == "failed" and key in result.unmet:
                checks.append(Check(key, label, expected, result.unmet[key]["actual"], "mismatch"))
            elif status == "failed" and not invariant_failure:
                checks.append(Check(key, label, expected, expected, "match"))
            elif status == "failed":
                checks.append(Check(key, label, expected, None, "not_reached"))
            else:
                checks.append(Check(key, label, expected, None, "not_run"))
        summaries.append(StageSummary(
            n=n, title=stage.title,
            actions=[{"key": k, "value": v, "kind": classify(k, v), "text": describe_action(k, v)}
                     for k, v in stage.when.items()],
            within_s=stage.within_s, status=status, applied_t=stage_applied, response_s=response, checks=checks,
        ))
        if status == "passed" and applied is not None:
            applied = round(applied + response, 9)

    all_checks = [c for st in summaries for c in st.checks]
    evaluated = [c for c in all_checks if c.status in ("match", "mismatch")]
    passed_checks = [c for c in evaluated if c.status == "match"]

    if result.passed:
        verdict = "PASS"
        qualifier = ("partly observed" if result.not_observed
                     else "within latency tolerance" if result.within_tolerance else "")
    elif result.not_observable:
        verdict, qualifier = "NOT OBSERVABLE", ""
    else:
        verdict, qualifier = "FAIL", ("setup failed" if setup_failed else "")

    first_divergence = None
    if not result.passed and not result.not_observable:
        failed = next((st for st in summaries if st.status == "failed"), None)
        if failed is not None:
            first_divergence = {
                "stage": failed.n,
                "stage_title": failed.title,
                "stage_applied_t": failed.applied_t,
                "t": (round(failed.applied_t + failed.within_s, 9)
                      if failed.applied_t is not None and not invariant_failure else None),
                "kind": "invariant violated" if invariant_failure else "expectations unmet by the deadline",
                "unmet": [{"label": c.label, "key": c.key, "expected": c.expected, "actual": c.actual}
                          for c in failed.checks if c.status == "mismatch"],
                "detail": result.detail,
            }
        else:
            first_divergence = {"stage": None, "stage_title": "", "stage_applied_t": None, "t": None,
                                "kind": "setup failed", "unmet": [], "detail": result.detail}

    first_out = None
    for e in result.events:
        if (e.type == "alarm_activated" and e.data.get("first_out")
                and (result.when_applied_t is None or e.t >= result.when_applied_t)):
            first_out = e.data["alarm_id"]
            break

    plant_t = result.tags.samples[-1].t if result.tags and result.tags.samples else None
    path = scenario.path
    try:
        file = path.relative_to(root).as_posix() if root else path.as_posix()
    except ValueError:
        file = path.as_posix()
    return RunSummary(
        scenario=scenario.name, file=file, description=scenario.description, runtime=runtime,
        verdict=verdict, passed=result.passed, qualifier=qualifier, detail=result.detail,
        setup=dict(scenario.given), stages=summaries,
        checks_passed=len(passed_checks), checks_evaluated=len(evaluated), checks_total=len(all_checks),
        invariants=("violated: " + result.detail) if invariant_failure else (
            "held on every tick" if not setup_failed else "not checked past setup"),
        first_out=first_out, first_divergence=first_divergence,
        plant_time_s=plant_t, wall_time_s=wall_time_s, regression=regression,
        setup_text=describe_setup(scenario.given),
    )


def plan(scenario: Scenario, root=None) -> dict:
    """The test before it runs: setup, then each stage's actions, what it
    expects, and its time limit -- the skeleton a live view fills in as the
    run proceeds (summarize() is the same shape with the outcomes)."""
    path = scenario.path
    try:
        file = path.relative_to(root).as_posix() if root else path.as_posix()
    except ValueError:
        file = path.as_posix()
    return {
        "scenario": scenario.name,
        "file": file,
        "description": scenario.description,
        "setup_text": describe_setup(scenario.given),
        "stages": [
            {
                "n": n, "title": stage.title, "within_s": stage.within_s,
                "actions": [{"key": k, "value": v, "kind": classify(k, v), "text": describe_action(k, v)}
                            for k, v in stage.when.items()],
                "checks": [{"key": k, "label": LABELS.get(k, k), "expected": v} for k, v in stage.expect.items()],
            }
            for n, stage in enumerate(scenario.stages, start=1)
        ],
    }


def event_signature(result: ScenarioResult) -> list[tuple]:
    """The run's event log as comparable tuples: two lockstep runs of the same
    scenario on different runtimes are identical exactly when these are."""
    return [(e.t, e.type, tuple(sorted(e.data.items()))) for e in result.events]


def _fmt(v: object) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        return "[" + ", ".join(map(str, v)) + "]" if v else "none"
    return str(v)


_MARK = {"match": "MATCH", "mismatch": "MISMATCH", "not_reached": "NOT REACHED", "not_run": "not run",
         "not_observed": "not observed"}


def render_text(s: RunSummary) -> str:
    """The console form (`controllab test`)."""
    bar = "─" * 60
    head = "REGRESSION FAILURE" if s.regression and not s.passed else "SCENARIO COMPLETE"
    lines = [head, "", s.scenario, bar, ""]
    verdict = s.verdict + (f" ({s.qualifier})" if s.qualifier else "")
    lines += [f"Result:   {verdict}", f"Runtime:  {s.runtime}"]
    if s.regression:
        lines.append(f"Controller build: deliberate regression '{s.regression}' (testing fixture)")
    lines.append(f"Checks:   {s.checks_passed}/{s.checks_evaluated} evaluated checks matched"
                 + (f" ({s.checks_total - s.checks_evaluated} not run / not observed)"
                    if s.checks_total != s.checks_evaluated else ""))
    if s.first_out:
        lines.append(f"First-out alarm: {s.first_out}")
    lines.append(f"Invariants: {s.invariants}")
    timing = []
    if s.plant_time_s is not None:
        timing.append(f"{s.plant_time_s:.1f} s plant time")
    if s.wall_time_s is not None:
        timing.append(f"{s.wall_time_s:.1f} s wall time")
    if timing:
        lines.append("Time:     " + ", ".join(timing))
    if s.setup:
        lines += ["", "Setup: " + ", ".join(f"{k} = {_fmt(v)}" for k, v in s.setup.items())]
    for st in s.stages:
        acts = ", ".join(f"{KINDS[a['kind']].lower()}: {a['key']}" + ("" if a["value"] is True else f" = {_fmt(a['value'])}")
                         for a in st.actions) or "no action (keep watching)"
        timing = f"{st.response_s:.2f} s / limit {st.within_s:g} s" if st.response_s is not None else f"limit {st.within_s:g} s"
        lines += ["", f"Stage {st.n}" + (f": {st.title}" if st.title else ""),
                  f"  do: {acts}   [{st.status.upper().replace('_', ' ')}, {timing}]"]
        for c in st.checks:
            actual = "" if c.status in ("match", "not_run", "not_observed", "not_reached") else f"  (actual: {_fmt(c.actual)})"
            lines.append(f"  {_MARK[c.status]:<12} {c.label}: expected {_fmt(c.expected)}{actual}")
    if s.first_divergence:
        d = s.first_divergence
        where = f"stage {d['stage']}" + (f" ({d['stage_title']})" if d["stage_title"] else "") if d["stage"] else "setup"
        at = f", t = {d['t']:.2f} s (the stage's deadline)" if d["t"] is not None else ""
        lines += ["", f"Failure detected at: {where}{at} -- {d['kind']}"]
        for u in d["unmet"]:
            lines.append(f"  expected {u['label']} = {_fmt(u['expected'])}, actual {_fmt(u['actual'])}")
        if not d["unmet"]:
            lines.append(f"  {d['detail']}")
    return "\n".join(lines)
