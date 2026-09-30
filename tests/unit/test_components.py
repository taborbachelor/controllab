"""The components (frontend redesign, build step 7), run in Node against a
small in-house DOM (tests/unit/mini_dom.js) that counts every write: each
component renders every state it has, rendering the same data twice writes
nothing (so focus and screen readers are left alone), new data patches the
existing nodes instead of rebuilding them, and the words come from
copytext.py, which covers every line state. Skipped where Node isn't
installed."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from services.control.line_state import LineState
from services.visualization import copytext
from services.visualization.page import HERE

NODE = shutil.which("node")
MINI_DOM = Path(__file__).with_name("mini_dom.js")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

# The in-house icon set the specification lists (section 7.1).
SPEC_ICONS = ("octagon", "triangle", "circle-info", "check", "cross", "lock", "hand", "clock", "flask",
              "batch", "wrench", "estop", "play", "pause", "restart", "question", "link", "chevron")


def run(body: str, tmp_path: Path):
    """Runs `body` after the mini DOM, components.js and the UI copy; returns
    what the body printed with out(...), parsed from JSON."""
    script = tmp_path / "components_test.js"
    script.write_text(
        MINI_DOM.read_text(encoding="utf-8") + "\n" + (HERE / "components.js").read_text(encoding="utf-8")
        + f"\nconst COPY = {copytext.ui_copy_json()};\nconst out = (x) => console.log(JSON.stringify(x));\n" + body,
        encoding="utf-8")
    result = subprocess.run([NODE, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def sprite_icons() -> set[str]:
    return set(re.findall(r'<symbol id="i-([a-z-]+)"', (HERE / "icons.svg.html").read_text(encoding="utf-8")))


def test_every_line_state_has_a_badge_in_the_copy():
    states = {s.name.lower() for s in LineState}
    assert states <= set(copytext.STATE_BADGES)
    assert set(copytext.STATE_BADGES) - states == {"external", "testing"}


def test_the_icon_set_is_the_specified_one_and_every_badge_icon_exists():
    assert sprite_icons() == set(SPEC_ICONS)
    for state, badge in copytext.STATE_BADGES.items():
        assert badge["icon"] is None or badge["icon"] in sprite_icons(), state


@needs_node
def test_patch_writes_only_what_differs(tmp_path):
    got = run("""
      const el = document.createElement("span");
      const first = patch(el, {text: "Ready", attrs: {"data-state": "idle", hidden: true, title: null}});
      const again = patch(el, {text: "Ready", attrs: {"data-state": "idle", hidden: true, title: null}});
      const off = patch(el, {attrs: {hidden: false}});
      out({first, again, off, html: el.toHTML()});
    """, tmp_path)
    assert got == {"first": 3, "again": 0, "off": 1, "html": '<span data-state="idle">Ready</span>'}


@needs_node
@pytest.mark.parametrize("state", sorted(copytext.STATE_BADGES))
def test_the_state_badge_shows_every_state_in_its_fixed_words(state, tmp_path):
    got = run(f"""
      const el = stateBadge();
      renderStateBadge(el, {{state: {json.dumps(state)}}}, COPY);
      DOM.writes = 0;
      renderStateBadge(el, {{state: {json.dumps(state)}}}, COPY);
      out({{text: el.textContent, variant: el.getAttribute("data-variant"), iconHidden: el.firstChild.hasAttribute("hidden"),
           href: el.firstChild.firstChild.getAttribute("href"), writesOnRepeat: DOM.writes}});
    """, tmp_path)
    badge = copytext.STATE_BADGES[state]
    assert got["text"] == badge["text"] and got["variant"] == badge["variant"]
    assert got["iconHidden"] == (badge["icon"] is None)
    if badge["icon"]:
        assert got["href"] == f"#i-{badge['icon']}"
    assert got["writesOnRepeat"] == 0


@needs_node
def test_a_state_change_patches_the_same_badge_and_marks_it_fresh(tmp_path):
    got = run("""
      const el = stateBadge();
      renderStateBadge(el, {state: "idle"}, COPY);
      const firstRender = el.hasAttribute("data-fresh");
      const node = el.lastChild;
      renderStateBadge(el, {state: "faulted"}, COPY);
      out({sameNode: node === el.lastChild, text: el.textContent, fresh: el.hasAttribute("data-fresh"), firstRender});
    """, tmp_path)
    assert got == {"sameNode": True, "text": "TRIPPED", "fresh": True, "firstRender": False}


@needs_node
def test_an_unknown_state_is_an_error_not_a_blank_badge(tmp_path):
    got = run("""
      let message = null;
      try { renderStateBadge(stateBadge(), {state: "flying"}, COPY); } catch (e) { message = e.message; }
      out(message);
    """, tmp_path)
    assert got == 'no badge for state "flying"'


@needs_node
def test_the_tag_chip_shows_an_identifier_or_nothing(tmp_path):
    got = run("""
      const el = tagChip();
      renderTagChip(el, {tag: null});
      const none = el.hasAttribute("hidden");
      renderTagChip(el, {tag: "LSH-103"});
      DOM.writes = 0;
      renderTagChip(el, {tag: "LSH-103"});
      out({none, shown: !el.hasAttribute("hidden"), text: el.textContent, writesOnRepeat: DOM.writes, tag: el.tagName});
    """, tmp_path)
    assert got == {"none": True, "shown": True, "text": "LSH-103", "writesOnRepeat": 0, "tag": "CODE"}


@needs_node
def test_the_panel_is_a_labelled_section(tmp_path):
    got = run("""
      const el = panel("alarms", "Alarms");
      out({tag: el.tagName, labelledby: el.getAttribute("aria-labelledby"),
           heading: el.firstChild.tagName, headingId: el.firstChild.getAttribute("id"), title: el.firstChild.textContent});
    """, tmp_path)
    assert got == {"tag": "SECTION", "labelledby": "alarms-title", "heading": "H2", "headingId": "alarms-title", "title": "Alarms"}


@needs_node
def test_the_drawer_is_collapsed_details_and_keeps_focus_on_update(tmp_path):
    got = run("""
      const el = drawer();
      renderDrawer(el, {title: "History", count: null});
      const countHidden = el.firstChild.children[2].hasAttribute("hidden");
      const summary = el.firstChild;
      summary.focus();
      renderDrawer(el, {title: "History", count: 12});
      DOM.writes = 0;
      renderDrawer(el, {title: "History", count: 12});
      out({tag: el.tagName, open: el.hasAttribute("open"), countHidden, count: summary.children[2].textContent,
           focusKept: document.activeElement === summary && el.contains(summary), writesOnRepeat: DOM.writes});
    """, tmp_path)
    assert got == {"tag": "DETAILS", "open": False, "countHidden": True, "count": "12", "focusKept": True, "writesOnRepeat": 0}


# ======== Step 7b: the console controls.

def test_every_operator_command_has_a_label_and_every_batch_state_a_step():
    from services.control.line_controller import COMMANDS
    assert set(copytext.COMMAND_LABELS) == set(COMMANDS)
    steps = [s for s, _ in copytext.CONTROLS["batch_steps"]]
    assert steps == ["loading", "processing", "discharging", "cleaning"]


@needs_node
def test_the_test_dom_is_as_strict_as_a_browser_about_children(tmp_path):
    got = run("""
      const el = h("div", {}, h("span"), h("span"));
      out({length: el.children.length, second: el.children[1].tagName, hasSome: typeof el.children.some,
           asArray: Array.from(el.children).length});
    """, tmp_path)
    assert got == {"length": 2, "second": "SPAN", "hasSome": "undefined", "asArray": 2}


@needs_node
def test_the_command_button_shows_the_controllers_answer_and_always_sends(tmp_path):
    got = run("""
      const pressed = [];
      const el = commandButton("reset", COPY, (c) => pressed.push(c));
      const look = () => ({state: el.getAttribute("data-state"), disabled: el.hasAttribute("disabled"),
        ariaDisabled: el.getAttribute("aria-disabled"), busy: el.getAttribute("aria-busy"), primary: el.hasAttribute("data-primary"),
        icon: el.firstChild.hasAttribute("hidden") ? null : el.firstChild.firstChild.getAttribute("href"), label: el.lastChild.textContent});
      const r = {};
      renderCommandButton(el, {preview: {accepted: true}, primary: true}, COPY); r.available = look();
      renderCommandButton(el, {preview: {accepted: false}, describedby: "reset-why"}, COPY); r.unavailable = look();
      r.describedby = el.getAttribute("aria-describedby");
      el.click(); r.pressedWhileUnavailable = pressed.slice();
      renderCommandButton(el, {preview: {accepted: false}, sent: true}, COPY); r.sent = look();
      renderCommandButton(el, {preview: null}, COPY); r.noPreview = look();
      renderCommandButton(el, {preview: {accepted: true}, locked: true}, COPY); r.locked = look();
      el.click(); r.pressedWhileLocked = pressed.length;
      DOM.writes = 0; renderCommandButton(el, {preview: {accepted: true}, locked: true}, COPY); r.writesOnRepeat = DOM.writes;
      out(r);
    """, tmp_path)
    assert got["available"] == {"state": "available", "disabled": False, "ariaDisabled": None, "busy": None,
                                "primary": True, "icon": None, "label": "Reset"}
    assert got["unavailable"] == {"state": "unavailable", "disabled": False, "ariaDisabled": "true", "busy": None,
                                  "primary": False, "icon": "#i-circle-info", "label": "Reset"}
    assert got["describedby"] == "reset-why"
    assert got["pressedWhileUnavailable"] == ["reset"], "the preview informs, it never blocks a press (spec 4.1)"
    assert got["sent"]["label"] == "Sent…" and got["sent"]["busy"] == "true"
    assert got["noPreview"]["state"] == "available" and got["noPreview"]["icon"] is None
    assert got["locked"]["disabled"] and got["locked"]["icon"] == "#i-lock" and got["pressedWhileLocked"] == 1
    assert got["writesOnRepeat"] == 0


@needs_node
def test_the_estop_button_presses_and_releases_and_is_never_unavailable(tmp_path):
    got = run("""
      const asks = [];
      const el = estopButton(COPY, (p) => asks.push(p));
      const b = el.firstChild;
      renderEStopButton(el, {pressed: false}, COPY);
      const released = {label: b.lastChild.textContent, pressed: b.getAttribute("aria-pressed"), status: el.lastChild.hasAttribute("hidden")};
      b.click();
      renderEStopButton(el, {pressed: true}, COPY);
      const pressed = {label: b.lastChild.textContent, pressed: b.getAttribute("aria-pressed"), status: el.lastChild.hasAttribute("hidden"),
                       statusText: el.lastChild.textContent};
      b.click();
      renderEStopButton(el, {pressed: true, locked: true, describedby: "lock-note"}, COPY);
      b.click();
      out({released, pressed, asks, locked: b.hasAttribute("disabled"), describedby: b.getAttribute("aria-describedby"),
           everAriaDisabled: b.hasAttribute("aria-disabled")});
    """, tmp_path)
    assert got["released"] == {"label": "Press E-stop", "pressed": "false", "status": True}
    assert got["pressed"] == {"label": "Release E-stop", "pressed": "true", "status": False, "statusText": "E-stop pressed"}
    assert got["asks"] == [True, False], "a locked E-stop sends nothing"
    assert got["locked"] and got["describedby"] == "lock-note" and not got["everAriaDisabled"]


@needs_node
def test_the_segmented_control_never_selects_on_an_arrow_key(tmp_path):
    got = run("""
      const chosen = [];
      const el = segmentedControl("Mode", [{value: "select_auto", label: "Auto"}, {value: "select_manual", label: "Manual"},
                                           {value: "select_batch", label: "Batch"}], (v) => chosen.push(v));
      const data = {selected: "select_auto", unavailable: {select_batch: true}, describedby: {select_batch: "why-batch"}};
      renderSegmentedControl(el, data);
      const [auto, manual, batch] = Array.from(el.children);
      const initial = {role: el.getAttribute("role"), checked: auto.getAttribute("aria-checked"),
                       tabs: [auto, manual, batch].map((b) => b.getAttribute("tabindex")),
                       batchDisabled: batch.getAttribute("aria-disabled"), batchWhy: batch.getAttribute("aria-describedby")};
      auto.focus();
      const ev = auto.dispatch("keydown", {key: "ArrowRight"});
      const afterArrow = {focused: document.activeElement === manual, chosen: chosen.slice(), prevented: ev.defaultPrevented,
                          tabs: [auto, manual, batch].map((b) => b.getAttribute("tabindex"))};
      renderSegmentedControl(el, data);
      const tabsKeptWhileFocused = [auto, manual, batch].map((b) => b.getAttribute("tabindex"));
      manual.click(); batch.click();
      DOM.writes = 0;
      renderSegmentedControl(el, data);
      out({initial, afterArrow, tabsKeptWhileFocused, chosen, writesOnRepeat: DOM.writes});
    """, tmp_path)
    assert got["initial"] == {"role": "radiogroup", "checked": "true", "tabs": ["0", "-1", "-1"],
                              "batchDisabled": "true", "batchWhy": "why-batch"}
    assert got["afterArrow"] == {"focused": True, "chosen": [], "prevented": True, "tabs": ["-1", "0", "-1"]}
    assert got["tabsKeptWhileFocused"] == ["-1", "0", "-1"], "a re-render must not pull the tab stop away from the operator"
    assert got["chosen"] == ["select_manual", "select_batch"], "an unavailable option still sends; the controller decides"
    assert got["writesOnRepeat"] == 0


@needs_node
def test_the_permissive_note_tells_a_reason_from_a_refusal(tmp_path):
    got = run("""
      const el = permissiveNote("start-why");
      renderPermissiveNote(el, {kind: null});
      const hidden = el.hasAttribute("hidden");
      renderPermissiveNote(el, {kind: "preview", text: "Can't start yet: bin A is nearly empty."});
      const preview = [el.getAttribute("data-kind"), el.firstChild.firstChild.getAttribute("href"), el.lastChild.textContent];
      renderPermissiveNote(el, {kind: "refused", text: "Start refused: bin A is nearly empty."});
      const refused = [el.getAttribute("data-kind"), el.firstChild.firstChild.getAttribute("href")];
      out({hidden, preview, refused, id: el.getAttribute("id")});
    """, tmp_path)
    assert got["hidden"] and got["id"] == "start-why"
    assert got["preview"] == ["preview", "#i-circle-info", "Can't start yet: bin A is nearly empty."]
    assert got["refused"] == ["refused", "#i-cross"], "a refusal is marked apart from a reason, and never as a trip"


@needs_node
def test_the_permissive_table_lists_only_reported_blocking_reasons(tmp_path):
    got = run("""
      const el = permissiveTable();
      const data = {requests: [
        {label: "Start", rows: [{text: "Bin A is nearly empty", tag: "BIN_LOW"}], empty: "Nothing is blocking Start."},
        {label: "Reset", rows: [], empty: "Nothing is blocking Reset."}]};
      renderPermissiveTable(el, data);
      const html = el.toHTML();
      DOM.writes = 0; renderPermissiveTable(el, data); const writesOnRepeat = DOM.writes;
      renderPermissiveTable(el, {requests: [], note: "This controller decides when you press."});
      out({html, writesOnRepeat, noPreview: el.textContent});
    """, tmp_path)
    assert got["html"].count('data-state="blocking"') == 1 and got["html"].count('data-state="clear"') == 1
    assert "Bin A is nearly empty" in got["html"] and "Nothing is blocking Reset." in got["html"]
    assert got["writesOnRepeat"] == 0
    assert got["noPreview"] == "This controller decides when you press."


@needs_node
def test_the_device_row_is_a_labelled_group_of_state_and_buttons(tmp_path):
    got = run("""
      const pressed = [];
      const el = deviceRow("Conveyor", ["start_conveyor", "stop_conveyor"], COPY, (c) => pressed.push(c));
      const data = {state: "commanded", stateText: "Starting…",
        buttons: {start_conveyor: {preview: {accepted: true}}, stop_conveyor: {preview: {accepted: true}}}};
      renderDeviceRow(el, data, COPY);
      const [start, stop] = Array.from(el.children[2].children);
      start.click();
      DOM.writes = 0;
      renderDeviceRow(el, data, COPY);
      out({role: el.getAttribute("role"), label: el.getAttribute("aria-label"), state: el.children[1].getAttribute("data-state"),
           stateText: el.children[1].textContent, buttons: [start.textContent, stop.textContent], pressed, writesOnRepeat: DOM.writes});
    """, tmp_path)
    assert got == {"role": "group", "label": "Conveyor", "state": "commanded", "stateText": "Starting…",
                   "buttons": ["Start", "Stop"], "pressed": ["start_conveyor"], "writesOnRepeat": 0}


@needs_node
def test_the_recipe_form_keeps_what_was_typed_and_checks_only_that_it_is_a_number(tmp_path):
    got = run("""
      const applied = [];
      const el = recipeForm("recipe", COPY, (v) => applied.push(v));
      const data = {applied: {recipe_a_kg: 300, recipe_b_kg: 200, recipe_c_kg: 0, hold_s: 10}};
      renderRecipeForm(el, data, COPY);
      const inputs = Array.from(el.firstChild.children).map((f) => f.children[1]);
      const filled = inputs.map((i) => i.value);
      const settled = el.lastChild.textContent;
      inputs[0].value = "450"; inputs[0].dispatch("input");
      renderRecipeForm(el, data, COPY);
      const kept = inputs[0].value, changed = el.lastChild.textContent;
      inputs[1].value = "-5"; inputs[1].dispatch("input");
      const invalid = [inputs[1].getAttribute("aria-invalid"), inputs[1].parentNode.lastChild.hasAttribute("hidden")];
      el.dispatch("submit");
      const afterBadSubmit = applied.length;
      inputs[1].value = "5000"; inputs[1].dispatch("input");
      el.dispatch("submit");
      out({filled, settled, kept, changed, invalid, afterBadSubmit, applied,
           label: el.firstChild.children[0].firstChild.textContent, unit: el.firstChild.children[3].children[2].textContent});
    """, tmp_path)
    assert got["filled"] == ["300", "200", "0", "10"] and got["settled"] == "Applied."
    assert got["kept"] == "450" and got["changed"] == "Changed, not applied yet."
    assert got["invalid"] == ["true", False] and got["afterBadSubmit"] == 0
    # 5,000 kg may be too much for the hopper: that is the controller's call (RECIPE_TOO_LARGE), not the form's.
    assert got["applied"] == [{"recipe_a_kg": 450, "recipe_b_kg": 5000, "recipe_c_kg": 0, "hold_s": 10}]
    assert got["label"] == "Bin A" and got["unit"] == "s"


@needs_node
def test_batch_progress_marks_the_current_step_and_the_load(tmp_path):
    got = run("""
      const el = batchProgress(COPY);
      const look = () => ({current: Array.from(el.firstChild.children).map((li) => li.getAttribute("aria-current")),
                           done: Array.from(el.firstChild.children).map((li) => li.hasAttribute("data-done")),
                           loaded: el.lastChild.hasAttribute("hidden") ? null : el.lastChild.textContent});
      renderBatchProgress(el, {state: "idle", loaded_kg: 0, target_kg: 500}, COPY); const idle = look();
      renderBatchProgress(el, {state: "loading", loaded_kg: 240.4, target_kg: 500}, COPY); const loading = look();
      renderBatchProgress(el, {state: "discharging", loaded_kg: 500, target_kg: 500}, COPY); const discharging = look();
      DOM.writes = 0; renderBatchProgress(el, {state: "discharging", loaded_kg: 500, target_kg: 500}, COPY);
      out({idle, loading, discharging, writesOnRepeat: DOM.writes,
           labels: Array.from(el.firstChild.children).map((li) => li.textContent)});
    """, tmp_path)
    assert got["idle"] == {"current": [None] * 4, "done": [False] * 4, "loaded": None}
    assert got["loading"] == {"current": ["step", None, None, None], "done": [False] * 4, "loaded": "Loaded 240 kg of 500 kg"}
    assert got["discharging"] == {"current": [None, None, "step", None], "done": [True, True, False, False], "loaded": None}
    assert got["labels"] == ["Load", "Hold", "Discharge", "Clean out"] and got["writesOnRepeat"] == 0


@needs_node
def test_a_condition_toggle_and_a_maintenance_action_speak_physically(tmp_path):
    got = run("""
      const toggles = [], repairs = [];
      const t = conditionToggle("Jam the feeder", COPY, (a) => toggles.push(a));
      renderConditionToggle(t, {active: false}); t.click();
      renderConditionToggle(t, {active: true});
      const active = [t.getAttribute("aria-pressed"), t.lastChild.hasAttribute("hidden"), t.textContent]; t.click();
      const m = maintenanceAction("Clear feeder obstruction", COPY, () => repairs.push(1));
      renderMaintenanceAction(m, {done: false}); m.click();
      renderMaintenanceAction(m, {done: true}); m.click();
      out({toggles, active, repairs: repairs.length, maint: m.textContent, maintDone: m.getAttribute("aria-disabled"),
           maintIcon: m.firstChild.firstChild.getAttribute("href")});
    """, tmp_path)
    assert got["toggles"] == [True, False] and got["active"] == ["true", False, "Jam the feederActive"]
    assert got["repairs"] == 1, "a done repair is not repeated"
    assert got["maint"] == "Maintenance action:Clear feeder obstructionDone"
    assert got["maintDone"] == "true" and got["maintIcon"] == "#i-check"


# ======== Step 7c: alarms, history, readings and test results.

def real_run(file: str, regression: str | None = None) -> tuple[dict, dict]:
    """A real test's plan and the summary of a real run of it (with a
    deliberate regression when asked): the shapes the components will get."""
    from services.testing.regressions import REGRESSIONS
    from services.testing.runner import run_scenario
    from services.testing.scenario import Scenario
    from services.testing.verdict import plan, summarize
    from services.visualization.verify import SCENARIOS_DIR
    scenario = Scenario.load(SCENARIOS_DIR / file)
    result = run_scenario(scenario, line_cls=REGRESSIONS[regression].cls if regression else None)
    summary = summarize(scenario, result, "python", root=SCENARIOS_DIR, regression=regression).to_dict()
    return plan(scenario, root=SCENARIOS_DIR), summary


def test_the_copy_has_words_for_every_kind_status_and_verdict_the_runner_reports():
    from services.testing import verdict
    assert set(copytext.ACTION_KINDS) == set(verdict.KINDS)
    for kind in copytext.ACTION_KINDS.values():
        assert kind["icon"] in sprite_icons()
    assert set(copytext.TESTS["check_status"]) == set(verdict._MARK)
    # Every status a StageSummary can carry, plus the two a live run adds before its outcome.
    assert set(copytext.TESTS["stage_status"]) >= {"pending", "running", "passed", "failed", "not_run", "not_observable"}
    assert set(copytext.ALARMS["lifecycle"]) == {"new", "acknowledged", "cleared"}


def test_the_7c_copy_follows_the_copy_rules():
    """Physical and maintenance words never borrow a controller verb, and no
    fixed word is an identifier (spec 5.4)."""
    controller_verbs = re.compile(r"\b(Start|Stop|Reset|Acknowledge)\b")
    for kind in ("fault", "repair", "process"):
        assert not controller_verbs.search(copytext.ACTION_KINDS[kind]["text"])
    words = json.dumps({k: getattr(copytext, k) for k in ("ALARMS", "HISTORY", "READINGS", "CARDS", "TESTS")})
    assert not re.search(r"\b[A-Z]{1,4}-\d{3}\b", words), "a tag in the interface's fixed words"


@needs_node
def test_a_keyed_list_moves_only_what_must_move_so_focus_survives(tmp_path):
    got = run("""
      const list = h("ul");
      const make = (item) => h("li", {}, h("button", {}, item.name));
      const update = (li, item) => patch(li.firstChild, {text: item.name});
      reconcile(list, [{id: "a", name: "A"}, {id: "b", name: "B"}], (x) => x.id, make, update);
      const b = list.children[1], button = b.firstChild;
      button.focus();
      reconcile(list, [{id: "new", name: "New"}, {id: "a", name: "A"}, {id: "b", name: "B"}], (x) => x.id, make, update);
      const afterInsert = {order: Array.from(list.children).map((li) => li.getAttribute("data-key")),
                           sameNode: list.children[2] === b, focusKept: document.activeElement === button};
      DOM.writes = 0;
      reconcile(list, [{id: "new", name: "New"}, {id: "a", name: "A"}, {id: "b", name: "B"}], (x) => x.id, make, update);
      const writesOnRepeat = DOM.writes;
      reconcile(list, [{id: "b", name: "B2"}], (x) => x.id, make, update);
      out({afterInsert, writesOnRepeat, left: list.textContent, stillB: list.children[0] === b});
    """, tmp_path)
    assert got["afterInsert"] == {"order": ["new", "a", "b"], "sameNode": True, "focusKept": True}
    assert got["writesOnRepeat"] == 0
    assert got["left"] == "B2" and got["stillB"]


@needs_node
def test_the_test_dom_blurs_a_focused_node_that_is_moved_as_a_browser_does(tmp_path):
    got = run("""
      const list = h("ul", {}, h("li"), h("li", {}, h("button")));
      const button = list.children[1].firstChild;
      button.focus();
      list.insertBefore(list.children[1], list.children[0]);
      out({focused: document.activeElement === button, tag: button.tagName, svg: h("svg").tagName});
    """, tmp_path)
    assert got == {"focused": False, "tag": "BUTTON", "svg": "svg"}


@needs_node
def test_the_alarm_marker_is_an_octagon_for_a_trip_and_a_triangle_for_a_warning(tmp_path):
    got = run("""
      const m = alarmMarker();
      const look = () => [m.firstChild.getAttribute("href"), m.getAttribute("data-lifecycle"), m.getAttribute("aria-hidden")];
      renderAlarmMarker(m, {cls: "trip", lifecycle: "new"}); const trip = look();
      renderAlarmMarker(m, {cls: "warn", lifecycle: "acknowledged"}); const warn = look();
      out({trip, warn, lifecycles: [{active: true, acknowledged: false}, {active: true, acknowledged: true},
                                    {active: false, acknowledged: false}].map(alarmLifecycle)});
    """, tmp_path)
    assert got["trip"] == ["#i-octagon", "new", "true"] and got["warn"] == ["#i-triangle", "acknowledged", "true"]
    assert got["lifecycles"] == ["new", "acknowledged", "cleared"]


@needs_node
def test_the_alarm_summary_names_its_count_in_the_link(tmp_path):
    got = run("""
      const shown = [];
      const el = alarmSummary("#alarms", COPY, () => shown.push(1));
      const [marker, counts, link] = Array.from(el.children);
      const look = () => ({state: el.getAttribute("data-state"), text: counts.textContent, link: link.getAttribute("aria-label"),
                           linkHidden: link.hasAttribute("hidden"), marker: marker.hasAttribute("hidden") ? null : marker.firstChild.getAttribute("href")});
      renderAlarmSummary(el, {trips: 0, warnings: 0}, COPY); const none = look();
      renderAlarmSummary(el, {trips: 0, warnings: 1, unacknowledged: true}, COPY); const warn = look();
      renderAlarmSummary(el, {trips: 1, warnings: 2, unacknowledged: true}, COPY); const trip = look();
      const ev = link.click();
      DOM.writes = 0; renderAlarmSummary(el, {trips: 1, warnings: 2, unacknowledged: true}, COPY);
      out({none, warn, trip, shown: shown.length, prevented: ev.defaultPrevented, writesOnRepeat: DOM.writes});
    """, tmp_path)
    assert got["none"] == {"state": "none", "text": "No alarms", "link": None, "linkHidden": True, "marker": None}
    assert got["warn"]["text"] == "1 warning" and got["warn"]["marker"] == "#i-triangle"
    assert got["trip"] == {"state": "trip", "text": "1 trip alarm · 2 warnings", "link": "1 trip alarm, 2 warnings, show",
                           "linkHidden": False, "marker": "#i-octagon"}
    assert got["shown"] == 1 and got["prevented"] and got["writesOnRepeat"] == 0


ALARMS_FIXTURE = [
    {"id": "LSL-101.LOW", "text": "Bin A is nearly empty", "is_warning": True, "active": True, "acknowledged": True, "first_out": False},
    {"id": "M-103.FAULT", "text": "Feeder drive tripped", "is_warning": False, "active": False, "acknowledged": False, "first_out": False},
    {"id": "LSH-103.JAM", "text": "Feeder jammed", "is_warning": False, "active": True, "acknowledged": False, "first_out": True},
    {"id": "LSL-111.LOW", "text": "Bin B is nearly empty", "is_warning": True, "active": True, "acknowledged": False, "first_out": False},
]


@needs_node
def test_the_alarm_list_orders_by_lifecycle_and_says_each_in_words(tmp_path):
    got = run(f"""
      const el = alarmList("al", COPY);
      renderAlarmList(el, {{alarms: []}}, COPY);
      const empty = [el.firstChild.hasAttribute("hidden"), el.lastChild.hasAttribute("hidden"), el.firstChild.textContent];
      const alarms = {json.dumps(ALARMS_FIXTURE)};
      renderAlarmList(el, {{alarms}}, COPY);
      const rows = Array.from(el.lastChild.lastChild.children);
      const look = rows.map((tr) => ({{id: tr.getAttribute("data-key"), status: tr.lastChild.textContent,
        isNew: !tr.firstChild.firstChild.children[1].hasAttribute("hidden"), first: !tr.firstChild.firstChild.children[4].hasAttribute("hidden")}}));
      const cell = rows[0].firstChild.firstChild, first = cell.children[4];
      const help = first.getAttribute("aria-describedby");
      const helpText = cell.children[5].getAttribute("id") === help ? cell.children[5].textContent : null;
      first.focus();
      alarms.push({{id: "M-104.OL", text: "Conveyor overload", is_warning: false, active: true, acknowledged: false, first_out: false}});
      renderAlarmList(el, {{alarms}}, COPY);
      const focusKept = document.activeElement === first;
      DOM.writes = 0; renderAlarmList(el, {{alarms}}, COPY);
      out({{empty, look, helpText, focusKept, writesOnRepeat: DOM.writes,
            order: Array.from(el.lastChild.lastChild.children).map((tr) => tr.getAttribute("data-key"))}});
    """, tmp_path)
    assert got["empty"] == [False, True, "No alarms."]
    assert got["look"] == [
        {"id": "LSH-103.JAM", "status": "Trip · New: active, not acknowledged", "isNew": True, "first": True},
        {"id": "LSL-111.LOW", "status": "Warning · New: active, not acknowledged", "isNew": True, "first": False},
        {"id": "LSL-101.LOW", "status": "Warning · Acknowledged, still active", "isNew": False, "first": False},
        {"id": "M-103.FAULT", "status": "Trip · Cleared, not acknowledged", "isNew": False, "first": False},
    ]
    assert got["helpText"] == "The first alarm; the others followed from it."
    # A second new trip keeps the server's order within the group, so the first-out row doesn't move.
    assert got["order"] == ["LSH-103.JAM", "M-104.OL", "LSL-111.LOW", "LSL-101.LOW", "M-103.FAULT"]
    assert got["focusKept"] and got["writesOnRepeat"] == 0


HISTORY_FIXTURE = [
    {"key": 1, "t": 0.0, "text": "You pressed Start", "tone": None, "tag": None},
    {"key": 2, "t": 12.34, "text": "The feeder jammed", "tone": "trip", "tag": "LSH-103"},
    {"key": 3, "t": 15.0, "text": "You acknowledged the alarms", "tone": None, "tag": None},
]


@needs_node
def test_live_history_is_newest_first_and_only_adds_what_is_new(tmp_path):
    got = run(f"""
      const el = historyList("live", COPY);
      const rows = {json.dumps(HISTORY_FIXTURE)};
      renderHistoryList(el, {{rows: []}}, COPY);
      const emptyShown = !el.firstChild.hasAttribute("hidden");
      renderHistoryList(el, {{rows: rows.slice(0, 2)}}, COPY);
      const kept = el.lastChild.children[0];
      DOM.writes = 0;
      renderHistoryList(el, {{rows}}, COPY);
      const writesForOne = DOM.writes;
      DOM.writes = 0;
      renderHistoryList(historyList("live", COPY), {{rows: rows.slice(2)}}, COPY);
      const writesDrawingItAlone = DOM.writes;
      const items = Array.from(el.lastChild.children);
      out({{emptyShown, writesForOne, writesDrawingItAlone, keptSame: items[1] === kept,
            text: items.map((li) => li.textContent), tone: items[1].getAttribute("data-tone"),
            buttons: el.toHTML().includes("<button")}});
    """, tmp_path)
    assert got["emptyShown"]
    assert got["text"] == ["15.0 sYou acknowledged the alarmsNow", "12.3 sThe feeder jammedLSH-103Now",
                           "0.0 sYou pressed StartNow"]
    assert got["keptSame"] and got["tone"] == "trip" and not got["buttons"]
    assert got["writesForOne"] <= got["writesDrawingItAlone"], "one new event must not re-render the others"


@needs_node
def test_replay_history_is_chronological_marks_now_and_jumps(tmp_path):
    got = run(f"""
      const jumps = [];
      const el = historyList("replay", COPY, (t) => jumps.push(t));
      renderHistoryList(el, {{rows: {json.dumps(HISTORY_FIXTURE)}, now: 13}}, COPY);
      const items = Array.from(el.lastChild.children);
      const look = items.map((li) => [li.getAttribute("aria-current"), li.hasAttribute("data-future"),
                                      !li.firstChild.children[4].hasAttribute("hidden")]);
      items[2].firstChild.click();
      items[1].firstChild.children[2].click();
      out({{look, jumps, order: items.map((li) => li.getAttribute("data-key"))}});
    """, tmp_path)
    assert got["order"] == ["1", "2", "3"]
    assert got["look"] == [[None, False, False], ["true", False, True], [None, True, False]]
    assert got["jumps"] == [15, 12.34]


@needs_node
def test_the_checklist_ticks_from_data_and_says_why_a_step_waits(tmp_path):
    got = run("""
      const el = checklist();
      const steps = [{text: "Clear feeder obstruction", state: "done"},
                     {text: "Acknowledge", state: "pending"},
                     {text: "Reset", state: "blocked", why: "Can't reset yet: the chute is still plugged."}];
      renderChecklist(el, {steps}, COPY);
      const items = Array.from(el.children);
      items[1].click();
      DOM.writes = 0; renderChecklist(el, {steps}, COPY);
      out({tag: el.tagName, states: items.map((li) => li.getAttribute("data-state")), words: items.map((li) => li.lastChild.textContent),
           icons: items.map((li) => li.firstChild.hasAttribute("hidden") ? null : li.firstChild.firstChild.getAttribute("href")),
           writesOnRepeat: DOM.writes});
    """, tmp_path)
    assert got["tag"] == "OL" and got["states"] == ["done", "pending", "blocked"]
    assert got["words"] == ["done", "", "Can't reset yet: the chute is still plugged."]
    assert got["icons"] == ["#i-check", None, "#i-lock"] and got["writesOnRepeat"] == 0


@needs_node
def test_the_all_normal_card_repoints_its_one_button_without_losing_focus(tmp_path):
    got = run("""
      const pressed = [];
      const el = allNormalCard("rail", COPY, (c) => pressed.push(c));
      const button = el.lastChild;
      renderAllNormalCard(el, {state: "idle", sentence: "Ready. Start runs the line from bin A.",
                               action: {command: "start", preview: {accepted: true}, primary: true}}, COPY);
      const idle = [el.children[1].textContent, button.textContent, button.hasAttribute("data-primary")];
      button.click(); button.focus();
      renderAllNormalCard(el, {state: "running", sentence: "Running normally: feeding from bin A, hopper at 42 %.",
                               action: {command: "stop", preview: {accepted: true}, primary: true}}, COPY);
      const running = [el.getAttribute("data-state"), button.textContent, document.activeElement === button, el.lastChild === button];
      button.click();
      renderAllNormalCard(el, {state: "idle", sentence: "Ready.", action: null}, COPY);
      out({idle, running, pressed, hiddenWithoutAction: button.hasAttribute("hidden"), heading: el.firstChild.tagName});
    """, tmp_path)
    assert got["idle"] == ["Ready. Start runs the line from bin A.", "Start", True]
    assert got["running"] == ["running", "Stop", True, True]
    assert got["pressed"] == ["start", "stop"] and got["hiddenWithoutAction"] and got["heading"] == "H3"


@needs_node
def test_a_readout_shows_its_value_and_never_a_lost_signals_number(tmp_path):
    got = run("""
      const el = readout("Hopper weight");
      const look = () => [el.getAttribute("data-health"), el.children[2].textContent,
                          el.lastChild.hasAttribute("hidden") ? null : el.lastChild.textContent];
      renderReadout(el, {value: 1912.4, unit: "kg", health: "normal", tag: "WT-105"}, COPY); const normal = look();
      renderReadout(el, {value: 45.25, unit: "%", decimals: 1, health: "suspect"}, COPY); const suspect = look();
      renderReadout(el, {value: 0, unit: "kg", health: "lost"}, COPY); const lost = look();
      DOM.writes = 0; renderReadout(el, {value: 0, unit: "kg", health: "lost"}, COPY);
      out({normal, suspect, lost, writesOnRepeat: DOM.writes});
    """, tmp_path)
    assert got["normal"] == ["normal", "1,912 kg", None]
    assert got["suspect"] == ["suspect", "45.3 %", "Reading suspect"]
    assert got["lost"] == ["lost", "—", "Signal lost"], "a failed transmitter's 0 kg must not look like an empty hopper"
    assert got["writesOnRepeat"] == 0


@needs_node
def test_an_indicator_shows_its_state_and_words_only_where_asked(tmp_path):
    got = run("""
      const el = indicator();
      renderIndicator(el, {state: "reached", cls: "trip"}, COPY);
      const quiet = [el.getAttribute("data-state"), el.getAttribute("data-class"), el.lastChild.hasAttribute("hidden")];
      renderIndicator(el, {state: "normal", cls: "trip", words: true}, COPY);
      const worded = el.lastChild.textContent;
      renderIndicator(el, {state: "faulted", cls: "warn", words: true}, COPY);
      out({quiet, worded, faulted: el.lastChild.textContent, svgNs: el.firstChild.namespaceURI,
           shapes: Array.from(el.firstChild.children).map((n) => n.tagName)});
    """, tmp_path)
    assert got["quiet"] == ["reached", "trip", True] and got["worded"] == "normal" and got["faulted"] == "Reading suspect"
    assert got["svgNs"] == "http://www.w3.org/2000/svg" and got["shapes"] == ["circle", "path"]


@needs_node
def test_the_io_table_marks_what_changed_and_hides_tags_a_recording_lacks(tmp_path):
    got = run("""
      const el = ioTable([{name: "WT-105", type: "AI", units: "kg", description: "Hopper weight"},
                          {name: "M-103.RUN", type: "DO", units: "", description: "Feeder run command"},
                          {name: "DS-107.READY", type: "DI", units: "", description: "Next process ready"}], COPY);
      renderIOTable(el, {values: {"WT-105": 10, "M-103.RUN": false}, prev: null});
      renderIOTable(el, {values: {"WT-105": 12.5, "M-103.RUN": false}, prev: {"WT-105": 10, "M-103.RUN": false}});
      const rows = Array.from(el.lastChild.children);
      const look = rows.map((tr) => [tr.hasAttribute("hidden"), tr.hasAttribute("data-changed"), tr.lastChild.textContent]);
      DOM.writes = 0; renderIOTable(el, {values: {"WT-105": 12.5, "M-103.RUN": false}, prev: {"WT-105": 12.5, "M-103.RUN": false}});
      const settle = DOM.writes;
      DOM.writes = 0; renderIOTable(el, {values: {"WT-105": 12.5, "M-103.RUN": false}, prev: {"WT-105": 12.5, "M-103.RUN": false}});
      out({look, settle, writesOnRepeat: DOM.writes, head: Array.from(el.firstChild.firstChild.children).map((th) => th.textContent)});
    """, tmp_path)
    assert got["look"] == [[False, True, "12.50 kg"], [False, False, "0"], [True, False, ""]]
    assert got["settle"] == 1 and got["writesOnRepeat"] == 0
    assert got["head"] == ["Tag", "Signal", "Type", "Value"]


@needs_node
@pytest.mark.parametrize("kind", sorted(copytext.ACTION_KINDS))
def test_an_action_chip_says_its_kind_in_words(kind, tmp_path):
    got = run(f"""
      const el = actionChip();
      renderActionChip(el, {{kind: {json.dumps(kind)}, text: "Someone presses the E-stop"}}, COPY);
      out({{text: el.textContent, icon: el.firstChild.firstChild.getAttribute("href"), sr: el.children[1].getAttribute("class")}});
    """, tmp_path)
    words = copytext.ACTION_KINDS[kind]
    assert got == {"text": f"{words['text']}: Someone presses the E-stop", "icon": f"#i-{words['icon']}", "sr": "c-sr"}


@needs_node
def test_an_unknown_action_kind_is_an_error_not_a_blank_chip(tmp_path):
    got = run("""
      let message = null;
      try { renderActionChip(actionChip(), {kind: "magic", text: "x"}, COPY); } catch (e) { message = e.message; }
      out(message);
    """, tmp_path)
    assert got == 'no words for action kind "magic"'


@needs_node
def test_the_test_panel_follows_a_real_run_stage_by_stage(tmp_path):
    test_plan, summary = real_run("faults/feeder_jam_recovery.yaml")
    assert summary["verdict"] == "PASS"
    got = run(f"""
      const plan = {json.dumps(test_plan)}, summary = {json.dumps(summary)};
      const el = testPanel(plan, COPY);
      const [list, live] = Array.from(el.children);
      const stages = () => Array.from(list.children).slice(1);
      const status = () => stages().map((li) => li.firstChild.lastChild.textContent);
      const n = plan.stages.length;
      renderTestPanel(el, {{setup: "running", stages: []}}, COPY);
      const setupRunning = [list.children[0].firstChild.lastChild.textContent, status()[0]];
      renderTestPanel(el, {{setup: "done", stages: [{{status: "running", elapsed_s: 1.26}}]}}, COPY);
      const running = [stages()[0].getAttribute("data-status"), status()[0], live.textContent];
      renderTestPanel(el, {{setup: "done", stages: summary.stages}}, COPY);
      const done = {{statuses: stages().map((li) => li.getAttribute("data-status")), first: status()[0], announced: live.textContent,
                     results: stages().flatMap((li) => li.children[2] ? Array.from(li.children[2].lastChild.children).map((tr) => tr.lastChild.textContent) : [])}};
      DOM.writes = 0; renderTestPanel(el, {{setup: "done", stages: summary.stages}}, COPY);
      out({{setupRunning, running, done, writesOnRepeat: DOM.writes, n,
            chips: list.children[1].children[1].textContent, heads: stages().map((li) => li.firstChild.children[1].textContent)}});
    """, tmp_path)
    first = summary["stages"][0]
    assert got["setupRunning"] == ["Setting up…", "Waiting"]
    assert got["running"] == ["running", f"1.3 s of {first['within_s']:g} s", ""]
    assert got["done"]["statuses"] == ["passed"] * got["n"]
    assert got["done"]["first"] == f"Passed in {first['response_s']:.2f} s (limit {first['within_s']:g} s)"
    assert got["done"]["announced"].startswith(f"Stage {got['n']}") and "Passed in" in got["done"]["announced"]
    assert set(got["done"]["results"]) == {"MATCH"}
    assert got["writesOnRepeat"] == 0
    assert got["heads"][0] == f"Stage 1: {test_plan['stages'][0]['title']}"
    kind = copytext.ACTION_KINDS[test_plan["stages"][0]["actions"][0]["kind"]]["text"]
    assert got["chips"].startswith(f"{kind}: {test_plan['stages'][0]['actions'][0]['text']}")


@needs_node
def test_a_failed_run_shows_the_mismatch_the_deadline_and_what_never_ran(tmp_path):
    test_plan, summary = real_run("faults/feeder_jam_recovery.yaml", regression="jam-trip-removed")
    assert summary["verdict"] == "FAIL"
    failed = next(st for st in summary["stages"] if st["status"] == "failed")
    got = run(f"""
      const summary = {json.dumps(summary)};
      const tp = testPanel({json.dumps(test_plan)}, COPY);
      renderTestPanel(tp, {{setup: "done", stages: summary.stages.map((st) => ({{...st, deadline: true}}))}}, COPY);
      const stages = Array.from(tp.firstChild.children).slice(1);
      const failed = stages[{failed['n'] - 1}];
      const verdict = verdictBlock();
      renderVerdictBlock(verdict, summary, COPY);
      DOM.writes = 0; renderVerdictBlock(verdict, summary, COPY);
      out({{failedStatus: failed.firstChild.lastChild.textContent,
            results: Array.from(failed.children[2].lastChild.children).map((tr) => [tr.getAttribute("data-status"), tr.lastChild.textContent]),
            after: stages.slice({failed['n']}).map((li) => li.firstChild.lastChild.textContent),
            verdict: verdict.getAttribute("data-verdict"), heading: verdict.firstChild.tagName, head: verdict.firstChild.textContent,
            where: verdict.children[1].textContent, unmet: Array.from(verdict.lastChild.children).map((li) => li.textContent),
            writesOnRepeat: DOM.writes}});
    """, tmp_path)
    assert got["failedStatus"] == f"Failed at its {failed['within_s']:g} s deadline"
    mismatches = [c for c in failed["checks"] if c["status"] == "mismatch"]
    assert mismatches and sum(1 for s, _ in got["results"] if s == "mismatch") == len(mismatches)
    assert all(text.startswith("MISMATCH, got ") for s, text in got["results"] if s == "mismatch")
    assert set(got["after"]) <= {"Not run: the test stops at the first failure"}
    assert got["verdict"] == "fail" and got["heading"] == "H3"
    assert got["head"] == f"FAIL{summary['checks_passed']}/{summary['checks_evaluated']} checks matched"
    assert got["where"].startswith(f"Failed at stage {failed['n']} ({failed['title']}), at ")
    assert len(got["unmet"]) == len(mismatches) and all(": expected " in u and ", got " in u for u in got["unmet"])
    assert got["writesOnRepeat"] == 0


@needs_node
def test_the_verdict_block_passes_quietly(tmp_path):
    _, summary = real_run("startup/normal_operation.yaml")
    got = run(f"""
      const el = verdictBlock();
      renderVerdictBlock(el, {json.dumps(summary)}, COPY);
      out({{verdict: el.getAttribute("data-verdict"), badge: el.firstChild.firstChild.textContent,
            whereHidden: el.children[1].hasAttribute("hidden"), unmetHidden: el.lastChild.hasAttribute("hidden")}});
    """, tmp_path)
    assert got == {"verdict": "pass", "badge": "PASS", "whereHidden": True, "unmetHidden": True}


@needs_node
def test_a_runtime_comparison_says_how_each_was_compared_and_whether_it_agrees(tmp_path):
    got = run("""
      const el = runtimeTable(COPY);
      const rows = [
        {runtime_id: "python", runtime: "Python controller", verdict: "PASS", checks: "12/12", how: "reference run", agrees: null},
        {runtime_id: "modbus", runtime: "Over Modbus", verdict: "PASS", checks: "12/12", how: "lockstep: event log compared event by event -- identical", agrees: true},
        {runtime_id: "openplc", runtime: "OpenPLC", verdict: "FAIL", checks: "10/12", how: "real time: compared by verdict and checks", agrees: false}];
      renderRuntimeTable(el, {rows}, COPY);
      DOM.writes = 0; renderRuntimeTable(el, {rows}, COPY);
      out({rows: Array.from(el.lastChild.children).map((tr) => [tr.getAttribute("data-agrees"), tr.children[1].firstChild.getAttribute("data-verdict"),
                                                               tr.lastChild.textContent, tr.firstChild.tagName]),
           writesOnRepeat: DOM.writes});
    """, tmp_path)
    assert got["rows"] == [["reference", "pass", "Reference run", "TH"], ["yes", "pass", "Agrees", "TH"],
                           ["no", "fail", "Disagrees", "TH"]]
    assert got["writesOnRepeat"] == 0


@needs_node
def test_a_scenario_card_runs_shows_its_result_and_locks_while_any_test_runs(tmp_path):
    got = run("""
      const asked = [];
      const el = scenarioCard({id: "feeder-jam", title: "Feeder jam recovery", description: "The feeder jams mid-run.", stages: 6},
                              COPY, {run: (id) => asked.push(["run", id]), compare: (id) => asked.push(["compare", id])});
      const [run, compare, watch] = Array.from(el.lastChild.children);
      const result = el.children[3];
      renderScenarioCard(el, {running: false, locked: false, result: null, watch: null}, COPY);
      const idle = [el.getAttribute("data-state"), result.hasAttribute("hidden"), watch.hasAttribute("hidden"), el.children[2].textContent];
      run.click(); compare.click();
      renderScenarioCard(el, {running: true, locked: true, result: null, watch: null}, COPY);
      const running = [el.getAttribute("data-state"), result.textContent, run.hasAttribute("disabled"), compare.hasAttribute("disabled")];
      run.click();
      renderScenarioCard(el, {running: false, locked: false, result: {verdict: "PASS", checks: "12/12 checks matched"}, watch: "replay/latest"}, COPY);
      const done = [el.getAttribute("data-state"), result.textContent, result.children[1].getAttribute("data-verdict"),
                    watch.getAttribute("href"), watch.getAttribute("target"), run.hasAttribute("disabled")];
      out({idle, running, done, asked, heading: el.firstChild.tagName, labelledby: el.getAttribute("aria-labelledby")});
    """, tmp_path)
    assert got["idle"] == ["idle", True, True, "6 stages"]
    assert got["running"] == ["running", "Running now…", True, True]
    assert got["asked"] == [["run", "feeder-jam"], ["compare", "feeder-jam"]], "a locked card sends nothing"
    assert got["done"] == ["result", "PASS12/12 checks matched", "pass", "replay/latest", "_blank", False]
    assert got["heading"] == "H3" and got["labelledby"] == "test-feeder-jam-title"
