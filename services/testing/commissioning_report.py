"""The generated commissioning report (docs/CONTROL-LAB.md §10, Phase 5
step 4; CLAUDE.md §14): one Markdown document covering what the
commissioning scenarios proved -- pass/fail, response time against each
scenario's own `within` limit, the interlock coverage matrix, and the
event/alarm sequence each scenario actually produced.

Built entirely from things that already exist, not a new data path: the
CoverageReport from services/testing/report.py (the same object the
console report prints), and the telemetry events each ScenarioResult
already carries (services/testing/runner.py records them on every run).
The report can't disagree with the run, because it IS the run's record.

Pure logic, no I/O -- returns a string. scripts/scenario_report.py's
--markdown flag is the only thing that writes it to disk, the same
logic/file-writer split report.py and services/telemetry/ already use.

Deliberately deterministic, byte for byte: no wall-clock generation
timestamp, no absolute paths, and every number comes from simulated
time. Two runs against the same code produce an identical file, so a
committed report diffs cleanly in git and a changed line means changed
behavior (docs/CONTROL-LAB.md §7, item 3). The git commit a report was
generated from is the right provenance record, not a date inside it.

Markdown only, for now (CLAUDE.md §14: "don't implement every export
format immediately") -- GitHub renders it, and it diffs as text.

A real-time run against a free-running controller (Phase 9) passes
`realtime`: the report then states the conditions (latency tolerance,
plant speed, number of passes), marks a result met only inside the
tolerance as exactly that, and adds each scenario's response-time spread
across the passes. Such a report is a record of one session on real
hardware timing, so it is NOT byte-identical run to run -- the lockstep
report still is.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from services.telemetry.events import Event
from services.testing.report import CoverageReport

STATUS_LABEL = {
    "covered": "✅ covered",
    "covered_but_failing": "❌ covered but failing",
    "not_covered": "⚠️ not covered",
    "not_applicable": "➖ not applicable yet",
}


@dataclass
class RealtimeConditions:
    """How a real-time run was made (services/testing/realtime.py).
    `responses` maps a scenario's path to its response time in each pass,
    None where that pass failed."""

    latency_s: float
    speed: float
    passes: int
    responses: dict[Path, list[float | None]] = field(default_factory=dict)


def render_markdown(
    report: CoverageReport, scenarios_root: Path, controller: str = "", realtime: RealtimeConditions | None = None
) -> str:
    """`scenarios_root` only relativizes scenario file paths for display,
    so the output never contains a machine-specific absolute path.
    `controller` names what was tested when it isn't the built-in one
    (Phase 7 step 3b); omitted, the output is exactly as before.
    `realtime` describes a real-time run (Phase 9); see the module
    docstring."""
    lines: list[str] = []
    total = len(report.results)
    failed = total - report.passed_count
    verdict = "PASS" if failed == 0 and report.gap_count == 0 else "FAIL"

    lines += [
        "# ControlLab — Commissioning Report",
        "",
        *([f"**Controller under test:** {controller}", ""] if controller else []),
        f"**Overall: {verdict}** — {report.passed_count}/{total} scenarios passed; "
        f"{report.covered_count}/{len(report.rows)} interlocks covered "
        f"({report.not_applicable_count} not yet applicable, {report.gap_count} gap(s)).",
        "",
        "All times are simulated seconds. Response time is measured from the moment the "
        "scenario's `when` stimulus is applied until every `expect` condition holds.",
        "",
    ]
    if realtime is not None:
        lines += _realtime_conditions(realtime)

    lines += _results_table(report, scenarios_root)
    if realtime is not None and realtime.passes > 1:
        lines += _spread_table(report, scenarios_root, realtime)
    lines += _coverage_table(report)
    if report.unknown_tags:
        lines += ["## Unrecognized interlock tags", ""]
        lines += [f"- `{tag}` — matches no §6.3 row (likely a typo)" for tag in report.unknown_tags]
        lines.append("")
    lines += _sequences(report, scenarios_root)

    return "\n".join(lines).rstrip("\n") + "\n"


def _results_table(report: CoverageReport, scenarios_root: Path) -> list[str]:
    lines = [
        "## Scenario results",
        "",
        "| Result | Scenario | Response | Limit | Margin | File |",
        "|---|---|---:|---:|---:|---|",
    ]
    for scenario, result in report.results:
        if not result.passed:
            mark = "❌ FAIL"
        elif result.within_tolerance:
            mark = "🟡 PASS within tolerance"
        else:
            mark = "✅ PASS"
        if result.passed:
            response = f"{result.elapsed_s:.2f} s"
            margin = f"{scenario.within_s - result.elapsed_s:.2f} s"
        else:
            response, margin = "—", "—"
        lines.append(
            f"| {mark} | {_cell(scenario.name)} | {response} | {scenario.within_s:.2f} s | {margin} "
            f"| `{_rel(scenario.path, scenarios_root)}` |"
        )
    lines.append("")

    failures = [(s, r) for s, r in report.results if not r.passed]
    if failures:
        lines += ["**Failures:**", ""]
        lines += [f"- **{_cell(s.name)}** — {_cell(r.detail)}" for s, r in failures]
        lines.append("")
    return lines


def _realtime_conditions(rt: RealtimeConditions) -> list[str]:
    speed = "real time (1×)" if rt.speed == 1 else f"{rt.speed:g}× real time"
    return [
        "## Real-time conditions",
        "",
        f"The controller ran free on its own clock against the plant paced at {speed}, "
        "reaching it only over Modbus TCP. Every scenario started from a fresh plant and a cold-restarted "
        "controller, brought to a clean IDLE by the operator procedure (acknowledge, reset), which is not "
        "part of the scenario's record.",
        "",
        f"- **Latency tolerance: {rt.latency_s:g} s** of plant time for the I/O round trip (a Modbus poll and "
        "a controller scan on each side of a hand-off). A result met after its limit but inside the "
        "tolerance is marked 🟡 *PASS within tolerance*, never counted as on time. The same allowance "
        "is the settle before `when` and the grace on the feeder-onto-an-unproven-conveyor invariant.",
        f"- **Passes: {rt.passes}.** A scenario passes only if every pass passed; the result shown is the "
        "worst pass (the first failure, or else the slowest).",
        "- Real-time results are not bit-exact: response times vary with where in the controller's scan "
        "a change lands. The lockstep report is the deterministic one.",
        "",
    ]


def _spread_table(report: CoverageReport, scenarios_root: Path, rt: RealtimeConditions) -> list[str]:
    lines = [
        f"## Response time across {rt.passes} passes",
        "",
        "| Scenario | Passed | Min | Max | Each pass |",
        "|---|---:|---:|---:|---|",
    ]
    for scenario, _ in report.results:
        times = rt.responses.get(scenario.path, [])
        ok = [t for t in times if t is not None]
        each = ", ".join("fail" if t is None else f"{t:.2f}" for t in times)
        lo = f"{min(ok):.2f} s" if ok else "—"
        hi = f"{max(ok):.2f} s" if ok else "—"
        lines.append(f"| {_cell(scenario.name)} | {len(ok)}/{len(times)} | {lo} | {hi} | {each} |")
    lines.append("")
    return lines


def _coverage_table(report: CoverageReport) -> list[str]:
    lines = [
        "## Interlock coverage (docs/CONTROL-LAB.md §6.3)",
        "",
        "| Status | Interlock | Kind | Scenarios | Note |",
        "|---|---|---|---|---|",
    ]
    for row_cov in report.rows:
        names = "<br>".join(_cell(n) + ("" if passed else " (failing)") for n, passed in row_cov.scenarios) or "—"
        lines.append(
            f"| {STATUS_LABEL[row_cov.status]} | {row_cov.row.name} | {row_cov.row.kind} | {names} "
            f"| {_cell(row_cov.row.note) or '—'} |"
        )
    lines.append("")
    return lines


def _sequences(report: CoverageReport, scenarios_root: Path) -> list[str]:
    lines = [
        "## Event sequences",
        "",
        "What each scenario actually did, from its telemetry record. **setup** events come "
        "from reaching the scenario's `given` preconditions; **response** events are the "
        "system reacting to `when`.",
        "",
    ]
    for scenario, result in report.results:
        mark = "PASS" if result.passed else "FAIL"
        lines += [f"### {scenario.name} — {mark}", "", f"`{_rel(scenario.path, scenarios_root)}`", ""]
        if not result.events:
            lines += ["*No events recorded.*", ""]
            continue
        lines += ["| t (s) | Phase | Event |", "|---:|---|---|"]
        for event in result.events:
            lines.append(f"| {event.t:.2f} | {_phase(event, result.when_applied_t)} | {describe(event)} |")
        lines.append("")
    return lines


def _phase(event: Event, when_applied_t: float | None) -> str:
    if when_applied_t is None or event.t <= when_applied_t:
        return "setup"
    return "response"


def describe(event: Event) -> str:
    """One human-readable line per event. Unknown event types fall back to
    their raw fields instead of raising, so a future event type
    shows up in the report instead of breaking it."""
    d = event.data
    if event.type == "command_issued":
        return f"Operator command: **{d['command']}**"
    if event.type == "state_changed":
        text = f"Line state {d['from']} → **{d['to']}**"
        if d.get("fault_reason") and d["to"] in ("faulted", "estopped"):
            text += f" ({_cell(str(d['fault_reason']))})"
        return text
    if event.type == "alarm_activated":
        kind = "Warning" if d.get("is_warning") else "Alarm"
        text = f"{kind} **{d['alarm_id']}** active — {_cell(str(d['description']))}"
        if d.get("first_out"):
            text += " · **first-out**"
        return text
    if event.type == "alarm_cleared":
        return f"Alarm {d['alarm_id']} cleared"
    if event.type == "alarm_acknowledged":
        return f"Alarm {d['alarm_id']} acknowledged"
    return f"{event.type}: {_cell(str(d))}"


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _cell(text: str) -> str:
    """Keeps free text from breaking a Markdown table row."""
    return text.replace("|", "\\|").replace("\n", " ")
