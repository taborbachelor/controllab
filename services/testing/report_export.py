"""The commissioning report as JSON and as print-ready HTML (the master
specification's "JSON, HTML or PDF"; CLAUDE.md §14).

The JSON is the one intermediate: `report_dict()` turns the same
CoverageReport the console and Markdown reports use into plain data, and
`render_html()` renders only from that data, so the JSON and the HTML can't
disagree. PDF is the HTML printed: it carries a print stylesheet (A4/Letter
margins, tables kept whole across pages), so a browser's Print -> Save as
PDF gives the PDF without a PDF library (decided with Tabor: no new
dependency for it).

Like the Markdown report, both are deterministic for a given run: no
wall-clock timestamp, no absolute path. Provenance is the build stamp,
`BuildInfo`: the package version and the git commit the report was
generated from, flagged when the working tree had uncommitted changes.
`build_info()` is the one function here that touches the outside world
(package metadata and git); everything else is pure.

The summary follows the master specification's report layout: tests total /
passed / failed / warnings, a critical failure summary, and the operating
modes validated. A *warning* is a pass that needed something to pass -- met
only inside a real-time latency tolerance, or only partly observed because
the controller doesn't publish some field -- so it's never shown as a plain
pass. Not observable is counted apart: neither passed nor failed.
"""
from __future__ import annotations

import html
import subprocess
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from services.testing.commissioning_report import RealtimeConditions, _phase, describe
from services.testing.report import CoverageReport
from services.testing.verdict import LABELS, _fmt

SCHEMA = "controllab.commissioning-report/1"
SYSTEM = "Bulk material handling line (BIN-101 → XV-102 → FDR-103 → CV-104 → HOP-105)"
DEFAULT_CONTROLLER = "Built-in Python controller (in-process, lockstep)"


@dataclass(frozen=True)
class BuildInfo:
    version: str
    commit: str | None = None  # short SHA; None outside a git checkout
    dirty: bool = False  # uncommitted changes when the report was generated

    @property
    def label(self) -> str:
        text = f"controllab {self.version}"
        if self.commit:
            text += f", git {self.commit}" + (" + uncommitted changes" if self.dirty else "")
        return text

    def as_dict(self) -> dict:
        return {"version": self.version, "commit": self.commit, "dirty": self.dirty, "label": self.label}


def build_info(repo: Path) -> BuildInfo:
    """The installed package version and the checkout's commit (if git is there)."""
    try:
        version = metadata.version("controllab")
    except metadata.PackageNotFoundError:
        version = "unknown"
    try:
        run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True,  # noqa: E731
                                        check=True, timeout=10).stdout.strip()
        # Only this checkout's own commit: git walks up from `repo`, so a copy
        # that isn't a checkout but sits inside some other repository would
        # otherwise be stamped with that repository's commit.
        if Path(run("rev-parse", "--show-toplevel")).resolve() != Path(repo).resolve():
            return BuildInfo(version)
        return BuildInfo(version, run("rev-parse", "--short", "HEAD"), bool(run("status", "--porcelain")))
    except (OSError, subprocess.SubprocessError):
        return BuildInfo(version)


def _result_key(result) -> str:
    if result.not_observable:
        return "not_observable"
    if not result.passed:
        return "fail"
    return "pass_within_tolerance" if result.within_tolerance else "pass"


