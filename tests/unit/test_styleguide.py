"""The published style guide (frontend redesign, build step 6): generated
from tokens.css and tokens.py, so it shows every colour token with its real
value and every verified contrast pair with its recomputed ratio, needs no
script, and is the same bytes every time."""
import json
import re

from services.visualization import copytext, styleguide
from services.visualization import tokens as tk


def test_the_style_guide_shows_every_colour_token_with_its_value():
    page = styleguide.render()
    values = tk.tokens()
    for name, _ in tk.COLOURS:
        assert f"<code>--{name}</code></td><td class=\"mono\">{values[name]}</td>" in page, name


def test_the_style_guide_shows_every_pair_with_its_recomputed_ratio():
    page = styleguide.render()
    for p in tk.PAIRS:
        assert f"<code>--{p.fg}</code> on <code>--{p.bg}</code>" in page
        assert f"{tk.pair_ratio(p):.2f} : 1" in page
    assert "FAILS" not in page


def test_the_style_guide_is_self_contained_and_deterministic():
    page = styleguide.render("https://example.invalid/repo")
    assert page == styleguide.render("https://example.invalid/repo")
    assert page.count("<script") == 1 and "<script src" not in page, "one inline script: the component gallery"
    assert not re.search(r"""(?:src|href)=["']https?://(?!example\.invalid/repo/)""", page), "no external resource"
    assert " style=" not in page, "per-token classes, never inline styles"
    assert page.index("--page: #e3e5e8") < page.index(".sw-page")
    # Everything up to the components section reads without script (Tabor, 2026-09-28).
    assert page.index('id="components"') < page.index("<script")


def test_the_style_guide_shows_every_icon_and_draws_every_badge():
    page = styleguide.render()
    for name in re.findall(r'<symbol id="i-([a-z-]+)"', page):
        assert f'<use href="#i-{name}"/></svg><code class="sg-caption">{name}</code>' in page, name
    order = json.loads(re.search(r"const BADGE_ORDER = (\[.*?\]);", page).group(1))
    assert order == list(copytext.STATE_BADGES)
    assert "function renderStateBadge(" in page and "<noscript>" in page


def test_the_test_results_gallery_is_drawn_from_real_runs():
    """A pass and a fail from the runner itself (the fail against a deliberate
    regression), so the gallery shows the shapes the dashboard will get."""
    page = styleguide.render()
    runs = {name: json.loads(re.search(rf"const {name} = (\{{.*?\}});\n", page).group(1)) for name in ("SG_PASS", "SG_FAIL")}
    assert runs["SG_PASS"]["verdict"] == "PASS" and runs["SG_FAIL"]["verdict"] == "FAIL"
    assert runs["SG_FAIL"]["regression"] == styleguide.GALLERY_REGRESSION and runs["SG_FAIL"]["first_divergence"]
    assert "function renderTestPanel(" in page and "renderVerdictBlock(v, summary, COPY)" in page
