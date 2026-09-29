// Components (frontend redesign, build step 7; the design specification's
// section 7). Each component is built once (`stateBadge()`, `drawer(...)`)
// and then kept current by its render function (`renderStateBadge(el,
// data, copy)`), which is pure and idempotent: everything arrives as
// arguments, and it changes the DOM only through patch(), so rendering the
// same data twice writes nothing, and a focused control inside is never
// rebuilt. The words come from `copy` (copytext.py, as JSON); this file holds
// no identifier-to-words table of its own.

const SVG_NS = "http://www.w3.org/2000/svg";

// patch(el, props): the only way a render function changes the DOM.
// props.text replaces the element's text (use on leaf elements); props.attrs
// sets each attribute, removing it for null/false and writing "" for true.
// Writes only what differs; returns the number of writes made.
function patch(el, props) {
  let writes = 0;
  if ("text" in props) {
    const text = props.text === null || props.text === undefined ? "" : String(props.text);
    if (el.textContent !== text) { el.textContent = text; writes++; }
  }
  for (const [name, value] of Object.entries(props.attrs || {})) {
    if (value === null || value === false || value === undefined) {
      if (el.hasAttribute(name)) { el.removeAttribute(name); writes++; }
    } else {
      const s = value === true ? "" : String(value);
      if (el.getAttribute(name) !== s) { el.setAttribute(name, s); writes++; }
    }
  }
  return writes;
}

// h(tag, attrs, ...children): builds a node once; render functions patch it after.
function h(tag, attrs = {}, ...children) {
  const el = tag === "svg" || tag === "use" ? document.createElementNS(SVG_NS, tag) : document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value !== null && value !== false && value !== undefined) el.setAttribute(name, value === true ? "" : String(value));
  }
  for (const child of children) {
    if (child !== null && child !== undefined) el.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return el;
}

// An icon from the in-house set (icons.svg.html), always beside visible text.
function icon(name) {
  return h("svg", { class: "c-icon", "aria-hidden": "true", focusable: "false" }, h("use", { href: `#i-${name}` }));
}

// Shows or hides an icon element and points it at `name` (null: hidden).
function patchIcon(svg, name) {
  return patch(svg, { attrs: { hidden: !name } }) + (name ? patch(svg.firstChild, { attrs: { href: `#i-${name}` } }) : 0);
}

// ---- StateBadge: the line state in fixed words (spec 5.1); also the separate
// TESTING badge. data: {state}, a key of copy.badges. The words are the
// accessible name; the icon is hidden from screen readers.
function stateBadge() {
  return h("span", { class: "c-badge" }, icon("clock"), h("span", { class: "c-badge__text" }));
}

function renderStateBadge(el, data, copy) {
  const badge = copy.badges[data.state];
  if (!badge) throw new Error(`no badge for state "${data.state}"`);  // copytext.py is tested to cover every state
  const previous = el.getAttribute("data-state");
  let writes = patch(el, { attrs: { "data-state": data.state, "data-variant": badge.variant } });
  writes += patchIcon(el.firstChild, badge.icon);
  writes += patch(el.lastChild, { text: badge.text });
  if (previous !== null && previous !== data.state) {
    // One 200 ms fade of the new badge (spec 5.5); off under reduced motion.
    el.removeAttribute("data-fresh");
    void el.offsetWidth;  // restart the animation
    el.setAttribute("data-fresh", "");
    writes += 2;
  }
  return writes;
}

// ---- TagChip: a technical identifier, shown only with "Show technical
// identifiers" on (spec 2.3). data: {tag}, or {tag: null} for none.
function tagChip() {
  return h("code", { class: "c-tag", hidden: true });
}

function renderTagChip(el, data) {
  return patch(el, { attrs: { hidden: !data.tag } }) + patch(el, { text: data.tag || "" });
}

