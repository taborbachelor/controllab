"""The interface's fixed words, in one place (frontend redesign, build step 7;
the design specification's section 5.4: the page holds no mapping from
identifiers to words of its own). Pages receive these as JSON and the
components render them; tests pin that every identifier the controller can
produce has its words here.

Step 7a: the line-state badges (the specification's section 5.1). Step 7b:
the console's command labels and the controls' own fixed words. Step 7c: the
words around alarms, history, readings and test results. The
sentences built from controller data (refusals, "can't yet" reasons, status)
are composed server-side by their own modules and passed to the components
as text; they are not here.
"""
from __future__ import annotations

import json

from services.control.line_controller import COMMANDS
from services.control.line_state import LineState
from services.testing.verdict import KINDS as VERDICT_KINDS

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

# Step 7c: the fixed words around alarms, history, readings and test results
# (spec 4.4, 5.2, 5.3, 7.2). The alarm and history sentences themselves, and
# the recovery steps, arrive composed (their tables come with the cause
# chain, step 9). A count's words are [one, many], with {n} for the number.
ALARMS: dict[str, object] = {
    "class": {"trip": "Trip", "warn": "Warning"},
    # The controller's own flags, in words (spec 4.4): active and not
    # acknowledged is new; acknowledged and active; cleared but not yet acknowledged.
    "lifecycle": {"new": "New: active, not acknowledged", "acknowledged": "Acknowledged, still active",
                  "cleared": "Cleared, not acknowledged"},
    "new_label": "NEW",
    "first_out": "Started it",
    "first_out_help": "The first alarm; the others followed from it.",
    "columns": ["Alarm", "Status"],
    "empty": "No alarms.",
    "count_trip": ["{n} trip alarm", "{n} trip alarms"],
    "count_warn": ["{n} warning", "{n} warnings"],
    "none": "No alarms",
    "show": "Show",
    "show_label": "{counts}, show",
}

HISTORY: dict[str, str] = {
    "empty": "Nothing has happened yet.",
    "now": "Now",
}

# A reading's health and a switch's state (spec 5.2).
READINGS: dict[str, str] = {
    "lost": "Signal lost",
    "suspect": "Reading suspect",
    "reached": "reached",
    "normal": "normal",
    "faulted": "Reading suspect",
}

CARDS: dict[str, str] = {
    "all_normal": "Nothing needs attention",
    "checklist_done": "done",
    "checklist_blocked": "Not possible yet",
}

IO: dict[str, list[str]] = {
    "columns": ["Tag", "Signal", "Type", "Value"],
}

# What each kind of stage action is (the kinds verdict.py classifies), in
# the Test view's words: a fault the test injects is a physical condition, a
# field repair a maintenance action (spec 4.3, 5.4).
ACTION_KINDS: dict[str, dict] = {
    "operator": {"text": "Operator action", "icon": "hand"},
    "fault": {"text": "Physical condition", "icon": "flask"},
    "repair": {"text": "Maintenance action", "icon": "wrench"},
    "process": {"text": "Process condition", "icon": "batch"},
}
assert set(ACTION_KINDS) == set(VERDICT_KINDS), "every kind of stage action needs its words"

# Test results (spec 5.3). {elapsed}, {response} and {t} are seconds, {limit} the stage's time limit.
TESTS: dict[str, object] = {
    "setup": "Setup: bring the line to the starting condition",
    "setup_status": {"pending": "Waiting", "running": "Setting up…", "done": "Done", "failed": "Setup failed"},
    "stage": "Stage {n}: {title}",
    "stage_untitled": "Stage {n}",
    "no_action": "No action: keep watching",
    "stage_status": {
        "pending": "Waiting",
        "running": "{elapsed} of {limit}",
        "passed": "Passed in {response} (limit {limit})",
        "passed_untimed": "Passed (limit {limit})",
        "failed": "Failed at its {limit} deadline",
        "failed_stopped": "Failed: the run stopped here",
        "not_run": "Not run: the test stops at the first failure",
        "not_observable": "Not observable: this controller publishes no status block",
    },
    "check_columns": ["Check", "Expected", "Result"],
    "check_status": {"match": "MATCH", "mismatch": "MISMATCH", "not_reached": "not reached", "not_run": "not run",
                     "not_observed": "not observed"},
    "got": "{mark}, got {actual}",
    "values": {"yes": "yes", "no": "no", "none": "none", "missing": "—"},
    "checks_matched": "{passed}/{evaluated} checks matched",
    "divergence": "Failed at stage {n}{title}",
    "divergence_at": ", at {t} (its deadline)",
    "divergence_setup": "Failed while setting up the starting condition",
    "unmet": "{label}: expected {expected}, got {actual}",
    "runtime_columns": ["Runtime", "Result", "Checks", "How it was compared", "Agrees"],
    "agrees": {"yes": "Agrees", "no": "Disagrees", "reference": "Reference run"},
    "run": "Run & verify",
    "compare": "Compare runtimes",
    "watch": "Watch this run",
    "running": "Running now…",
    "new_tab": " (opens in a new tab)",
    "stages_count": ["{n} stage", "{n} stages"],
}


def ui_copy() -> dict:
    """Everything the components need to put words on screen."""
    return {"badges": STATE_BADGES, "commands": COMMAND_LABELS, "controls": CONTROLS, "alarms": ALARMS,
            "history": HISTORY, "readings": READINGS, "cards": CARDS, "io": IO, "action_kinds": ACTION_KINDS,
            "tests": TESTS}


def ui_copy_json() -> str:
    """ui_copy() as JSON safe to inline in a <script> (no closing tag inside)."""
    return json.dumps(ui_copy(), ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
