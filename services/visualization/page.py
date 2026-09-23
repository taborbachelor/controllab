"""Assembles a Visualization page from its template plus the shared HMI
pieces (Phase 6 step 3): hmi.css, mimic.svg.html, and hmi.js are written
once and inlined into both the replay viewer and the live dashboard, so
the line is drawn identically in both and a fix to the mimic lands in
both. Inlined, not linked: the replay is a single file you can email or
commit, and the live server stays a handful of routes.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent
PIECES = {
    "/*__HMI_CSS__*/": "hmi.css",
    "<!--__MIMIC_SVG__-->": "mimic.svg.html",
    "/*__HMI_JS__*/": "hmi.js",
}


def assemble(template_name: str) -> str:
    page = (HERE / template_name).read_text(encoding="utf-8")
    for placeholder, filename in PIECES.items():
        assert page.count(placeholder) == 1, f"{template_name} must contain {placeholder} exactly once"
        page = page.replace(placeholder, (HERE / filename).read_text(encoding="utf-8"))
    return page