// ---- Panel: a titled region (section + h2). Static: built once with its
// title, then the caller fills panel.lastChild.
function panel(id, title) {
  return h("section", { class: "c-panel", "aria-labelledby": `${id}-title` },
    h("h2", { class: "c-panel__title", id: `${id}-title` }, title), h("div", { class: "c-panel__body" }));
}

// ---- Drawer: collapsible diagnostic or engineering content (spec 3.5),
// native details/summary, collapsed by default. data: {title, count}; count
// null hides it. The caller fills drawer.lastChild.
function drawer() {
  return h("details", { class: "c-drawer" },
    h("summary", {}, icon("chevron"), h("span", { class: "c-drawer__title" }), h("span", { class: "c-drawer__count", hidden: true })),
    h("div", { class: "c-drawer__body" }));
}

function renderDrawer(el, data) {
  const summary = el.firstChild;
  const title = summary.children[1], count = summary.children[2];
  return patch(title, { text: data.title })
    + patch(count, { attrs: { hidden: data.count === null || data.count === undefined } })
    + patch(count, { text: data.count === null || data.count === undefined ? "" : data.count });
}

// ======== Step 7b: the console controls. They show what the controller and
// the server say; they never decide anything. A button is unavailable only
// because the controller's preview says so, and pressing it still sends the
// request: the controller decides (spec 4.1). Sentences built from controller
// data (a refusal, a "can't yet" reason) arrive composed, as text.

// A number with a thin space and its unit (spec 5.4).
function withUnit(value, unit) {
  return `${Math.round(value)} ${unit}`;
}

// ---- CommandButton: one controller request (spec 4.1). onPress(command) is
// called on every press, available or not. data: {preview: {accepted} or
// null, sent, locked, primary, describedby}; preview null means no preview
// (an external controller). A locked button (a test owns the line) is the
// only natively disabled one; an unavailable button stays focusable.
function commandButton(command, copy, onPress) {
  const el = h("button", { type: "button", class: "c-cmd", "data-command": command },
    icon("circle-info"), h("span", { class: "c-cmd__label" }, copy.commands[command]));
  el.addEventListener("click", () => { if (!el.hasAttribute("disabled")) onPress(command); });
  return el;
}

function renderCommandButton(el, data, copy) {
  const command = el.getAttribute("data-command");
  const unavailable = !!(data.preview && data.preview.accepted === false) && !data.locked;
  const state = data.locked ? "locked" : data.sent ? "sent" : unavailable ? "unavailable" : "available";
  return patch(el, { attrs: {
      "data-state": state, "data-primary": !!data.primary && state === "available",
      disabled: state === "locked", "aria-disabled": unavailable ? "true" : null,
      "aria-busy": state === "sent" ? "true" : null, "aria-describedby": data.describedby || null } })
    + patchIcon(el.firstChild, state === "locked" ? "lock" : unavailable ? "circle-info" : null)
    + patch(el.lastChild, { text: state === "sent" ? copy.controls.sent : copy.commands[command] });
}

// ---- EStopButton: the operator's emergency-stop pushbutton (spec 8.4, Q2).
// A plant input, not a controller request: no preview, never unavailable.
// data: {pressed, locked, describedby}. onToggle(pressed) asks to press or release.
function estopButton(copy, onToggle) {
  const el = h("span", { class: "c-estop" },
    h("button", { type: "button", class: "c-estop__button", "aria-pressed": "false" }, icon("estop"),
      h("span", {}, copy.controls.estop_press)),
    h("span", { class: "c-estop__status", hidden: true }, copy.controls.estop_pressed));
  const button = el.firstChild;
  button.addEventListener("click", () => {
    if (!button.hasAttribute("disabled")) onToggle(button.getAttribute("aria-pressed") !== "true");
  });
  return el;
}

function renderEStopButton(el, data, copy) {
  const button = el.firstChild, status = el.lastChild;
  return patch(el, { attrs: { "data-state": data.locked ? "locked" : data.pressed ? "pressed" : "released" } })
    + patch(button, { attrs: { "aria-pressed": data.pressed ? "true" : "false", disabled: !!data.locked,
                               "aria-describedby": data.locked ? data.describedby || null : null } })
    + patch(button.lastChild, { text: data.pressed ? copy.controls.estop_release : copy.controls.estop_press })
    + patch(status, { attrs: { hidden: !data.pressed } });
}

