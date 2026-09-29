"""The interface's fixed words, in one place (frontend redesign, build step 7;
the design specification's section 5.4: the page holds no mapping from
identifiers to words of its own). Pages receive these as JSON and the
components render them; tests pin that every identifier the controller can
produce has its words here.

Step 7a: the line-state badges (the specification's section 5.1). Step 7b:
the console's command labels and the controls' own fixed words. The
sentences built from controller data (refusals, "can't yet" reasons, status)
are composed server-side by their own modules and passed to the components
as text; they are not here.
"""
from __future__ import annotations

import json

from services.control.line_controller import COMMANDS
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

# The console's label for every operator command (controller verbs only,
# spec 5.4). A Manual device's buttons sit in a group named for the device,
# so "Start" there reads as "Start" within "Conveyor".
COMMAND_LABELS: dict[str, str] = {
    "start": "Start", "stop": "Stop", "acknowledge": "Acknowledge", "reset": "Reset",
    "select_auto": "Auto", "select_manual": "Manual", "select_batch": "Batch",
    "start_conveyor": "Start", "stop_conveyor": "Stop",
    "open_gate": "Open", "close_gate": "Close",
    "start_feeder": "Start", "stop_feeder": "Stop",
    "open_outlet": "Open", "close_outlet": "Close",
}
assert set(COMMAND_LABELS) == set(COMMANDS), "every operator command needs exactly one label"

# The controls' own fixed words (spec 4.1, 4.2, 7.2, 8.4).
CONTROLS: dict[str, object] = {
    "sent": "Sent…",
    "preview_unknown": "The controller decides when you press.",
    "locked": "A test is operating the line. Controls return when it finishes.",
    "estop_press": "Press E-stop",
    "estop_release": "Release E-stop",
    "estop_pressed": "E-stop pressed",
    "condition_active": "Active",
    "maintenance_prefix": "Maintenance action:",
    "done": "Done",
    "batch_steps": [["loading", "Load"], ["processing", "Hold"], ["discharging", "Discharge"], ["cleaning", "Clean out"]],
    "batch_loaded": "Loaded {loaded} of {target}",
    "recipe_fields": [["recipe_a_kg", "Bin A", "kg"], ["recipe_b_kg", "Bin B", "kg"], ["recipe_c_kg", "Bin C", "kg"], ["hold_s", "Hold", "s"]],
    "recipe_apply": "Apply recipe",
    "recipe_invalid": "Enter a number, 0 or more.",
    "recipe_applied": "Applied.",
    "recipe_changed": "Changed, not applied yet.",
}
_BATCH = {s.name.lower() for s in (LineState.LOADING, LineState.PROCESSING, LineState.DISCHARGING, LineState.CLEANING)}
assert {key for key, _ in CONTROLS["batch_steps"]} == _BATCH, "every batch state is one BatchProgress step"


def ui_copy() -> dict:
    """Everything the components need to put words on screen."""
    return {"badges": STATE_BADGES, "commands": COMMAND_LABELS, "controls": CONTROLS}


def ui_copy_json() -> str:
    """ui_copy() as JSON safe to inline in a <script> (no closing tag inside)."""
    return json.dumps(ui_copy(), ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
