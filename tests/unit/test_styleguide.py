"""The published style guide (frontend redesign, build step 6): generated
from tokens.css and tokens.py, so it shows every colour token with its real
value and every verified contrast pair with its recomputed ratio, needs no
script, and is the same bytes every time."""
import re

from services.visualization import styleguide
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
    assert "<script" not in page
    assert not re.search(r"""(?:src|href)=["']https?://(?!example\.invalid/repo/)""", page), "no external resource"
    assert " style=" not in page, "per-token classes, never inline styles"
    assert page.index("--page: #e3e5e8") < page.index(".sw-page")
