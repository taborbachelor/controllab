// Components (frontend redesign, build step 7; the design specification's
// section 7). Each component is built once (`stateBadge()`, `drawer(...)`)
// and then kept current by its render function (`renderStateBadge(el,
// data, copy)`), which is pure and idempotent: everything arrives as
// arguments, and it changes the DOM only through patch(), so rendering the
// same data twice writes nothing, and a focused control inside is never
// rebuilt. The words come from `copy` (copytext.py, as JSON); this file holds
// no identifier-to-words table of its own.

const SVG_NS = "http://www.w3.org/2000/svg";
const SVG_TAGS = new Set(["svg", "use", "circle", "path"]);

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
  const el = SVG_TAGS.has(tag) ? document.createElementNS(SVG_NS, tag) : document.createElement(tag);
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

// A number and its unit joined by a narrow no-break space (U+202F: thin, and it never
// lets a line break split "1 s"; spec 5.4).
function withUnit(value, unit) {
  return `${Math.round(value)}\u202f${unit}`;
}

// ---- CommandButton: one controller request (spec 4.1). onPress(command) is
// called on every press, available or not. data: {preview: {accepted} or
// null, sent, locked, primary, describedby}; preview null means no preview
// (an external controller). A locked button (a test owns the line) is the
// only natively disabled one; an unavailable button stays focusable. The
// request sent is the element's data-command, so a caller may repoint the
// same button (AllNormalCard: Start, then Stop) without rebuilding it.
function commandButton(command, copy, onPress) {
  const el = h("button", { type: "button", class: "c-cmd", "data-command": command },
    icon("circle-info"), h("span", { class: "c-cmd__label" }, copy.commands[command]));
  el.addEventListener("click", () => { if (!el.hasAttribute("disabled")) onPress(el.getAttribute("data-command")); });
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
    // Locked shows no icon of its own: the console's one lock notice says why (Tabor, 2026-09-29).
    + patchIcon(el.firstChild, unavailable ? "circle-info" : null)
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

// ======== Step 7c: alarms, history, readings and test results. They show
// what the controller, the test runner and the server report and never judge
// anything: an alarm's lifecycle is the controller's own flags in words, a
// test's statuses and times come from the runner's plan and summary, a
// reading's health comes with it. Sentences built from that data (alarm text,
// history entries, recovery steps) arrive composed, as text.

// "{n} stages": fills a copy template's {names}.
function fill(template, values) {
  return template.replace(/\{(\w+)\}/g, (whole, name) => (name in values ? String(values[name]) : whole));
}

// A count's words: [one, many] from the copy.
function plural(forms, n) {
  return fill(forms[n === 1 ? 0 : 1], { n });
}

// Seconds, joined like withUnit(): one decimal in status and history, two in test
// timing (spec 5.4). A stage's time limit is shown as the scenario wrote it.
function seconds(value, decimals) {
  return `${value.toFixed(decimals)}\u202fs`;
}
function limitText(value) {
  return `${Number(value)}\u202fs`;
}

// A value a test expected or saw, in words (yes/no, lists, "—" for none).
function valueText(v, copy) {
  const w = copy.tests.values;
  if (v === null || v === undefined) return w.missing;
  if (typeof v === "boolean") return v ? w.yes : w.no;
  if (Array.isArray(v)) return v.length ? v.join(", ") : w.none;
  return String(v);
}

// reconcile(parent, items, keyOf, create, update): keeps parent's children in
// the order of `items`, one node per key. It creates what is missing, removes
// what is gone, and moves only a node that is out of place, so a row holding
// focus stays where it is unless it must itself move; then it updates each
// node with update(node, item). keyOf(item, i) returns a string. Returns writes.
function reconcile(parent, items, keyOf, create, update) {
  const keys = items.map((item, i) => keyOf(item, i));
  const wanted = new Set(keys);
  const have = new Map();
  let writes = 0;
  for (const child of Array.from(parent.children)) {
    const key = child.getAttribute("data-key");
    if (wanted.has(key) && !have.has(key)) have.set(key, child);
    else { parent.removeChild(child); writes++; }
  }
  items.forEach((item, i) => {
    let node = have.get(keys[i]);
    if (!node) { node = create(item); node.setAttribute("data-key", keys[i]); writes++; }
    if (parent.children[i] !== node) { parent.insertBefore(node, parent.children[i] || null); writes++; }
    writes += update(node, item);
  });
  return writes;
}

// A header row of column headings, for the tables below.
function headRow(columns) {
  return h("thead", {}, h("tr", {}, ...columns.map((c) => h("th", { scope: "col" }, c))));
}

// ---- AlarmMarker: the octagon (a trip) or triangle (a warning), drawn
// strongest while the alarm is new (spec 4.4, D7: never flashing). Hidden from
// screen readers: the words beside it carry the meaning. data: {cls: "trip" |
// "warn", lifecycle: "new" | "acknowledged" | "cleared"}.
function alarmMarker() {
  return h("svg", { class: "c-marker", "aria-hidden": "true", focusable: "false" }, h("use", { href: "#i-octagon" }));
}

function renderAlarmMarker(el, data) {
  return patch(el, { attrs: { "data-class": data.cls, "data-lifecycle": data.lifecycle } })
    + patch(el.firstChild, { attrs: { href: data.cls === "trip" ? "#i-octagon" : "#i-triangle" } });
}

// The controller's alarm flags in the words of spec 4.4. A latched alarm is
// active, unacknowledged, or both.
function alarmLifecycle(alarm) {
  return alarm.active ? (alarm.acknowledged ? "acknowledged" : "new") : "cleared";
}

// ---- AlarmSummary: the status bar's alarm count by class, and a "Show"
// link whose name carries the count ("1 trip alarm, show"). data: {trips,
// warnings, unacknowledged}; onShow() opens wherever the page keeps the list.
function alarmSummary(href, copy, onShow) {
  const link = h("a", { class: "c-asum__show", href }, copy.alarms.show);
  link.addEventListener("click", (e) => { if (onShow) { e.preventDefault(); onShow(); } });
  return h("span", { class: "c-asum" }, alarmMarker(), h("span", { class: "c-asum__counts" }), link);
}

function renderAlarmSummary(el, data, copy) {
  const a = copy.alarms, [marker, counts, link] = el.children;
  const parts = [];
  if (data.trips) parts.push(plural(a.count_trip, data.trips));
  if (data.warnings) parts.push(plural(a.count_warn, data.warnings));
  const state = data.trips ? "trip" : data.warnings ? "warn" : "none";
  let writes = patch(el, { attrs: { "data-state": state } }) + patch(marker, { attrs: { hidden: state === "none" } });
  if (state !== "none") writes += renderAlarmMarker(marker, { cls: state, lifecycle: data.unacknowledged ? "new" : "acknowledged" });
  return writes + patch(counts, { text: parts.length ? parts.join(" · ") : a.none })
    + patch(link, { attrs: { hidden: state === "none", "aria-label": state === "none" ? null : fill(a.show_label, { counts: parts.join(", ") }) } });
}

// ---- AlarmList / AlarmRow: the latched alarms (spec 4.4). A table; each
// row's lifecycle is in words, NEW is a static label, the first-out is
// "Started it" with its meaning on hover or focus. Rows are ordered new
// trips, new warnings, acknowledged, then cleared-unacknowledged, keeping the
// server's order (newest first) within each. data: {alarms: [{id, text,
// is_warning, active, acknowledged, first_out}]}; the id shows as a TagChip.
function alarmList(id, copy) {
  return h("div", { class: "c-alarms", "data-id": id },
    h("p", { class: "c-alarms__empty" }, copy.alarms.empty),
    h("table", { class: "c-alarms__table", hidden: true }, headRow(copy.alarms.columns), h("tbody")));
}

function alarmRank(a) {
  return a.active && !a.acknowledged ? (a.is_warning ? 1 : 0) : a.active ? 2 : 3;
}

// "Started it" is a toggletip: a button whose meaning shows beside it on
// hover, on keyboard focus, or when pressed (a touch screen has no hover),
// over the table rather than pushing the row down, and Escape dismisses it
// (WCAG 1.4.13). The text is also the button's description for screen readers.
function firstOutTip(help, copy) {
  const button = h("button", { type: "button", class: "c-alarms__first", "aria-expanded": "false", "aria-describedby": help },
    copy.alarms.first_out);
  const wrap = h("span", { class: "c-alarms__firstwrap", hidden: true }, button,
    h("span", { class: "c-alarms__help", id: help, role: "tooltip" }, copy.alarms.first_out_help));
  button.addEventListener("click", () => button.setAttribute("aria-expanded", String(button.getAttribute("aria-expanded") !== "true")));
  button.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    button.setAttribute("aria-expanded", "false");
    wrap.setAttribute("data-dismissed", "");
  });
  const undismiss = () => wrap.removeAttribute("data-dismissed");
  button.addEventListener("blur", undismiss);
  wrap.addEventListener("mouseleave", undismiss);
  return wrap;
}