def _is_warning(result) -> bool:
    return result.passed and (result.within_tolerance or bool(result.not_observed))


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def report_dict(
    report: CoverageReport,
    scenarios_root: Path,
    controller: str = "",
    realtime: RealtimeConditions | None = None,
    build: BuildInfo | None = None,
) -> dict:
    """The whole report as JSON-ready data (str / number / bool / None / list / dict)."""
    results = report.results
    scenarios = []
    for scenario, result in results:
        when_t = result.when_applied_t
        scenarios.append({
            "name": scenario.name,
            "file": _rel(scenario.path, scenarios_root),
            "description": scenario.description,
            "interlock": scenario.interlock,
            "mode": "Manual" if scenario.given.get("line_state") == "manual" else "Auto",
            "result": _result_key(result),
            "passed": result.passed,
            "warning": _is_warning(result),
            "not_observed": list(result.not_observed),
            "response_s": result.elapsed_s if result.passed else None,
            "limit_s": scenario.within_s,
            "margin_s": round(scenario.within_s - result.elapsed_s, 9) if result.passed else None,
            "stage_elapsed_s": list(result.stage_elapsed),
            "failed_stage": result.failed_stage,
            "unmet": result.unmet,
            "detail": result.detail,
            "responses_per_pass_s": (list(realtime.responses.get(scenario.path, [])) if realtime else None),
            "events": [
                {"t": e.t, "phase": _phase(e, when_t), "type": e.type,
                 "data": dict(e.data), "text": describe(e).replace("**", "")}
                for e in result.events
            ],
        })
    return {
        "schema": SCHEMA,
        "system": SYSTEM,
        "build": build.as_dict() if build else None,
        "controller": controller or DEFAULT_CONTROLLER,
        "overall": report.verdict,
        "summary": {
            "total": len(results),
            "passed": report.passed_count,
            "failed": report.failed_count,
            "warnings": sum(1 for _, r in results if _is_warning(r)),
            "not_observable": report.not_observable_count,
        },
        "critical_failures": [
            {"scenario": s.name, "file": _rel(s.path, scenarios_root), "failed_stage": r.failed_stage,
             "detail": r.detail, "unmet": r.unmet}
            for s, r in results if not r.passed and not r.not_observable
        ],
        "modes": [
            {"mode": m.mode, "status": m.status, "run": m.run, "passed": m.passed, "not_observable": m.not_observable}
            for m in report.mode_counts()
        ],
        "interlocks": {
            "covered": report.covered_count,
            "total": len(report.rows),
            "not_applicable": report.not_applicable_count,
            "gaps": report.gap_count,
            "rows": [
                {"name": rc.row.name, "kind": rc.row.kind, "status": rc.status, "note": rc.row.note,
                 "scenarios": [{"name": n, "passed": p} for n, p in rc.scenarios], "unobservable": list(rc.unobservable)}
                for rc in report.rows
            ],
            "unknown_tags": list(report.unknown_tags),
        },
        "realtime": (
            {"latency_tolerance_s": realtime.latency_s, "speed": realtime.speed, "passes": realtime.passes}
            if realtime else None
        ),
        "scenarios": scenarios,
    }


# ---- HTML -------------------------------------------------------------------

_RESULT_TEXT = {"pass": "PASS", "pass_within_tolerance": "PASS within tolerance", "fail": "FAIL",
                "not_observable": "NOT OBSERVABLE"}
_STATUS_TEXT = {"covered": "covered", "covered_but_failing": "covered but failing", "not_covered": "not covered",
                "not_applicable": "not applicable yet", "not_observable": "not observable"}