// ---- SegmentedControl: the mode, or the source bin (spec 7.2). Radio-group
// semantics with a roving tab stop. Arrow keys move focus only; Enter or
// Space selects, because selecting sends a request to the controller and an
// arrow key must never do that (spec 14: no accidental operator commands).
// options: [{value, label}]; data: {selected, unavailable: {value: true},
// locked, describedby: {value: id}}. onSelect(value) on every selection.
function segmentedControl(label, options, onSelect) {
  const el = h("div", { class: "c-seg", role: "radiogroup", "aria-label": label },
    ...options.map((o) => h("button", { type: "button", role: "radio", class: "c-seg__option", "data-value": o.value,
                                        "aria-checked": "false", tabindex: "-1" }, icon("circle-info"), h("span", {}, o.label))));
  for (const button of el.children) {
    button.addEventListener("click", () => { if (!button.hasAttribute("disabled")) onSelect(button.getAttribute("data-value")); });
    button.addEventListener("keydown", (e) => {
      const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
      if (!step) return;
      e.preventDefault();
      const all = Array.from(el.children), next = all[(all.indexOf(button) + step + all.length) % all.length];
      for (const b of all) b.setAttribute("tabindex", b === next ? "0" : "-1");
      next.focus();
    });
  }
  return el;
}

function renderSegmentedControl(el, data) {
  let writes = 0;
  const focusedInside = Array.from(el.children).some((b) => document.activeElement === b);
  for (const button of el.children) {
    const value = button.getAttribute("data-value"), selected = value === data.selected;
    const unavailable = !!(data.unavailable || {})[value] && !data.locked;
    writes += patch(button, { attrs: {
      "aria-checked": selected ? "true" : "false", disabled: !!data.locked,
      "aria-disabled": unavailable ? "true" : null, "aria-describedby": (data.describedby || {})[value] || null } });
    // The tab stop follows the selection, unless the operator is moving through the options.
    if (!focusedInside) writes += patch(button, { attrs: { tabindex: selected ? "0" : "-1" } });
    writes += patchIcon(button.firstChild, unavailable ? "circle-info" : null);
  }
  return writes;
}

// ---- PermissiveNote: why an action is unavailable, or why it was refused
// (spec 4.1, 10.4). data: {kind: "preview" | "refused" | "unknown" | null,
// text}. The text arrives composed; kind null hides the note. Refused is a
// controller answer, not an equipment failure: never the trip marker.
function permissiveNote(id) {
  return h("p", { class: "c-note", id, hidden: true }, icon("circle-info"), h("span", {}));
}

function renderPermissiveNote(el, data) {
  return patch(el, { attrs: { hidden: !data.kind, "data-kind": data.kind || null } })
    + patchIcon(el.firstChild, data.kind === "refused" ? "cross" : "circle-info")
    + patch(el.lastChild, { text: data.kind ? data.text : "" });
}

// ---- PermissiveTable: "Why can't I...?" (spec 10.4, as decided 2026-09-27):
// only what the controller reports as blocking each request, in refusal-reason
// wording, never a permissive shown as met. data: {requests: [{label, rows:
// [{text, tag}], empty}], note}; `empty` is the words when nothing blocks it;
// `note` alone (no requests) is the no-preview case.
function permissiveTable() {
  return h("div", { class: "c-ptable" });
}

