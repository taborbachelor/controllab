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