function alarmRow(listId, alarm, copy) {
  return h("tr", {},
    h("td", {}, h("div", { class: "c-alarms__alarm" }, alarmMarker(),
      h("span", { class: "c-alarms__new", hidden: true }, copy.alarms.new_label),
      h("span", { class: "c-alarms__text" }), tagChip(), firstOutTip(`${listId}-${alarm.id}-first`, copy))),
    h("td", { class: "c-alarms__status" }));
}

function renderAlarmRow(tr, alarm, copy) {
  const cls = alarm.is_warning ? "warn" : "trip", lifecycle = alarmLifecycle(alarm);
  const [marker, isNew, text, chip, first] = tr.firstChild.firstChild.children;
  return patch(tr, { attrs: { "data-class": cls, "data-lifecycle": lifecycle, "data-first-out": !!alarm.first_out } })
    + renderAlarmMarker(marker, { cls, lifecycle })
    + patch(isNew, { attrs: { hidden: lifecycle !== "new" } })
    + patch(text, { text: alarm.text })
    + renderTagChip(chip, { tag: alarm.id })
    + patch(first, { attrs: { hidden: !alarm.first_out } })
    + patch(tr.lastChild, { text: `${copy.alarms.class[cls]} · ${copy.alarms.lifecycle[lifecycle]}` });
}

