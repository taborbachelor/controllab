"""The interface's fixed words, in one place (frontend redesign, build step 7;
the design specification's section 5.4: the page holds no mapping from
identifiers to words of its own). Pages receive these as JSON and the
components render them; tests pin that every identifier the controller can
produce has its words here.

Step 7a: the line-state badges (the specification's section 5.1). Later
component steps add their own tables here.
"""
from __future__ import annotations

import json

from services.control.line_state import LineState

# The badge for each line state (the snapshot's `state`, i.e. LineState name
# lowercased), plus `external` (an external controller runs the line) and
# `testing` (a second badge while a test operates the line). Each: the
# words (binding, section 5.1), a variant that sets fill and outline, and an
# icon from the in-house set, or None. PAUSED is shown on the clock, not here.
STATE_BADGES: dict[str, dict] = {
    "idle": {"text": "READY", "variant": "outline", "icon": None},
    "starting": {"text": "STARTING", "variant": "dashed", "icon": "clock"},
    "running": {"text": "RUNNING", "variant": "on", "icon": None},
    "stopping": {"text": "STOPPING", "variant": "dashed", "icon": "clock"},
    "manual": {"text": "MANUAL", "variant": "manual", "icon": "hand"},
    "loading": {"text": "BATCH · LOADING", "variant": "on", "icon": "batch"},
    "processing": {"text": "BATCH · HOLDING", "variant": "on", "icon": "batch"},
    "discharging": {"text": "BATCH · DISCHARGING", "variant": "on", "icon": "batch"},
    "cleaning": {"text": "BATCH · CLEANING OUT", "variant": "on", "icon": "batch"},
    "faulted": {"text": "TRIPPED", "variant": "trip", "icon": "octagon"},
    "estopped": {"text": "EMERGENCY STOP", "variant": "estop", "icon": "estop"},
    "external": {"text": "EXTERNAL CONTROLLER", "variant": "external", "icon": "link"},
    "testing": {"text": "TESTING", "variant": "testing", "icon": "flask"},
}

# Every line state the controller can report must have a badge.
assert {s.name.lower() for s in LineState} <= set(STATE_BADGES), "a LineState has no badge"


def ui_copy() -> dict:
    """Everything the components need to put words on screen."""
    return {"badges": STATE_BADGES}


def ui_copy_json() -> str:
    """ui_copy() as JSON safe to inline in a <script> (no closing tag inside)."""
    return json.dumps(ui_copy(), ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
