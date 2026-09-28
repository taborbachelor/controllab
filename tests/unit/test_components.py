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