function renderAlarmList(el, data, copy) {
  const [empty, table] = el.children, listId = el.getAttribute("data-id");
  const alarms = data.alarms.map((a, i) => [a, i]).sort(([a, i], [b, j]) => alarmRank(a) - alarmRank(b) || i - j).map(([a]) => a);
  return patch(empty, { attrs: { hidden: alarms.length > 0 } }) + patch(table, { attrs: { hidden: alarms.length === 0 } })
    + reconcile(table.lastChild, alarms, (a) => a.id, (a) => alarmRow(listId, a, copy), (tr, a) => renderAlarmRow(tr, a, copy));
}

// ---- HistoryList / HistoryRow: what happened, in plain words (spec 7.2).
// Live: newest first. Replay: chronological, the current moment marked "Now"
// (the latest entry at or before it; later ones muted), each entry a button
// that jumps there. data: {rows: [{key, t, text, tone: "trip" | "warn" |
// null, tag}], now: t (replay only)}, rows oldest first as they happened.
// onJump(t) in a replay, from one listener on the list (rows carry data-t).
function historyList(mode, copy, onJump) {
  const el = h("div", { class: "c-history", "data-mode": mode },
    h("p", { class: "c-history__empty" }, copy.history.empty),
    h("ol", { class: "c-history__list" }));
  if (mode === "replay") el.addEventListener("click", (e) => {
    for (let n = e.target; n && n !== el; n = n.parentNode) {
      if (n.hasAttribute && n.hasAttribute("data-t")) { onJump(+n.getAttribute("data-t")); return; }
    }
  });
  return el;
}