function renderPermissiveTable(el, data) {
  // Rebuilt only when its content changes: it holds no control that can have focus.
  const key = JSON.stringify(data);
  if (el.getAttribute("data-key") === key) return 0;
  while (el.firstChild) el.removeChild(el.firstChild);
  el.setAttribute("data-key", key);
  if (!data.requests || !data.requests.length) {
    el.appendChild(h("p", { class: "c-ptable__note" }, data.note || ""));
    return 1;
  }
  for (const r of data.requests) {
    const rows = r.rows.length
      ? r.rows.map((row) => {
          const chip = tagChip();
          renderTagChip(chip, { tag: row.tag || null });
          return h("tr", { "data-state": "blocking" }, h("th", { scope: "row" }, icon("cross")), h("td", {}, row.text, chip));
        })
      : [h("tr", { "data-state": "clear" }, h("th", { scope: "row" }, icon("check")), h("td", {}, r.empty))];
    el.appendChild(h("table", { class: "c-ptable__table" }, h("caption", {}, r.label), h("tbody", {}, ...rows)));
  }
  return 1;
}

// ---- DeviceRow: one device in Manual (spec 4.2 workflow 6). A labelled group:
// the device's name, its state (confirmed on / off / commanded, words and
// marker), and its two CommandButtons. data: {state: "on"|"off"|"commanded",
// stateText, buttons: {command: CommandButton data}}.
function deviceRow(name, commands, copy, onPress) {
  return h("div", { class: "c-device", role: "group", "aria-label": name },
    h("span", { class: "c-device__name" }, name),
    h("span", { class: "c-device__state" }, h("span", { class: "c-device__marker", "aria-hidden": "true" }), h("span", {})),
    h("span", { class: "c-device__buttons" }, ...commands.map((c) => commandButton(c, copy, onPress))));
}

function renderDeviceRow(el, data, copy) {
  const state = el.children[1], buttons = el.children[2].children;
  let writes = patch(state, { attrs: { "data-state": data.state } }) + patch(state.lastChild, { text: data.stateText });
  for (const b of buttons) writes += renderCommandButton(b, data.buttons[b.getAttribute("data-command")] || {}, copy);
  return writes;
}

// ---- RecipeForm: the batch recipe and hold (spec 4.2 workflow 7). Labelled
// number inputs with units; Apply never loses what was typed. The form only
// checks that each entry is a number, 0 or more: whether the recipe fits the
// hopper is the controller's call. data: {applied: {field: value}, locked}.
// onApply({field: number}) when every entry is valid.
function recipeForm(id, copy, onApply) {
  const c = copy.controls;
  const fields = c.recipe_fields.map(([name, label, unit]) => h("label", { class: "c-recipe__field" },
    h("span", {}, label),
    h("input", { type: "number", min: "0", step: "any", inputmode: "decimal", name, id: `${id}-${name}`,
                 "aria-describedby": `${id}-${name}-err` }),
    h("span", { class: "c-recipe__unit" }, unit),
    h("span", { class: "c-recipe__error", id: `${id}-${name}-err`, hidden: true }, c.recipe_invalid)));
  const apply = h("button", { type: "submit", class: "c-cmd" }, h("span", { class: "c-cmd__label" }, c.recipe_apply));
  const el = h("form", { class: "c-recipe", id, novalidate: true },
    h("div", { class: "c-recipe__fields" }, ...fields), apply, h("p", { class: "c-recipe__status", role: "status" }));
  const inputs = () => fields.map((f) => f.children[1]);
  const check = (input) => {
    const ok = input.value.trim() !== "" && Number.isFinite(+input.value) && +input.value >= 0;
    patch(input, { attrs: { "aria-invalid": ok ? null : "true" } });
    patch(input.parentNode.lastChild, { attrs: { hidden: ok } });
    return ok;
  };
  for (const input of inputs()) input.addEventListener("input", () => { input.setAttribute("data-edited", ""); check(input); });
  el.addEventListener("submit", (e) => {
    e.preventDefault();
    const all = inputs(), ok = all.map(check).every(Boolean);
    if (ok) onApply(Object.fromEntries(all.map((i) => [i.getAttribute("name"), +i.value])));
  });
  return el;
}

