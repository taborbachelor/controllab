"""The published style guide (frontend redesign, build step 6; the design
specification's D12 and section 12.4): one self-contained page generated
from the same sources the dashboard and replays use, so it cannot drift
from them. scripts/build_site.py writes it beside the demo runs.

Step 6 renders the tokens: every colour with what it is for, the contrast
pairs recomputed from tokens.css, the type scale, spacing, sizes, shape and
motion. Step 7 adds the icon set (plain markup) and the components in every
state, drawn in the browser by their real render functions from
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
  table { border-collapse: collapse; width: 100%; background: var(--surface); border: 1px solid var(--border); }
  th, td { text-align: left; padding: var(--sp-2) var(--sp-3); border-bottom: 1px solid var(--border); vertical-align: middle; }
  th { font-size: var(--fs-xs); color: var(--ink-muted); font-weight: 600; }
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
  .sg-stack { display: grid; gap: var(--sp-3); max-width: 480px; }
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
</main>
<footer>More components join this page as each is built.</footer>
<script>
const COPY = {copytext.ui_copy_json()};
const BADGE_ORDER = {order};
{components_js}
{GALLERY_JS}
</script>
</body>
</html>
"""