function historyRow(replay, copy) {
  const parts = [h("span", { class: "c-history__time" }), alarmMarker(), h("span", { class: "c-history__text" }), tagChip(),
                 h("span", { class: "c-history__now", hidden: true }, copy.history.now)];
  return h("li", {}, ...(replay ? [h("button", { type: "button", class: "c-history__jump" }, ...parts)] : parts));
}

function renderHistoryRow(li, row, replay, current, future) {
  const [time, marker, text, chip, now] = (replay ? li.firstChild : li).children;
  // The current moment is marked on the jump button itself, where a screen reader lands (aria-current).
  let writes = patch(li, { attrs: { "data-tone": row.tone || null, "data-future": future, "data-current": current,
                                     "data-t": replay ? String(row.t) : null } })
    + (replay ? patch(li.firstChild, { attrs: { "aria-current": current ? "true" : null } }) : 0)
    + patch(time, { text: seconds(row.t, 1) }) + patch(marker, { attrs: { hidden: !row.tone } })
    + patch(text, { text: row.text }) + renderTagChip(chip, { tag: row.tag || null })
    + patch(now, { attrs: { hidden: !current } });
  if (row.tone) writes += renderAlarmMarker(marker, { cls: row.tone, lifecycle: "acknowledged" });
  return writes;
}

function renderHistoryList(el, data, copy) {
  const mode = el.getAttribute("data-mode"), replay = mode === "replay";
  let current = -1;
  if (replay) data.rows.forEach((r, i) => { if (r.t <= data.now) current = i; });
  const rows = data.rows.map((r, i) => ({ r, i }));
  if (!replay) rows.reverse();
  return patch(el.firstChild, { attrs: { hidden: data.rows.length > 0 } })
    + reconcile(el.lastChild, rows, ({ r }) => String(r.key), () => historyRow(replay, copy),
                (li, { r, i }) => renderHistoryRow(li, r, replay, replay && i === current, replay && i > current));
}

// ---- Checklist: the recovery steps (spec 9.6). Ordered; a step is done or
// blocked only because the data says so, never on a click. data: {steps:
// [{text, state: "pending" | "done" | "blocked", why}]}; `why` is the
// composed reason a blocked step waits for.
function checklist() {
  return h("ol", { class: "c-checklist" });
}

function renderChecklist(el, data, copy) {
  return reconcile(el, data.steps, (s, i) => `${i}:${s.text}`,
    () => h("li", {}, icon("check"), h("span", { class: "c-checklist__text" }), h("span", { class: "c-checklist__state" })),
    (li, s) => patch(li, { attrs: { "data-state": s.state } })
      + patchIcon(li.firstChild, s.state === "done" ? "check" : s.state === "blocked" ? "lock" : null)
      + patch(li.children[1], { text: s.text })
      + patch(li.children[2], { text: s.state === "done" ? copy.cards.checklist_done
                                     : s.state === "blocked" ? s.why || copy.cards.checklist_blocked : "" }));
}

// ---- AllNormalCard: the Operate rail when nothing is wrong (spec 8.5): the
// server's sentence and one button, the expected next action. data: {state:
// "idle" | "running", sentence, action: CommandButton data plus its
// `command`, or null}.
function allNormalCard(id, copy, onPress) {
  return h("section", { class: "c-allnormal", "aria-labelledby": `${id}-title` },
    h("h3", { class: "c-allnormal__title", id: `${id}-title` }, copy.cards.all_normal),
    h("p", { class: "c-allnormal__text" }), commandButton("start", copy, onPress));
}

function renderAllNormalCard(el, data, copy) {
  const [, text, button] = el.children;
  let writes = patch(el, { attrs: { "data-state": data.state } }) + patch(text, { text: data.sentence })
    + patch(button, { attrs: { hidden: !data.action } });
  if (data.action) writes += patch(button, { attrs: { "data-command": data.action.command } }) + renderCommandButton(button, data.action, copy);
  return writes;
}