function renderRecipeForm(el, data, copy) {
  let writes = 0, changed = false;
  for (const field of el.firstChild.children) {
    const input = field.children[1], applied = data.applied[input.getAttribute("name")];
    // What the operator typed is never overwritten: only an untouched field follows the applied value.
    if (!input.hasAttribute("data-edited") && document.activeElement !== input && input.value !== String(applied)) {
      input.value = String(applied); writes++;
    }
    if (input.value.trim() === "" || +input.value !== applied) changed = true;
    writes += patch(input, { attrs: { disabled: !!data.locked } });
  }
  writes += patch(el.children[1], { attrs: { disabled: !!data.locked } });
  return writes + patch(el.lastChild, { text: changed ? copy.controls.recipe_changed : copy.controls.recipe_applied,
                                        attrs: { "data-changed": changed } });
}

// Called by the page once the server confirms an Apply: the fields follow the applied values again.
function settleRecipeForm(el) {
  for (const field of el.firstChild.children) field.children[1].removeAttribute("data-edited");
}

// ---- BatchProgress: Load -> Hold -> Discharge -> Clean out (spec 4.2
// workflow 7). An ordered list; the current step has aria-current="step".
// data: {state, loaded_kg, target_kg}; outside a batch no step is current.
function batchProgress(copy) {
  return h("div", { class: "c-batch" },
    h("ol", { class: "c-batch__steps" }, ...copy.controls.batch_steps.map(([state, label]) =>
      h("li", { "data-step": state }, icon("check"), h("span", {}, label)))),
    h("p", { class: "c-batch__loaded", hidden: true }));
}

function renderBatchProgress(el, data, copy) {
  const steps = Array.from(el.firstChild.children);
  const current = steps.findIndex((li) => li.getAttribute("data-step") === data.state);
  let writes = 0;
  steps.forEach((li, i) => {
    const done = current > i;
    writes += patch(li, { attrs: { "aria-current": i === current ? "step" : null, "data-done": done } });
    writes += patchIcon(li.firstChild, done ? "check" : null);
  });
  const loading = data.state === "loading" && data.target_kg > 0;
  return writes + patch(el.lastChild, { attrs: { hidden: !loading }, text: loading
    ? copy.controls.batch_loaded.replace("{loaded}", withUnit(data.loaded_kg, "kg")).replace("{target}", withUnit(data.target_kg, "kg"))
    : "" });
}

// ---- ConditionToggle: a physical condition in the Test view (spec 4.3):
// "Jam the feeder", pressed while active. The words arrive with it (physical
// verbs only, never a controller verb). data: {active, locked}. onToggle(active).
function conditionToggle(label, copy, onToggle) {
  const el = h("button", { type: "button", class: "c-condition", "aria-pressed": "false" },
    h("span", {}, label), h("span", { class: "c-condition__active", hidden: true }, copy.controls.condition_active));
  el.addEventListener("click", () => { if (!el.hasAttribute("disabled")) onToggle(el.getAttribute("aria-pressed") !== "true"); });
  return el;
}

function renderConditionToggle(el, data) {
  return patch(el, { attrs: { "aria-pressed": data.active ? "true" : "false", disabled: !!data.locked } })
    + patch(el.lastChild, { attrs: { hidden: !data.active } });
}

// ---- MaintenanceAction: a physical repair (spec 4.3, D4), labelled as a
// maintenance action, never as a controller operation. data: {done}.
function maintenanceAction(label, copy, onDo) {
  const el = h("button", { type: "button", class: "c-maint" }, icon("wrench"),
    h("span", { class: "c-maint__prefix" }, copy.controls.maintenance_prefix), h("span", {}, label),
    h("span", { class: "c-maint__done", hidden: true }, copy.controls.done));
  el.addEventListener("click", () => { if (el.getAttribute("aria-disabled") !== "true") onDo(); });
  return el;
}

function renderMaintenanceAction(el, data) {
  return patch(el, { attrs: { "aria-disabled": data.done ? "true" : null, "data-done": !!data.done } })
    + patchIcon(el.firstChild, data.done ? "check" : "wrench")
    + patch(el.lastChild, { attrs: { hidden: !data.done } });
}
