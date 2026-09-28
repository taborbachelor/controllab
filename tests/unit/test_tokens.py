"""The design tokens (frontend redesign, build step 6): every colour pair the
design specification verified still meets WCAG 2.2 AA and still has the
ratio the specification records; no frontend source writes a colour of its
own; every var(--name) used is defined; the pages inline the tokens first;
and every animation has a reduced-motion off switch.

The lint here is colours only. Spacing values and inline style= attributes
join it at build step 8, when the application shell replaces today's layout
(Tabor, 2026-09-27)."""
import re

import pytest

from services.visualization import tokens as tk
from services.visualization.page import HERE, assemble

# The frontend sources the lint covers. tokens.css is the one place a value
# may be written, so it is left out on purpose.
SOURCES = ("hmi.css", "hmi.js", "mimic.svg.html", "live_template.html", "replay_template.html", "styleguide.py",
           "components.css", "components.js", "icons.svg.html")
RAW_COLOUR = re.compile(
    r"(?<![&\w])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b"  # hex, not an entity or an id selector
    r"|\b(?:rgba?|hsla?)\(")


def source(name):
    return (HERE / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("pair", tk.PAIRS, ids=lambda p: f"{p.fg}-on-{p.bg}")
def test_every_verified_pair_meets_wcag_and_matches_the_specification(pair):
    ratio = tk.pair_ratio(pair)
    assert ratio >= pair.minimum, f"{pair.fg} on {pair.bg}: {ratio:.2f} < {pair.minimum}"
    # A token change that moves a ratio must update the specification's table too.
    assert round(ratio, 2) == pair.spec, f"{pair.fg} on {pair.bg}: {ratio:.2f}, the specification says {pair.spec}"


def test_the_contrast_arithmetic_is_wcag():
    assert tk.contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert tk.contrast("#777777", "#777777") == pytest.approx(1.0)
    assert tk.contrast("#595959", "#ffffff") == pytest.approx(7.0, abs=0.01)


def test_every_colour_token_is_defined_as_a_plain_colour():
    values = tk.tokens()
    for name, _ in tk.COLOURS:
        assert re.fullmatch(r"#[0-9a-f]{6}", values[name]), f"--{name}: {values[name]!r}"
    for pair in tk.PAIRS:
        assert pair.fg in values and pair.bg in values
    assert values["ok"] == values["equip-on"], "ok is the dark neutral, never green (spec 5.3)"


@pytest.mark.parametrize("name", SOURCES)
def test_no_frontend_source_writes_its_own_colour(name):
    found = [m.group(0) for m in RAW_COLOUR.finditer(source(name))]
    assert not found, f"{name} writes raw colours {found}: use a token from tokens.css"


def test_the_colour_lint_catches_what_it_should_and_nothing_else():
    assert RAW_COLOUR.search("color: #fff;") and RAW_COLOUR.search("fill='#b42318'")
    assert RAW_COLOUR.search("rgba(0, 0, 0, .5)")
    assert not RAW_COLOUR.search("#events tr, #scen-panel { }")  # id selectors
    assert not RAW_COLOUR.search("&#8230; &#x2014;")            # character entities
    # Known limit: an id spelled only with hex letters (#add, #fade) reads as a
    # colour. That fails loudly rather than letting a colour through; rename the id.


def test_every_token_used_is_defined():
    defined = set(re.findall(r"--([a-z0-9-]+)\s*:", source("tokens.css") + source("hmi.css") + source("replay_template.html")))
    for name in SOURCES:
        used = set(re.findall(r"var\(--([a-z0-9-]+)", source(name)))
        assert used <= defined, f"{name} uses undefined tokens {sorted(used - defined)}"


@pytest.mark.parametrize("template", ["live_template.html", "replay_template.html"])
def test_every_page_inlines_the_tokens_ahead_of_the_styles(template):
    page = assemble(template)
    assert page.index("--page: #e3e5e8") < page.index("Transitional aliases")


def test_every_animation_is_switched_off_under_reduced_motion():
    css = source("hmi.css") + source("replay_template.html") + source("components.css")
    animated = {sel.strip() for sel in re.findall(r"([^{}]+)\{[^{}]*\banimation:(?!\s*none\b)[^;}]+", css)}
    reduced = " ".join(re.findall(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\}\s*\}", css, re.S))
    assert animated, "expected the belt-flow animation"
    for selector in animated:
        assert re.search(re.escape(selector) + r"\s*\{\s*animation:\s*none", reduced), f"{selector} keeps animating"
    assert "@keyframes pulse" not in css, "a walkthrough target is a static outline (spec 5.5)"