// ---- Readout: a label, a value and its unit (spec 5.2, 11.3). A faulted
// instrument is striped and says so; a lost signal shows no number, since a
// failed transmitter's value means nothing. data: {value, unit, decimals,
// health: "normal" | "suspect" | "lost", tag}.
function readout(label) {
  return h("span", { class: "c-readout" }, h("span", { class: "c-readout__label" }, label), tagChip(),
    h("span", { class: "c-readout__value" }), h("span", { class: "c-readout__health", hidden: true }));
}

function renderReadout(el, data, copy) {
  const [, chip, value, health] = el.children, state = data.health || "normal";
  const d = data.decimals || 0;
  const number = state === "lost" || data.value === null || data.value === undefined ? copy.tests.values.missing
    : data.value.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }) + (data.unit ? `\u202f${data.unit}` : "");
  return patch(el, { attrs: { "data-health": state } }) + renderTagChip(chip, { tag: data.tag || null })
    + patch(value, { text: number })
    + patch(health, { attrs: { hidden: state === "normal" }, text: state === "normal" ? "" : copy.readings[state] });
}

// ---- Indicator: a switch (spec 5.2). Reached: filled in its class colour
// with a notch; normal: hollow; faulted: a dashed outline. The words
// ("reached", "normal") show only where asked (device detail); otherwise the
// indicator is part of its device's name. data: {state: "reached" | "normal"
// | "faulted", cls: "trip" | "warn" | "on", words}.
function indicator() {
  return h("span", { class: "c-indicator" },
    h("svg", { class: "c-indicator__lamp", viewBox: "0 0 12 12", "aria-hidden": "true", focusable: "false" },
      h("circle", { cx: "6", cy: "6", r: "5" }), h("path", { d: "M6 1.5v3.5" })),
    h("span", { class: "c-indicator__text", hidden: true }));
}

function renderIndicator(el, data, copy) {
  return patch(el, { attrs: { "data-state": data.state, "data-class": data.cls } })
    + patch(el.lastChild, { attrs: { hidden: !data.words }, text: data.words ? copy.readings[data.state] : "" });
}

// ---- IOTable: the raw I/O (spec 2.2, L3): every tag, its signal, its type
// and value, and whether it changed this tick. Built once from the tag list;
// a tag absent from the frame (an older recording) hides its row. data:
// {values, prev}; prev null on the first frame.
function ioTable(tags, copy) {
  return h("table", { class: "c-io" }, headRow(copy.io.columns),
    h("tbody", {}, ...tags.map((t) => h("tr", { "data-tag": t.name, "data-units": t.units || null },
      h("th", { scope: "row" }, h("code", {}, t.name)), h("td", {}, t.description || ""), h("td", {}, t.type),
      h("td", { class: "c-io__value" })))));
}

function ioValue(v, units) {
  return (typeof v === "boolean" ? (v ? "1" : "0") : v.toFixed(2)) + (units ? `\u202f${units}` : "");
}

function renderIOTable(el, data) {
  let writes = 0;
  for (const tr of el.lastChild.children) {
    const name = tr.getAttribute("data-tag"), v = data.values[name], present = v !== undefined;
    const changed = present && !!data.prev && data.prev[name] !== undefined && data.prev[name] !== v;
    writes += patch(tr, { attrs: { hidden: !present, "data-changed": changed } });
    if (present) writes += patch(tr.lastChild, { text: ioValue(v, tr.getAttribute("data-units")) });
  }
  return writes;
}

// ---- ActionChip: one action a test stage takes (spec 7.2): an operator
// action, a physical condition, a maintenance action or a process condition,
// with its kind in words for screen readers. data: {kind, text}; kind is
// verdict.py's classification.
function actionChip() {
  return h("span", { class: "c-chip" }, icon("hand"), h("span", { class: "c-sr" }), h("span", {}));
}

function renderActionChip(el, data, copy) {
  const kind = copy.action_kinds[data.kind];
  if (!kind) throw new Error(`no words for action kind "${data.kind}"`);  // copytext.py is tested to cover every kind
  return patch(el, { attrs: { "data-kind": data.kind } }) + patchIcon(el.firstChild, kind.icon)
    + patch(el.children[1], { text: `${kind.text}: ` }) + patch(el.lastChild, { text: data.text });
}