_CSS = """
:root { --ink:#1f2328; --muted:#5d646c; --line:#c9ced4; --pass:#1f6f3f; --fail:#b3261e; --warn:#9a6700; --head:#eef1f4; }
* { box-sizing: border-box; }
body { margin: 0 auto; max-width: 1040px; padding: 28px 24px 48px; color: var(--ink); background: #fff;
       font: 13.5px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 16px; margin: 28px 0 8px; border-bottom: 1px solid var(--line); padding-bottom: 4px; }
h3 { font-size: 14px; margin: 18px 0 6px; }
.meta { color: var(--muted); margin: 2px 0; }
.summary { border: 2px solid var(--ink); border-radius: 6px; padding: 12px 16px; margin: 16px 0; }
.summary .overall { font-size: 18px; font-weight: 700; }
.PASS { color: var(--pass); } .FAIL { color: var(--fail); } .WARN { color: var(--warn); }
.counts { font-variant-numeric: tabular-nums; margin-top: 4px; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 10px; font-size: 12.5px; }
th, td { border: 1px solid var(--line); padding: 4px 7px; text-align: left; vertical-align: top; }
th { background: var(--head); font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
code { font-size: 12px; }
.modes { list-style: none; padding: 0; margin: 6px 0; display: flex; flex-wrap: wrap; gap: 6px 22px; }
.note { color: var(--muted); font-size: 12px; }
@media print {
  @page { margin: 14mm 12mm; }
  body { max-width: none; padding: 0; font-size: 11px; }
  h2 { break-after: avoid; } table, .summary, .scenario { break-inside: avoid; }
  a { color: inherit; text-decoration: none; }
}
"""


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _seconds(value) -> str:
    return "—" if value is None else f"{value:.2f} s"


