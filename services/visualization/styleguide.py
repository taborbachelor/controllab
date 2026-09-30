"""The published style guide (frontend redesign, build step 6; the design
specification's D12 and section 12.4): one self-contained page generated
from the same sources the dashboard and replays use, so it cannot drift
from them. scripts/build_site.py writes it beside the demo runs.

Step 6 renders the tokens: every colour with what it is for, the contrast
pairs recomputed from tokens.css, the type scale, spacing, sizes, shape and
motion. Step 7 adds the icon set (plain markup) and the components in every
state (7c's test results from real runs), drawn in the browser by their real render functions from
components.js with the words from copytext.py (Tabor, 2026-09-28: the
component section needs script; the token sections don't).
Deterministic: no dates, no randomness, the same bytes on every build.
"""
from __future__ import annotations

import json
import re
from html import escape

from services.visualization import copytext
from services.visualization import tokens as tk
from services.visualization.page import HERE

TYPE_SCALE = (("fs-xs", "12 px: the floor, labels and tag chips"), ("fs-sm", "13 px: secondary text"),
              ("fs-md", "14 px: body text"), ("fs-lg", "16 px: emphasis"),
              ("fs-xl", "20 px: the status sentence"), ("fs-2xl", "24 px: the replay title"))
SPACE = ("sp-1", "sp-2", "sp-3", "sp-4", "sp-5", "sp-6", "gutter")
OTHER = (("Size", ("control-h", "target-min", "header-h", "statusbar-h", "rail-w", "indicator", "marker")),
         ("Shape", ("radius-sm", "radius-md")),
         ("Motion", ("dur", "ease", "flow-period")),
         ("Type", ("font-ui", "font-mono")))
SAMPLE = "The controller stopped the feeder."

PAGE_CSS = """
  body { margin: 0; background: var(--page); color: var(--ink); font: var(--fs-md)/1.45 var(--font-ui); }
  header, main { max-width: 1100px; margin: 0 auto; padding: var(--sp-5) var(--gutter); }
  header { padding-bottom: 0; }
  h1 { font-size: var(--fs-2xl); line-height: 1.2; margin: 0 0 var(--sp-2); }
  h2 { font-size: var(--fs-lg); margin: var(--sp-6) 0 var(--sp-2); }
  p { margin: 0 0 var(--sp-3); max-width: 80ch; }
  a { color: var(--info); }
  code, .mono { font-family: var(--font-mono); }
  td code { white-space: nowrap; }
  .wrap table { border-collapse: collapse; width: 100%; background: var(--surface); border: 1px solid var(--border); }
  .wrap th, .wrap td { text-align: left; padding: var(--sp-2) var(--sp-3); border-bottom: 1px solid var(--border); vertical-align: middle; }
  .wrap th { font-size: var(--fs-xs); color: var(--ink-muted); font-weight: 600; }
  td.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
  .wrap { overflow-x: auto; }
  .sw { display: inline-block; width: 40px; height: 24px; border: 1px solid var(--border-strong); border-radius: var(--radius-sm); vertical-align: middle; }
  .cp { display: inline-block; min-width: 140px; padding: var(--sp-1) var(--sp-2); border-radius: var(--radius-sm); font-weight: 600; }
  .cp.graphic { border: 3px solid; }
  .bar { display: inline-block; height: var(--sp-3); background: var(--equip-on); vertical-align: middle; }
  .muted { color: var(--ink-muted); }
  h3 { font-size: var(--fs-md); margin: var(--sp-5) 0 var(--sp-2); }
  .sg-row { display: flex; flex-wrap: wrap; gap: var(--sp-3) var(--sp-4); align-items: flex-start; padding: var(--sp-4);
            background: var(--surface); border: 1px solid var(--border); }
  .sg-item { display: flex; flex-direction: column; gap: var(--sp-1); align-items: flex-start; }
  .sg-caption { color: var(--ink-muted); font: var(--fs-xs)/1.4 var(--font-mono); }
  .sg-stack { display: grid; gap: var(--sp-3); width: 100%; max-width: 560px; }
  .sg-cols { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
  .sg-cols > .sg-item { align-items: stretch; min-width: 0; }
  .sg-icon { display: inline-flex; align-items: center; gap: var(--sp-2); min-width: 150px; }
  footer { max-width: 1100px; margin: 0 auto; padding: var(--sp-5) var(--gutter) var(--sp-6); color: var(--ink-muted); font-size: var(--fs-sm); }
"""