// ---- TestPanel / StageRow / CheckRow: a test's setup and stages, each with
// its actions, its checks and its time limit, marked as the run reaches them
// (spec 5.3). Built once from the plan (verdict.plan(), or a summary, which
// has the same shape); every status and time is handed to the render, which
// never judges one. data: {setup: "pending" | "running" | "done" | "failed",
// stages: [{status, elapsed_s, response_s, deadline, checks: [{status,
// actual}] or null}]}: `deadline` says a failure came at the stage's time
// limit (not an invariant stop). A stage outcome is announced once, politely.
// Finished steps fold to their heading and open on demand; a waiting stage
// shows its actions, and its checks once it runs (the shell mock, 2026-09-29).
const STAGE_ICONS = { running: "play", passed: "check", failed: "cross", not_observable: "question" };
const SETUP_ICONS = { done: "check", failed: "cross", running: "play" };
// A finished step folds to its one-line heading (Tabor, 2026-09-29): a passed
// stage, a completed setup. Everything else stays open.
const FOLDED = new Set(["passed", "done"]);

// One stage (or the setup, n 0): a native details/summary, so the heading is
// a disclosure control for keyboard and screen reader alike. The heading
// holds the mark, the title and, beneath the title, the status.
function stageItem(n, title, body, limit) {
  return h("li", { class: "c-stage", "data-stage": String(n), "data-limit": limit === null ? null : String(limit) },
    h("details", { class: "c-stage__box", open: true },
      h("summary", { class: "c-stage__head" }, icon("check"), h("span", { class: "c-stage__title" }, title),
        h("span", { class: "c-stage__status" })),
      h("div", { class: "c-stage__body" }, ...body)));
}

function testPanel(plan, copy) {
  const t = copy.tests;
  const setup = stageItem(0, t.setup, [h("ul", { class: "c-stage__setup" }, ...plan.setup_text.map((s) => h("li", {}, s)))], null);
  const stages = plan.stages.map((st) => stageItem(st.n,
    st.title ? fill(t.stage, { n: st.n, title: st.title }) : fill(t.stage_untitled, { n: st.n }),
    [h("p", { class: "c-stage__actions" }, ...(st.actions.length
      ? st.actions.map((a) => { const chip = actionChip(); renderActionChip(chip, a, copy); return chip; })
      : [h("span", { class: "c-stage__none" }, t.no_action)])),
     st.checks.length ? h("table", { class: "c-checks" }, headRow(t.check_columns),
       h("tbody", {}, ...st.checks.map((c) => h("tr", {}, h("th", { scope: "row" }, c.label),
         h("td", {}, valueText(c.expected, copy)), h("td", { class: "c-checks__result" }))))) : null],
    st.within_s));
  return h("div", { class: "c-test" }, h("ol", { class: "c-test__stages" }, setup, ...stages),
    h("p", { class: "c-sr", "aria-live": "polite" }));
}

function stageStatusText(status, stage, limit, copy) {
  const s = copy.tests.stage_status, l = limitText(limit);
  if (status === "running") return fill(s.running, { elapsed: seconds(stage.elapsed_s || 0, 1), limit: l });
  if (status === "passed") return stage.response_s === null || stage.response_s === undefined
    ? fill(s.passed_untimed, { limit: l }) : fill(s.passed, { response: seconds(stage.response_s, 2), limit: l });
  if (status === "failed") return stage.deadline ? fill(s.failed, { limit: l }) : s.failed_stopped;
  return s[status];
}

function renderCheckRow(tr, status, check, copy) {
  const marks = copy.tests.check_status;
  const shown = check && check.status ? check.status : status === "passed" ? "match" : null;
  const text = !shown ? "" : shown === "mismatch"
    ? fill(copy.tests.got, { mark: marks.mismatch, actual: valueText(check.actual, copy) }) : marks[shown];
  return patch(tr, { attrs: { "data-status": shown } }) + patch(tr.lastChild, { text });
}

