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
    assert got == {"none": True, "shown": True, "text": "LSH-103", "writesOnRepeat": 0, "tag": "code"}


@needs_node
def test_the_panel_is_a_labelled_section(tmp_path):
    got = run("""
      const el = panel("alarms", "Alarms");
      out({tag: el.tagName, labelledby: el.getAttribute("aria-labelledby"),
           heading: el.firstChild.tagName, headingId: el.firstChild.getAttribute("id"), title: el.firstChild.textContent});
    """, tmp_path)
    assert got == {"tag": "section", "labelledby": "alarms-title", "heading": "h2", "headingId": "alarms-title", "title": "Alarms"}


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
    assert got == {"tag": "details", "open": False, "countHidden": True, "count": "12", "focusKept": True, "writesOnRepeat": 0}


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
    assert got == {"length": 2, "second": "span", "hasSome": "undefined", "asArray": 2}


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
