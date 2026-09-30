"""The design tokens (tokens.css) read back in Python: their values, the
colour pairs the design specification verified for contrast (its section
6.1), and the WCAG arithmetic to recompute them. The contrast test and the
style guide both use this, so neither keeps its own copy of the pairs.

tokens.css is the only source of the values; this module parses it and
holds no colour of its own.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

TOKENS_CSS = Path(__file__).parent / "tokens.css"

TEXT = 4.5      # WCAG 2.2 AA, normal-size text
GRAPHIC = 3.0   # WCAG 2.2 AA, graphics, control borders and focus rings


@dataclass(frozen=True)
class Pair:
    fg: str
    bg: str
    minimum: float   # TEXT or GRAPHIC
    spec: float      # the ratio the specification records for this pair
    use: str


# Every pair the specification's colour table lists, with the ratio it
# records. The test fails when a token change drops a pair below its
# minimum, and also when the recorded ratio no longer matches: then the
# specification's table must be updated with the token.
PAIRS: tuple[Pair, ...] = (
    Pair("ink", "page", TEXT, 12.84, "Body text on the page background"),
    Pair("ink-muted", "page", TEXT, 5.53, "Secondary text on the page background"),
    Pair("ink", "surface", TEXT, 14.85, "Body text on panels"),
    Pair("ink-muted", "surface", TEXT, 6.40, "Secondary text and tag chips on panels"),
    Pair("ink-muted", "surface-sunken", TEXT, 5.90, "Secondary text in drawers and table stripes"),
    Pair("ink-muted", "trip-tint", TEXT, 6.11, "Secondary text on a trip card"),
    Pair("border-strong", "surface", GRAPHIC, 3.52, "Control and input borders"),
    Pair("equip-stroke", "surface", GRAPHIC, 7.46, "Equipment outlines and lines"),
    Pair("ink-inverse", "equip-on", TEXT, 10.04, "Text on RUNNING and PASS"),
    Pair("equip-on", "surface-raised", GRAPHIC, 9.70, "Running equipment on controls and cards"),
    Pair("material", "surface-raised", GRAPHIC, 4.55, "Material in bins, hopper and on the belt"),
    Pair("trip", "surface", TEXT, 6.03, "Trip text and markers"),
    Pair("ink-inverse", "trip", TEXT, 6.57, "Text on TRIPPED and FAIL"),
    Pair("trip", "trip-tint", TEXT, 5.75, "Trip text on a trip card"),
    Pair("warn", "surface", TEXT, 5.43, "Warning text and marker strokes"),
    Pair("warn", "warn-fill", GRAPHIC, 3.16, "A warning marker's stroke on its fill"),
    Pair("warn", "warn-tint", TEXT, 5.37, "Warning text on a warning row"),
    Pair("disagree", "surface", GRAPHIC, 4.29, "Commanded-not-confirmed outline on panels"),
    Pair("disagree", "surface-raised", GRAPHIC, 4.52, "Commanded-not-confirmed outline on stopped equipment"),
    Pair("info", "surface", TEXT, 6.49, "Links, focus, MANUAL and TESTING"),
    Pair("ink-inverse", "info", TEXT, 7.08, "Text on a primary action"),
    Pair("info", "info-tint", TEXT, 6.04, "Info text on a running-stage row"),
    # Added with the console controls (build step 7b, 2026-09-28; the specification's table updated to match).
    Pair("ink", "surface-raised", TEXT, 15.67, "Text on buttons and cards"),
    Pair("ink-muted", "surface-raised", TEXT, 6.75, "Secondary text on buttons and cards"),
    Pair("trip", "surface-raised", TEXT, 6.36, "The E-stop button's label"),
    Pair("ink", "warn-tint", TEXT, 14.68, "A refusal note's text"),
    # Added with alarms, history and test results (build step 7c, 2026-09-29).
    Pair("ink", "trip-tint", TEXT, 14.17, "A new trip alarm's row; a failed stage"),
    Pair("ink", "info-tint", TEXT, 13.84, "The running stage; an I/O row that just changed"),
    Pair("ink-muted", "info-tint", TEXT, 5.97, "Secondary text on the running stage"),
    Pair("ink-muted", "warn-tint", TEXT, 6.33, "A new warning's status words"),
    Pair("warn", "surface-raised", TEXT, 5.73, "A faulted reading's words; a physical-condition chip"),
    Pair("trip", "surface-sunken", TEXT, 5.55, "A trip marker in the history drawer"),
    Pair("warn", "surface-sunken", TEXT, 5.01, "A warning marker in the history drawer"),
    Pair("info", "surface-sunken", TEXT, 5.98, "The replay history's Now marker; links in drawers"),
)

# The colour tokens in the specification's order, with what each is for.
COLOURS: tuple[tuple[str, str], ...] = (
    ("page", "Page background"),
    ("surface", "Panels, status bar, rail"),
    ("surface-sunken", "Drawers, table stripes, code"),
    ("surface-raised", "Controls, cards, stopped equipment"),
    ("border", "Decorative dividers only"),
    ("border-strong", "Control and input borders"),
    ("ink", "Body text"),
    ("ink-muted", "Secondary text, tag chips"),
    ("ink-inverse", "Text on dark and coloured fills"),
    ("equip-stroke", "Equipment outlines, lines"),
    ("equip-on", "Confirmed running or open; RUNNING; PASS"),
    ("equip-off", "Confirmed stopped or closed"),
    ("material", "Material in bins, hopper, on the belt"),
    ("trip", "Trips, trip alarms, TRIPPED, FAIL, MISMATCH"),
    ("trip-tint", "Background of trip cards and rows"),
    ("warn", "Warning text and marker strokes"),
    ("warn-fill", "Warning marker fill, always with a warn stroke"),
    ("warn-tint", "Background of warning rows"),
    ("disagree", "Dashed commanded-not-confirmed stroke"),
    ("info", "Focus, primary action, MANUAL, TESTING, links"),
    ("info-tint", "Running-stage row, info cards"),
    ("ok", "Passed stage, MATCH: deliberately not green"),
    ("focus", "Focus ring"),
)

_ROOT = re.compile(r"^:root\s*\{(.*?)^\}", re.S | re.M)
_DECL = re.compile(r"--([a-z0-9-]+)\s*:\s*([^;]+);")
_VAR = re.compile(r"^var\(--([a-z0-9-]+)\)$")


def tokens(css: str | None = None) -> dict[str, str]:
    """Every token in tokens.css's first :root block, name (without --) to
    its value as written, var() references resolved."""
    css = TOKENS_CSS.read_text(encoding="utf-8") if css is None else css
    raw = {name: value.strip() for name, value in _DECL.findall(_ROOT.search(css).group(1))}

    def resolve(name: str, seen: tuple[str, ...] = ()) -> str:
        assert name not in seen, f"token cycle: {' -> '.join(seen + (name,))}"
        m = _VAR.match(raw[name])
        return resolve(m.group(1), seen + (name,)) if m else raw[name]

    return {name: resolve(name) for name in raw}


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    assert len(h) == 6, f"a colour token must be #rrggbb, got {hex_colour!r}"
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two #rrggbb colours."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def pair_ratio(pair: Pair, values: dict[str, str] | None = None) -> float:
    values = tokens() if values is None else values
    return contrast(values[pair.fg], values[pair.bg])