// The heading's mark and status words, and the fold. A step is folded or
// opened only when its status changes, so a stage someone opened stays open
// through later polls. Returns [writes, whether the status changed].
function renderStageHead(li, status, iconName, words) {
  const box = li.firstChild, head = box.firstChild, before = li.getAttribute("data-status");
  let writes = patch(li, { attrs: { "data-status": status } }) + patchIcon(head.firstChild, iconName)
    + patch(head.lastChild, { text: words });
  if (before !== status) writes += patch(box, { attrs: { open: !FOLDED.has(status) } });
  return [writes, before !== null && before !== status];
}

function renderTestPanel(el, data, copy) {
  const [list, live] = el.children, items = Array.from(list.children);
  let [writes] = renderStageHead(items[0], data.setup, SETUP_ICONS[data.setup] || null, copy.tests.setup_status[data.setup]);
  let announce = null;
  items.slice(1).forEach((li, i) => {
    const stage = data.stages[i] || { status: "pending" }, status = stage.status;
    const words = stageStatusText(status, stage, +li.getAttribute("data-limit"), copy);
    const [w, changed] = renderStageHead(li, status, STAGE_ICONS[status] || null, words);
    writes += w;
    if (changed && status !== "running" && status !== "pending") {
      announce = `${li.firstChild.firstChild.children[1].textContent}. ${words}`;
    }
    const table = li.firstChild.lastChild.children[1];  // the body: actions, then the checks table when the stage has checks
    if (table) Array.from(table.lastChild.children).forEach((tr, j) => {
      writes += renderCheckRow(tr, status, stage.checks ? stage.checks[j] : null, copy);
    });
  });
  if (announce !== null) writes += patch(live, { text: announce });
  return writes;
}

// ---- VerdictBlock: PASS or FAIL, how many checks matched, and where the run
// first departed from the test (spec 5.3, 7.2). data: the run summary's
// {verdict, qualifier, checks_passed, checks_evaluated, first_divergence}.
function verdictBlock() {
  return h("div", { class: "c-verdict" },
    h("h3", { class: "c-verdict__head" }, h("span", { class: "c-vbadge" }), h("span", { class: "c-verdict__counts" })),
    h("p", { class: "c-verdict__where", hidden: true }),
    h("ul", { class: "c-verdict__unmet", hidden: true }));
}

function verdictState(verdict) {
  return verdict === "PASS" ? "pass" : verdict === "FAIL" ? "fail" : "unobservable";
}

function renderVerdictBlock(el, data, copy) {
  const t = copy.tests, [head, where, unmet] = el.children, d = data.first_divergence;
  const counts = fill(t.checks_matched, { passed: data.checks_passed, evaluated: data.checks_evaluated })
    + (data.qualifier ? ` (${data.qualifier})` : "");
  let place = "";
  if (d) place = d.stage === null || d.stage === undefined ? t.divergence_setup
    : fill(t.divergence, { n: d.stage, title: d.stage_title ? ` (${d.stage_title})` : "" })
      + (d.t === null || d.t === undefined ? "" : fill(t.divergence_at, { t: seconds(d.t, 2) }))
      + (d.kind ? `: ${d.kind}.` : ".");
  const lines = !d ? [] : d.unmet.length
    ? d.unmet.map((u) => fill(t.unmet, { label: u.label, expected: valueText(u.expected, copy), actual: valueText(u.actual, copy) }))
    : d.detail ? [d.detail] : [];
  return patch(el, { attrs: { "data-verdict": verdictState(data.verdict) } })
    + patch(head.firstChild, { attrs: { "data-verdict": verdictState(data.verdict) }, text: data.verdict })
    + patch(head.lastChild, { text: counts })
    + patch(where, { attrs: { hidden: !place }, text: place })
    + patch(unmet, { attrs: { hidden: lines.length === 0 } })
    + reconcile(unmet, lines, (line, i) => `${i}:${line}`, () => h("li"), (li, line) => patch(li, { text: line }));
}

// ---- RuntimeRow: one runtime in a comparison (spec 4.2), each saying how it
// was compared; the first is the reference. data (the table): {rows:
// [{runtime_id, runtime, verdict, checks, how, agrees: true | false | null}]}.
function runtimeTable(copy) {
  return h("table", { class: "c-runtimes" }, headRow(copy.tests.runtime_columns), h("tbody"));
}