def render_html(data: dict) -> str:
    """One self-contained HTML document (no script, no network) from report_dict()'s data."""
    s = data["summary"]
    overall = data["overall"]
    out = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>ControlLab Commissioning Report</title>",
        f"<style>{_CSS}</style></head><body>",
        "<h1>ControlLab — Commissioning Report</h1>",
        f'<p class="meta"><strong>System:</strong> {_e(data["system"])}</p>',
        f'<p class="meta"><strong>Build:</strong> {_e(data["build"]["label"]) if data["build"] else "not recorded"}</p>',
        f'<p class="meta"><strong>Controller under test:</strong> {_e(data["controller"])}</p>',
        '<div class="summary">',
        f'<div class="overall {"PASS" if overall == "PASS" else "FAIL"}">Overall: {_e(overall)}</div>',
        f'<div class="counts">Tests: {s["total"]} total | {s["passed"]} passed | {s["failed"]} failed | '
        f'{s["warnings"]} warnings' + (f' | {s["not_observable"]} not observable' if s["not_observable"] else "")
        + "</div>",
        f'<div class="counts">Interlocks: {data["interlocks"]["covered"]}/{data["interlocks"]["total"]} covered, '
        f'{data["interlocks"]["gaps"]} gap(s)</div>',
        "</div>",
        "<h2>Critical failure summary</h2>",
    ]
    if data["critical_failures"]:
        out.append("<ol>")
        for f in data["critical_failures"]:
            head = f"<li><strong>{_e(f['scenario'])}</strong>" + (f", stage {f['failed_stage']}" if f["failed_stage"] else "")
            if f["unmet"]:
                checks = "".join(
                    f"<li>{_e(LABELS.get(k, k))}: expected {_e(_fmt(v.get('expected')))}, actual {_e(_fmt(v.get('actual')))}</li>"
                    for k, v in f["unmet"].items()
                )
                out.append(f"{head}: an expectation wasn't met by its deadline<ul>{checks}</ul></li>")
            else:
                out.append(f"{head}: {_e(f['detail'])}</li>")
        out.append("</ol>")
    else:
        out.append("<p>None: no scenario failed.</p>")

    out += ["<h2>Operating modes validated</h2>", '<ul class="modes">']
    for m in data["modes"]:
        mark = {"validated": "✓", "failing": "✗", "not observable": "?", "not run": "–"}[m["status"]]
        cls = {"validated": "PASS", "failing": "FAIL"}.get(m["status"], "WARN")
        out.append(f'<li><span class="{cls}">[{mark}]</span> {_e(m["mode"])}: {m["passed"]}/{m["run"]} passed'
                   + (f', {m["not_observable"]} not observable' if m["not_observable"] else "") + "</li>")
    out.append("</ul>")
    out.append('<p class="note">A warning is a pass that needed an allowance: met only inside the real-time latency '
               "tolerance, or only partly observed. Not observable is neither a pass nor a failure.</p>")

    if data["realtime"]:
        rt = data["realtime"]
        out += ["<h2>Real-time conditions</h2>",
                f"<p>Free-running controller over Modbus TCP, plant at {rt['speed']:g}× real time, "
                f"latency tolerance {rt['latency_tolerance_s']:g} s, {rt['passes']} pass(es); each result is the "
                "worst pass.</p>"]

    out += ["<h2>Scenario results</h2>", "<table><thead><tr><th>Result</th><th>Scenario</th><th>Mode</th>"
            "<th>Response</th><th>Limit</th><th>Margin</th>"
            + ("<th>Each pass</th>" if data["realtime"] else "") + "<th>File</th></tr></thead><tbody>"]
    for sc in data["scenarios"]:
        text = _RESULT_TEXT[sc["result"]] + (", partly observed" if sc["not_observed"] else "")
        cls = "FAIL" if sc["result"] == "fail" else ("WARN" if sc["warning"] or sc["result"] == "not_observable" else "PASS")
        each = ""
        if data["realtime"]:
            each = "<td>" + ", ".join("fail" if t is None else f"{t:.2f}" for t in (sc["responses_per_pass_s"] or [])) + "</td>"
        out.append(f'<tr><td class="{cls}">{_e(text)}</td><td>{_e(sc["name"])}</td><td>{_e(sc["mode"])}</td>'
                   f'<td class="num">{_seconds(sc["response_s"])}</td><td class="num">{_seconds(sc["limit_s"])}</td>'
                   f'<td class="num">{_seconds(sc["margin_s"])}</td>{each}<td><code>{_e(sc["file"])}</code></td></tr>')
    out.append("</tbody></table>")

    out += ["<h2>Interlock coverage</h2>", "<table><thead><tr><th>Status</th><th>Interlock</th><th>Kind</th>"
            "<th>Scenarios</th><th>Note</th></tr></thead><tbody>"]
    for row in data["interlocks"]["rows"]:
        names = [_e(x["name"]) + ("" if x["passed"] else " (failing)") for x in row["scenarios"]]
        names += [_e(n) + " (not observable)" for n in row["unobservable"]]
        cls = "PASS" if row["status"] == "covered" else ("FAIL" if row["status"] in ("covered_but_failing", "not_covered") else "WARN")
        out.append(f'<tr><td class="{cls}">{_e(_STATUS_TEXT[row["status"]])}</td><td>{_e(row["name"])}</td>'
                   f'<td>{_e(row["kind"])}</td><td>{"<br>".join(names) or "—"}</td><td>{_e(row["note"]) or "—"}</td></tr>')
    out.append("</tbody></table>")
    if data["interlocks"]["unknown_tags"]:
        out.append("<p><strong>Unrecognized interlock tags:</strong> "
                   + ", ".join(f"<code>{_e(t)}</code>" for t in data["interlocks"]["unknown_tags"]) + "</p>")

    out.append("<h2>Event sequences</h2>")
    for sc in data["scenarios"]:
        out += [f'<div class="scenario"><h3>{_e(sc["name"])} — {_e(_RESULT_TEXT[sc["result"]])}</h3>',
                f'<p class="note"><code>{_e(sc["file"])}</code>' + (f" · {_e(sc['description'])}" if sc["description"] else "")
                + "</p>"]
        if sc["events"]:
            out.append("<table><thead><tr><th>t (s)</th><th>Phase</th><th>Event</th></tr></thead><tbody>")
            out += [f'<tr><td class="num">{ev["t"]:.2f}</td><td>{_e(ev["phase"])}</td><td>{_e(ev["text"])}</td></tr>'
                    for ev in sc["events"]]
            out.append("</tbody></table>")
        else:
            out.append('<p class="note">No events recorded.</p>')
        out.append("</div>")
    out += ['<p class="note">All times are simulated seconds. Print this page (Save as PDF) for the PDF report.</p>',
            "</body></html>"]
    return "\n".join(out) + "\n"