def _swatch_rules() -> str:
    """One class per colour token and per contrast pair, so the page needs no inline style."""
    rules = [f"  .sw-{name} {{ background: var(--{name}); }}" for name, _ in tk.COLOURS]
    for i, p in enumerate(tk.PAIRS):
        rules.append(f"  .cp-{i} {{ color: var(--{p.fg}); background: var(--{p.bg}); border-color: var(--{p.fg}); }}")
    rules += [f"  .fs-{n} {{ font-size: var(--{n}); }}" for n, _ in TYPE_SCALE]
    rules += [f"  .bar-{n} {{ width: var(--{n}); }}" for n in SPACE]
    return "\n".join(rules)


def _colours(values: dict[str, str]) -> str:
    rows = "".join(
        f'<tr><td><span class="sw sw-{n}"></span></td><td><code>--{n}</code></td>'
        f'<td class="mono">{escape(values[n])}</td><td>{escape(use)}</td></tr>'
        for n, use in tk.COLOURS)
    return ('<div class="wrap"><table><thead><tr><th>Swatch</th><th>Token</th><th>Value</th><th>Used for</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>")


def _pairs(values: dict[str, str]) -> str:
    rows = []
    for i, p in enumerate(tk.PAIRS):
        ratio = tk.pair_ratio(p, values)
        kind = "text" if p.minimum == tk.TEXT else "graphic"
        sample = "Aa · 12.3 s" if kind == "text" else "Outline"
        rows.append(
            f'<tr><td><span class="cp cp-{i}{" graphic" if kind == "graphic" else ""}">{sample}</span></td>'
            f"<td><code>--{p.fg}</code> on <code>--{p.bg}</code></td><td>{escape(p.use)}</td>"
            f'<td class="num">{ratio:.2f} : 1</td><td class="num">{p.minimum:.1f} : 1 ({kind})</td>'
            f'<td>{"passes" if ratio >= p.minimum else "FAILS"}</td></tr>')
    return ('<div class="wrap"><table><thead><tr><th>Sample</th><th>Pair</th><th>Used for</th><th>Ratio</th>'
            f'<th>Needs (WCAG 2.2 AA)</th><th>Result</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _type() -> str:
    rows = "".join(f'<tr><td><code>--{n}</code></td><td class="muted">{escape(use)}</td>'
                   f'<td class="fs-{n}">{SAMPLE}</td></tr>' for n, use in TYPE_SCALE)
    return f'<div class="wrap"><table><tbody>{rows}</tbody></table></div>'


def _space(values: dict[str, str]) -> str:
    rows = "".join(f'<tr><td><code>--{n}</code></td><td class="num">{escape(values[n])}</td>'
                   f'<td><span class="bar bar-{n}"></span></td></tr>' for n in SPACE)
    return f'<div class="wrap"><table><tbody>{rows}</tbody></table></div>'


def _other(values: dict[str, str]) -> str:
    rows = "".join(f'<tr><td>{group}</td><td><code>--{n}</code></td><td class="mono">{escape(values[n])}</td></tr>'
                   for group, names in OTHER for n in names)
    return f'<div class="wrap"><table><thead><tr><th>Group</th><th>Token</th><th>Value</th></tr></thead><tbody>{rows}</tbody></table></div>'


GALLERY_7B = """
(function consoleControls() {
  const $ = (id) => document.getElementById(id);
  const item = (el, caption) => h("div", {class: "sg-item"}, el, h("code", {class: "sg-caption"}, caption));
  const noop = () => {};
  // CommandButton, in every state.
  for (const [caption, data] of [["available", {preview: {accepted: true}}], ["primary", {preview: {accepted: true}, primary: true}],
                                 ["unavailable", {preview: {accepted: false}}], ["sent", {preview: {accepted: true}, sent: true}],
                                 ["no preview", {preview: null}], ["locked", {preview: {accepted: true}, locked: true}]]) {
    const b = commandButton("start", COPY, noop);
    renderCommandButton(b, data, COPY);
    $("sg-commands").appendChild(item(b, caption));
  }
  // EStopButton: released, pressed (click it), locked.
  const live = estopButton(COPY, (pressed) => renderEStopButton(live, {pressed}, COPY));
  renderEStopButton(live, {pressed: false}, COPY);
  const pressed = estopButton(COPY, noop); renderEStopButton(pressed, {pressed: true}, COPY);
  const locked = estopButton(COPY, noop); renderEStopButton(locked, {pressed: false, locked: true}, COPY);
  $("sg-estop").append(item(live, "released (try it)"), item(pressed, "pressed"), item(locked, "locked"));
  // SegmentedControl: the mode (Batch unavailable) and the source bin; then locked.
  const modes = [{value: "select_auto", label: COPY.commands.select_auto}, {value: "select_manual", label: COPY.commands.select_manual},
                 {value: "select_batch", label: COPY.commands.select_batch}];
  const mode = segmentedControl("Mode", modes, (v) => renderSegmentedControl(mode, {selected: v, unavailable: {select_batch: true}}));
  renderSegmentedControl(mode, {selected: "select_auto", unavailable: {select_batch: true}});
  const bins = segmentedControl("Source bin", [{value: "A", label: "A"}, {value: "B", label: "B"}, {value: "C", label: "C"}], noop);
  renderSegmentedControl(bins, {selected: "A", locked: true});
  $("sg-seg").append(item(mode, "mode; Batch unavailable"), item(bins, "source bin, locked"));
  // PermissiveNote: a reason before the press, a refusal after it, no preview.
  for (const [kind, text] of [["preview", "Can't start yet: bin A is nearly empty."], ["refused", "Start refused: bin A is nearly empty."],
                              ["unknown", COPY.controls.preview_unknown]]) {
    const n = permissiveNote(`sg-note-${kind}`);
    renderPermissiveNote(n, {kind, text});
    $("sg-notes").appendChild(item(n, kind));
  }
  // PermissiveTable: reported blocking reasons only; then the no-preview case.
  const table = permissiveTable();
  renderPermissiveTable(table, {requests: [
    {label: "Start", rows: [{text: "Bin A is nearly empty", tag: "BIN_LOW"}, {text: "An alarm is not acknowledged", tag: "UNACKNOWLEDGED_ALARM"}],
     empty: "Nothing is blocking Start."},
    {label: "Reset", rows: [], empty: "Nothing is blocking Reset."}]});
  const none = permissiveTable();
  renderPermissiveTable(none, {requests: [], note: COPY.controls.preview_unknown});
  $("sg-ptable").append(item(table, "blocking reasons"), item(none, "no preview"));
  // DeviceRow: on, off, commanded.
  for (const [name, commands, data] of [
      ["Conveyor", ["start_conveyor", "stop_conveyor"], {state: "on", stateText: "Running", buttons: {start_conveyor: {preview: {accepted: true}}, stop_conveyor: {preview: {accepted: true}}}}],
      ["Feeder", ["start_feeder", "stop_feeder"], {state: "off", stateText: "Stopped", buttons: {start_feeder: {preview: {accepted: false}}, stop_feeder: {preview: {accepted: true}}}}],
      ["Bin A gate", ["open_gate", "close_gate"], {state: "commanded", stateText: "Opening…", buttons: {open_gate: {preview: {accepted: true}}, close_gate: {preview: {accepted: true}}}}]]) {
    const row = deviceRow(name, commands, COPY, noop);
    renderDeviceRow(row, data, COPY);
    $("sg-devices").appendChild(row);
  }
  // RecipeForm: applied values; type to see the changed state, clear a field to see the error.
  const recipe = recipeForm("sg-recipe", COPY, noop);
  renderRecipeForm(recipe, {applied: {recipe_a_kg: 300, recipe_b_kg: 200, recipe_c_kg: 0, hold_s: 10}}, COPY);
  recipe.addEventListener("input", () => renderRecipeForm(recipe, {applied: {recipe_a_kg: 300, recipe_b_kg: 200, recipe_c_kg: 0, hold_s: 10}}, COPY));
  $("sg-recipe-box").appendChild(recipe);
  // BatchProgress: at rest, loading, discharging.
  for (const [caption, data] of [["at rest", {state: "idle", loaded_kg: 0, target_kg: 500}],
                                 ["loading", {state: "loading", loaded_kg: 240, target_kg: 500}],
                                 ["discharging", {state: "discharging", loaded_kg: 500, target_kg: 500}]]) {
    const b = batchProgress(COPY);
    renderBatchProgress(b, data, COPY);
    $("sg-batch").appendChild(item(b, caption));
  }
  // ConditionToggle (click it) and MaintenanceAction.
  const jam = conditionToggle("Jam the feeder", COPY, (active) => renderConditionToggle(jam, {active}));
  renderConditionToggle(jam, {active: false});
  const slip = conditionToggle("Belt slips", COPY, noop); renderConditionToggle(slip, {active: true});
  const fix = maintenanceAction("Clear feeder obstruction", COPY, noop); renderMaintenanceAction(fix, {done: false});
  const fixed = maintenanceAction("Re-tension the belt", COPY, noop); renderMaintenanceAction(fixed, {done: true});
  $("sg-physical").append(item(jam, "inactive (try it)"), item(slip, "active"), item(fix, "available"), item(fixed, "done"));
})();
"""

# The components, each in every state it has, drawn by its real render
# function. Runs in the page after components.js and the UI copy.
GALLERY_JS = """
(function gallery() {
  const $ = (id) => document.getElementById(id);
  for (const state of BADGE_ORDER) {
    const badge = stateBadge();
    renderStateBadge(badge, {state}, COPY);
    $("sg-badges").appendChild(h("div", {class: "sg-item"}, badge, h("code", {class: "sg-caption"}, state)));
  }
  for (const [name, tag] of [["Hopper weight", "WT-105"], ["Chute plug switch", "LSH-103"], ["No identifier", null]]) {
    const chip = tagChip();
    renderTagChip(chip, {tag});
    $("sg-tags").appendChild(h("div", {class: "sg-item"}, h("span", {}, name, chip)));
  }
  const p = panel("sg-panel", "Alarms");
  p.lastChild.appendChild(h("p", {}, "A panel holds one region of the screen under a plain title."));
  const closed = drawer();
  renderDrawer(closed, {title: "History", count: 12});
  closed.lastChild.appendChild(h("p", {}, "Collapsed by default; the count says what is inside."));
  const open = drawer();
  renderDrawer(open, {title: "Raw I/O", count: null});
  open.setAttribute("open", "");
  open.lastChild.appendChild(h("p", {}, "Opened: no count shown when there is nothing to count."));
  for (const el of [p, closed, open]) $("sg-containers").appendChild(el);
})();
"""

# Step 7c's gallery. The test panel and verdict are drawn from real runs of a
# real test (a pass, and a fail from a deliberately broken controller), the
# same shapes the dashboard will hand them; built afresh, deterministically,
# each time the page is.
GALLERY_7C = """
(function results() {
  const $ = (id) => document.getElementById(id);
  const item = (el, caption) => h("div", {class: "sg-item"}, el, h("code", {class: "sg-caption"}, caption));
  const noop = () => {};
  // AlarmMarker: each class through its lifecycle.
  for (const cls of ["trip", "warn"]) for (const lifecycle of ["new", "acknowledged", "cleared"]) {
    const m = alarmMarker(); renderAlarmMarker(m, {cls, lifecycle});
    $("sg-markers").appendChild(item(h("span", {}, m), `${cls}, ${lifecycle}`));
  }
  // AlarmSummary: none, a warning, trips and warnings.
  for (const [caption, data] of [["none", {trips: 0, warnings: 0}], ["warning", {trips: 0, warnings: 1, unacknowledged: true}],
                                 ["trip", {trips: 1, warnings: 2, unacknowledged: true}]]) {
    const s = alarmSummary("#sg-alarms", COPY, null); renderAlarmSummary(s, data, COPY);
    $("sg-asum").appendChild(item(s, caption));
  }
  // AlarmList: every lifecycle, the first-out; then empty.
  const alarms = alarmList("sg-al", COPY);
  renderAlarmList(alarms, {alarms: SG_ALARMS}, COPY);
  const none = alarmList("sg-al-none", COPY); renderAlarmList(none, {alarms: []}, COPY);
  $("sg-alarms").append(alarms, item(none, "empty"));
  // HistoryList: live, newest first; a replay, "Now" marked (click an entry to move it).
  const live = historyList("live", COPY); renderHistoryList(live, {rows: SG_HISTORY}, COPY);
  const replay = historyList("replay", COPY, (t) => renderHistoryList(replay, {rows: SG_HISTORY, now: t}, COPY));
  renderHistoryList(replay, {rows: SG_HISTORY, now: 13}, COPY);
  $("sg-history").append(item(live, "live: newest first"), item(replay, "replay: in order, Now marked (try it)"));
  // Checklist.
  const steps = checklist();
  renderChecklist(steps, {steps: [{text: "Clear feeder obstruction", state: "done"}, {text: "Acknowledge", state: "done"},
    {text: "Reset", state: "blocked", why: "Can't reset yet: the chute is still plugged."}, {text: "Start", state: "pending"}]}, COPY);
  $("sg-checklist").appendChild(steps);
  // AllNormalCard: ready, running.
  for (const [caption, data] of [
      ["idle", {state: "idle", sentence: "Ready. Start runs the line from bin A.", action: {command: "start", preview: {accepted: true}, primary: true}}],
      ["running", {state: "running", sentence: "Running normally: feeding from bin A, hopper at 42\\u2009%.",
                   action: {command: "stop", preview: {accepted: true}, primary: true}}]]) {
    const card = allNormalCard(`sg-normal-${caption}`, COPY, noop); renderAllNormalCard(card, data, COPY);
    $("sg-allnormal").appendChild(item(card, caption));
  }
  // Readout: normal, suspect, lost.
  for (const [label, data] of [["Hopper weight", {value: 1912.4, unit: "kg", health: "normal", tag: "WT-105"}],
                               ["Belt scale", {value: 4.96, unit: "kg/s", decimals: 1, health: "suspect", tag: "FT-104"}],
                               ["Hopper weight", {value: 0, unit: "kg", health: "lost", tag: "WT-105"}]]) {
    const r = readout(label); renderReadout(r, data, COPY);
    $("sg-readouts").appendChild(item(r, data.health));
  }
  // Indicator: reached in each class, normal, faulted; with the words device detail shows.
  for (const [caption, data] of [["reached, trip", {state: "reached", cls: "trip", words: true}],
                                 ["reached, warning", {state: "reached", cls: "warn", words: true}],
                                 ["reached, running", {state: "reached", cls: "on", words: true}],
                                 ["normal", {state: "normal", cls: "trip", words: true}],
                                 ["faulted", {state: "faulted", cls: "warn", words: true}]]) {
    const i = indicator(); renderIndicator(i, data, COPY);
    $("sg-indicators").appendChild(item(i, caption));
  }
  // IOTable: the hopper weight changed this tick.
  const io = ioTable([{name: "WT-105", type: "AI", units: "kg", description: "Hopper weight"},
                      {name: "LSH-103", type: "DI", units: "", description: "Chute plug switch"},
                      {name: "M-103.RUN", type: "DO", units: "", description: "Feeder run command"}], COPY);
  renderIOTable(io, {values: {"WT-105": 812.5, "LSH-103": true, "M-103.RUN": false}, prev: {"WT-105": 810.25, "LSH-103": true, "M-103.RUN": false}});
  $("sg-io").appendChild(io);
  // ActionChip: every kind.
  for (const [kind, text] of [["operator", "Operator presses Start"], ["fault", "Someone presses the E-stop"],
                              ["repair", "The jam is cleared at the feeder"], ["process", "The hopper level is set to 85\\u2009%"]]) {
    const c = actionChip(); renderActionChip(c, {kind, text}, COPY);
    $("sg-chips").appendChild(item(c, kind));
  }
  // TestPanel: running, then passed, then failed -- the last two from real runs.
  const running = testPanel(SG_PLAN, COPY);
  renderTestPanel(running, {setup: "done", stages: [SG_PASS.stages[0], {status: "running", elapsed_s: 0.4}]}, COPY);
  const passed = testPanel(SG_PLAN, COPY); renderTestPanel(passed, {setup: "done", stages: SG_PASS.stages}, COPY);
  const failed = testPanel(SG_PLAN, COPY);
  renderTestPanel(failed, {setup: "done", stages: SG_FAIL.stages.map((st) => Object.assign({}, st, {deadline: true}))}, COPY);
  $("sg-tests").append(item(running, "running"), item(passed, "passed (a real run)"), item(failed, "failed (a real run, broken controller)"));
  // VerdictBlock: pass and fail, from the same runs.
  for (const [caption, summary] of [["pass", SG_PASS], ["fail", SG_FAIL]]) {
    const v = verdictBlock(); renderVerdictBlock(v, summary, COPY);
    $("sg-verdicts").appendChild(item(v, caption));
  }
  // RuntimeRow: the reference, one that agrees, one that doesn't.
  const runtimes = runtimeTable(COPY);
  renderRuntimeTable(runtimes, {rows: [
    {runtime_id: "python", runtime: "Python controller (in-process, lockstep)", verdict: "PASS", checks: "22/22", how: "reference run", agrees: null},
    {runtime_id: "modbus", runtime: "Python controller over Modbus TCP (lockstep)", verdict: "PASS", checks: "22/22",
     how: "lockstep: event log compared event by event -- identical", agrees: true},
    {runtime_id: "openplc", runtime: "OpenPLC Runtime over Modbus TCP (real time)", verdict: "FAIL", checks: "20/22",
     how: "real time: compared by verdict and checks (response times vary with the PLC's scan phase)", agrees: false}]}, COPY);
  $("sg-runtimes").appendChild(runtimes);
  // ScenarioCard: idle, running (every card locked), with a result.
  const test = {id: "sg-feeder-jam", title: "Feeder jam recovery", description: SG_PLAN.description, stages: SG_PLAN.stages.length};
  for (const [caption, data] of [["idle", {running: false, locked: false, result: null, watch: null}],
                                 ["running", {running: true, locked: true, result: null, watch: null}],
                                 ["last result", {running: false, locked: false, watch: "#sg-tests",
                                   result: {verdict: SG_PASS.verdict, checks: `${SG_PASS.checks_passed}/${SG_PASS.checks_evaluated} checks matched`}}]]) {
    const card = scenarioCard(Object.assign({}, test, {id: `${test.id}-${caption.replace(" ", "-")}`}), COPY, {run: noop, compare: noop});
    renderScenarioCard(card, data, COPY);
    $("sg-scenarios").appendChild(item(card, caption));
  }
})();
"""

SG_ALARMS = [
    {"id": "LSH-103.JAM", "text": "Feeder jammed: the discharge chute is plugged", "is_warning": False, "active": True,
     "acknowledged": False, "first_out": True},
    {"id": "LSL-111.LOW", "text": "Bin B is nearly empty", "is_warning": True, "active": True, "acknowledged": False,
     "first_out": False},
    {"id": "LSL-101.LOW", "text": "Bin A is nearly empty", "is_warning": True, "active": True, "acknowledged": True,
     "first_out": False},
    {"id": "M-103.FAULT", "text": "Feeder drive tripped", "is_warning": False, "active": False, "acknowledged": False,
     "first_out": False},
]

SG_HISTORY = [
    {"key": 1, "t": 0.0, "text": "You pressed Start", "tone": None, "tag": None},
    {"key": 2, "t": 6.2, "text": "The line is running", "tone": None, "tag": None},
    {"key": 3, "t": 12.34, "text": "The feeder jammed; the controller stopped the feed", "tone": "trip", "tag": "LSH-103"},
    {"key": 4, "t": 15.0, "text": "You acknowledged the alarms", "tone": None, "tag": None},
]

GALLERY_TEST = "faults/feeder_jam_recovery.yaml"
GALLERY_REGRESSION = "jam-trip-removed"


def _gallery_data() -> str:
    """The 7c gallery's fixtures as script constants: real runs of a real test."""
    from services.testing.regressions import REGRESSIONS
    from services.testing.runner import run_scenario
    from services.testing.scenario import Scenario
    from services.testing.verdict import plan, summarize
    from services.visualization.verify import SCENARIOS_DIR

    scenario = Scenario.load(SCENARIOS_DIR / GALLERY_TEST)
    runs = {}
    for name, regression in (("PASS", None), ("FAIL", GALLERY_REGRESSION)):
        result = run_scenario(scenario, line_cls=REGRESSIONS[regression].cls if regression else None)
        runs[name] = summarize(scenario, result, "python", root=SCENARIOS_DIR, regression=regression).to_dict()
    data = {"SG_PLAN": plan(scenario, root=SCENARIOS_DIR), "SG_PASS": runs["PASS"], "SG_FAIL": runs["FAIL"],
            "SG_ALARMS": SG_ALARMS, "SG_HISTORY": SG_HISTORY}
    return "\n".join(f"const {name} = {json.dumps(value, ensure_ascii=False, sort_keys=True).replace('</', '<' + chr(92) + '/')};"
                     for name, value in data.items())


def _icons(sprite: str) -> str:
    names = re.findall(r'<symbol id="i-([a-z-]+)"', sprite)
    return '<div class="sg-row">' + "".join(
        f'<span class="sg-icon"><svg class="c-icon" aria-hidden="true" focusable="false"><use href="#i-{n}"/></svg>'
        f'<code class="sg-caption">{n}</code></span>' for n in names) + "</div>"


def render(repo_url: str | None = None) -> str:
    """The style guide as one self-contained HTML page."""
    values = tk.tokens()
    css = tk.TOKENS_CSS.read_text(encoding="utf-8")
    components_css = (HERE / "components.css").read_text(encoding="utf-8")
    components_js = (HERE / "components.js").read_text(encoding="utf-8")
    sprite = (HERE / "icons.svg.html").read_text(encoding="utf-8")
    order = json.dumps(list(copytext.STATE_BADGES))
    source = (f' <a href="{escape(repo_url)}/blob/main/services/visualization/tokens.css">tokens.css</a>'
              if repo_url else " <code>services/visualization/tokens.css</code>")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Style guide · ControlLab</title>
<style>
{css}
{components_css}
{PAGE_CSS}
{_swatch_rules()}
</style>
</head>
<body>
{sprite}
<header>
<h1>ControlLab style guide</h1>
<p>Generated from the design tokens the dashboard, the replays and this demo are built from:{source}.
Nothing on this page is written by hand, so a change to a token changes this page too.</p>
<p class="muted">Light theme only. Colour never carries meaning alone: every state is also a shape and a word.
Green is not used anywhere; normal stays quiet.</p>
</header>
<main>
<h2 id="colour">Colour</h2>
{_colours(values)}
<h2 id="contrast">Contrast</h2>
<p>Every colour pair used for meaning, recomputed from the tokens each time this page is built.
Text needs 4.5 : 1; graphics, control borders and focus rings need 3 : 1.</p>
{_pairs(values)}
<h2 id="type">Type scale</h2>
<p>System fonts only, so every page works offline. Nothing is set below 12 px.</p>
{_type()}
<h2 id="space">Space</h2>
<p>A 4 px base. The page gutter is 20 px, 16 px on a phone.</p>
{_space(values)}
<h2 id="other">Size, shape, motion</h2>
<p>No shadows and no gradients. Under reduced motion every duration is zero.</p>
{_other(values)}
<h2 id="icons">Icons</h2>
<p>One in-house set on a 16 px grid, drawn in the colour of the text beside it. An icon never appears alone
and is hidden from screen readers; the words carry the meaning.</p>
{_icons(sprite)}
<h2 id="components">Components</h2>
<p>Each drawn by its real render function, the same code the dashboard and replays run, with the words from the
interface's copy table.</p>
<noscript><p>The components are drawn by the dashboard's own JavaScript. Turn JavaScript on to see them.</p></noscript>
<h3>State badge</h3>
<p class="muted">The line's state in fixed words, one badge in the status bar; TESTING appears beside it while a test
operates the line. Meaning is in the words: fill, outline and icon only reinforce them.</p>
<div class="sg-row" id="sg-badges"></div>
<h3>Tag chip</h3>
<p class="muted">A technical identifier, shown only while "Show technical identifiers" is on (on here). The plain name
always comes first.</p>
<div class="sg-row" id="sg-tags" data-ids="on"></div>
<h3>Panel and drawer</h3>
<p class="muted">A panel is a titled region. A drawer holds diagnostic or engineering detail, collapsed by default,
and opens without animation.</p>
<div class="sg-row"><div class="sg-stack" id="sg-containers"></div></div>
<h3>Command button</h3>
<p class="muted">A request to the controller. The expected next action is primary. An unavailable button stays focusable and
still sends when pressed: the controller decides, the preview only informs. Locked means a test is operating the line.</p>
<div class="sg-row" id="sg-commands"></div>
<h3>E-stop button</h3>
<p class="muted">The operator's safety pushbutton, apart from the controller requests: never unavailable, only locked while a
test runs. The same button releases it.</p>
<div class="sg-row" id="sg-estop"></div>
<h3>Segmented control</h3>
<p class="muted">The mode and the source bin. Arrow keys move between options; Enter or Space selects, because selecting sends a
request to the controller.</p>
<div class="sg-row" id="sg-seg"></div>
<h3>Permissive note</h3>
<p class="muted">Why an action is unavailable, before the press, or why it was refused, after it. A refusal is the controller's
answer, never shown as a trip.</p>
<div class="sg-row" id="sg-notes"></div>
<h3>Why can't I...? table</h3>
<p class="muted">Only what the controller reports as blocking each request; a permissive is never shown as met.</p>
<div class="sg-row" id="sg-ptable" data-ids="on"></div>
<h3>Device row</h3>
<p class="muted">One device in Manual: its name, its state in words with the picture's marker (solid on, outline off, dashed
while commanded but not confirmed), and its two requests.</p>
<div class="sg-row"><div class="sg-stack" id="sg-devices"></div></div>
<h3>Recipe form</h3>
<p class="muted">The batch recipe. It checks only that each entry is a number; whether the recipe fits is the controller's call.
Nothing typed is lost when the line updates.</p>
<div class="sg-row" id="sg-recipe-box"></div>
<h3>Batch progress</h3>
<div class="sg-row" id="sg-batch"></div>
<h3>Physical condition and maintenance action</h3>
<p class="muted">Test view only: things that happen to the equipment, and the repairs, in physical words. Never a controller verb.</p>
<div class="sg-row" id="sg-physical"></div>
<h3>Alarm marker</h3>
<p class="muted">An octagon for a trip, a triangle for a warning: filled while new, an outline once acknowledged, muted once
cleared but not yet acknowledged. It never flashes, and the words beside it carry the meaning.</p>
<div class="sg-row" id="sg-markers"></div>
<h3>Alarm summary</h3>
<p class="muted">The status bar's alarm count by class. The Show link's name includes the count.</p>
<div class="sg-row" id="sg-asum"></div>
<h3>Alarm list</h3>
<p class="muted">The latched alarms: new trips, new warnings, acknowledged, then cleared but not acknowledged. Each lifecycle is in
words; the alarm that started it is marked (hover or focus it for what that means).</p>
<div class="sg-row" data-ids="on"><div class="sg-stack" id="sg-alarms"></div></div>
<h3>History</h3>
<p class="muted">What happened, in plain words. Live, newest first; in a replay, in order, with the current moment marked Now and
each entry a jump.</p>
<div class="sg-row" id="sg-history" data-ids="on"></div>
<h3>Checklist</h3>
<p class="muted">The recovery steps. A step is done only when the line's data says so, never on a click; a blocked step says why.</p>
<div class="sg-row" id="sg-checklist"></div>
<h3>All-normal card</h3>
<p class="muted">The Operate rail when nothing is wrong: one sentence and the expected next action.</p>
<div class="sg-row" id="sg-allnormal"></div>
<h3>Readout</h3>
<p class="muted">A reading with its unit. A faulted instrument is striped and says so; a lost signal shows no number, because a
failed transmitter's value means nothing.</p>
<div class="sg-row" id="sg-readouts" data-ids="on"></div>
<h3>Indicator</h3>
<p class="muted">A switch. Reached: filled in its class colour, with a notch. Normal: hollow. Faulted: a dashed outline. The words
appear in device detail; elsewhere the indicator is part of its device's name.</p>
<div class="sg-row" id="sg-indicators"></div>
<h3>Raw I/O table</h3>
<p class="muted">Every tag, its signal, its type and value; the row that changed this tick is tinted.</p>
<div class="sg-row"><div class="sg-stack" id="sg-io"></div></div>
<h3>Action chip</h3>
<p class="muted">What a test stage does, marked by kind; the kind is also said to screen readers.</p>
<div class="sg-row" id="sg-chips"></div>
<h3>Test panel</h3>
<p class="muted">A test's setup and stages, each with its actions, checks and time limit. The passed and failed panels are real
runs of the feeder-jam test, the failed one against a deliberately broken controller.</p>
<div class="sg-row sg-cols" id="sg-tests"></div>
<h3>Verdict</h3>
<p class="muted">PASS or FAIL, how many checks matched, and where the run first departed from the test.</p>
<div class="sg-row sg-cols" id="sg-verdicts"></div>
<h3>Runtime comparison</h3>
<p class="muted">One row per runtime, each saying how it was compared; the first is the reference.</p>
<div class="sg-row"><div class="wrap" id="sg-runtimes"></div></div>
<h3>Test card</h3>
<p class="muted">A test to run. While any test operates the line, every card's buttons are locked.</p>
<div class="sg-row sg-cols" id="sg-scenarios"></div>
</main>
<footer>More components join this page as each is built.</footer>
<script>
const COPY = {copytext.ui_copy_json()};
const BADGE_ORDER = {order};
{components_js}
{GALLERY_JS}
{GALLERY_7B}
{_gallery_data()}
{GALLERY_7C}
</script>
</body>
</html>
"""