function runtimeRow() {
  return h("tr", {}, h("th", { scope: "row" }), h("td", {}, h("span", { class: "c-vbadge" })), h("td"), h("td"),
    h("td", { class: "c-runtimes__agrees" }, icon("check"), h("span", {})));
}

function renderRuntimeRow(tr, row, copy) {
  const [name, verdict, checks, how, agrees] = tr.children;
  const said = row.agrees === true ? "yes" : row.agrees === false ? "no" : "reference";
  return patch(tr, { attrs: { "data-agrees": said } }) + patch(name, { text: row.runtime })
    + patch(verdict.firstChild, { attrs: { "data-verdict": verdictState(row.verdict) }, text: row.verdict })
    + patch(checks, { text: row.checks }) + patch(how, { text: row.how })
    + patchIcon(agrees.firstChild, said === "yes" ? "check" : said === "no" ? "cross" : null)
    + patch(agrees.lastChild, { text: copy.tests.agrees[said] });
}

function renderRuntimeTable(el, data, copy) {
  return reconcile(el.lastChild, data.rows, (r) => r.runtime_id, () => runtimeRow(), (tr, r) => renderRuntimeRow(tr, r, copy));
}

// ---- ScenarioCard: a test to run (spec 4.2, 8.5): its title, what it shows,
// Run & verify, Compare runtimes, and once it has a result, the verdict and
// Watch this run (a replay, in a new tab). Every card's buttons are locked
// (natively disabled) while any test operates the line. test: {id, title,
// description, stages}; data: {running, locked, result: {verdict, checks} or
// null, watch: href or null}. on: {run(id), compare(id)}.
function scenarioCard(test, copy, on) {
  const t = copy.tests, id = `test-${test.id}`;
  const run = h("button", { type: "button", class: "c-cmd", "data-primary": true }, h("span", { class: "c-cmd__label" }, t.run));
  const compare = h("button", { type: "button", class: "c-cmd" }, h("span", { class: "c-cmd__label" }, t.compare));
  run.addEventListener("click", () => { if (!run.hasAttribute("disabled")) on.run(test.id); });
  compare.addEventListener("click", () => { if (!compare.hasAttribute("disabled")) on.compare(test.id); });
  return h("article", { class: "c-scenario", "aria-labelledby": `${id}-title` },
    h("h3", { class: "c-scenario__title", id: `${id}-title` }, test.title),
    h("p", { class: "c-scenario__text" }, test.description),
    h("p", { class: "c-scenario__meta" }, plural(t.stages_count, test.stages)),
    h("p", { class: "c-scenario__result", hidden: true }, icon("play"), h("span", { class: "c-vbadge" }), h("span", {})),
    h("div", { class: "c-scenario__buttons" }, run, compare,
      h("a", { class: "c-scenario__watch", target: "_blank", rel: "noopener", hidden: true }, t.watch,
        h("span", { class: "c-sr" }, t.new_tab))));
}

function renderScenarioCard(el, data, copy) {
  const [, , , result, buttons] = el.children, [playing, badge, words] = result.children;
  const [run, compare, watch] = buttons.children, r = data.result;
  const shown = data.running || !!r;
  return patch(el, { attrs: { "data-state": data.running ? "running" : r ? "result" : "idle" } })
    + patch(result, { attrs: { hidden: !shown } }) + patchIcon(playing, data.running ? "play" : null)
    + patch(badge, { attrs: { hidden: data.running || !r, "data-verdict": r && !data.running ? verdictState(r.verdict) : null },
                     text: r && !data.running ? r.verdict : "" })
    + patch(words, { text: data.running ? copy.tests.running : r ? r.checks : "" })
    + patch(run, { attrs: { disabled: !!data.locked } }) + patch(compare, { attrs: { disabled: !!data.locked } })
    + patch(watch, { attrs: { hidden: !data.watch || data.running, href: data.watch || null } });
}
