"""The bounded, structured description of the line that a model sees when
proposing scenarios (docs/CONTROL-LAB.md §10, Phase 8 step 2b).

Built from the same sources the system itself runs on -- the I/O image,
the scenario vocabulary, the §6.3 interlock rows, the controller's state,
fault-reason, alarm, and start-inhibit tables, the rig's timing -- so it
can't describe a different line than the one the candidates will be run
against. VALUE_SHAPES is the one hand-written part (what value each
vocabulary key takes); a drift test ties its keys to the vocabulary.

Deterministic (no timestamps, sorted where order isn't meaningful) and
size-checked: over MAX_CONTEXT_CHARS is an error, never a silent
truncation -- a model working from a quietly clipped spec is worse than
no model.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.ai.limits import MAX_CONTEXT_CHARS
from services.control.line_state import StartInhibit
from services.protocols.controller_status import ALARMS, FAULT_REASONS, LINE_STATES
from services.simulation.engine.plant_io import build_line_io_image
from services.testing.report import INTERLOCKS
from services.testing.rig import (
    DEFAULT_DEVICE_PROOF_TIMEOUT_S,
    DEFAULT_GATE_TRAVEL_TIMEOUT_S,
    DEFAULT_LINE_CONFIG,
    DEFAULT_PLANT_CONFIG,
    DT,
)
from services.testing.scenario import Scenario

# What value each vocabulary key takes, for the model. Keys must match the
# vocabulary exactly (tests/unit/test_ai_generation.py).
VALUE_SHAPES: dict[str, str] = {
    # given / when (actions)
    "start": "true (one-shot operator command)",
    "stop": "true (one-shot operator command)",
    "reset": "true (one-shot operator command)",
    "acknowledge": "true (one-shot operator command: acknowledge all alarms)",
    "select_manual": "true (one-shot: select Manual mode; accepted only at rest)",
    "select_auto": "true (one-shot: select Auto mode; accepted only at rest, every Manual device off)",
    "start_conveyor": "true (one-shot Manual pushbutton; refused in Auto)",
    "stop_conveyor": "true (one-shot Manual pushbutton; also drops the feeder)",
    "open_gate": "true (one-shot Manual pushbutton; refused in Auto)",
    "close_gate": "true (one-shot Manual pushbutton)",
    "start_feeder": "true (one-shot Manual pushbutton; needs the conveyor proven running; refused in Auto)",
    "stop_feeder": "true (one-shot Manual pushbutton)",
    "estop": '"tripped" or "healthy"',
    "conveyor_trip": "true/false (inject/clear a conveyor overload trip; trips only a running motor)",
    "feeder_trip": "true/false (inject/clear a feeder VFD trip; trips only a running motor)",
    "conveyor_fail_to_start": "true/false (conveyor motor never proves running)",
    "feeder_fail_to_start": "true/false (feeder motor never proves running)",
    "sensor_stuck": '"<input tag>" (that instrument freezes at its last reading; undetectable by the controller)',
    "sensor_failed": '"WT-105" (signal lost: reads 0.0 and its channel fault WT-105.FLT sets; only WT-105 has a diagnostic)',
    "sensor_restored": '"<input tag>" (the instrument is repaired at the field)',
    "feeder_jam": "true/false (jam/clear the feeder discharge: flow stops, drive keeps running, plug switch LSH-103 makes after the screw pushes against it)",
    "gate_stuck": "true/false (gate never reaches its limit switch)",
    "belt_slip": "true/false (conveyor motion switch reads no motion)",
    "feeder_drive_reset": "true (field reset of the feeder drive's own fault latch)",
    "conveyor_overload_reset": "true (field reset of the conveyor overload relay)",
    "gate_reset": "true (field reset of the gate actuator fault)",
    "hopper_level_pct": "number 0-100 (set the hopper level directly)",
    "bin_level_pct": "number 0-100 (set the bin level directly)",
    # expect (observations)
    "line_state": '"idle" | "starting" | "running" | "stopping" | "faulted" | "estopped" | "manual"',
    "mode": '"auto" | "manual"',
    "fault_reason": "string (see fault_reasons) or null",
    "conveyor_running": "true/false",
    "feeder_running": "true/false",
    "feeder_run_commanded": "true/false (the controller's feeder run output; drops in the same scan as a trip)",
    "conveyor_run_commanded": "true/false (the controller's conveyor run output)",
    "gate_open_commanded": "true/false (the controller's gate open output; the gate itself takes its travel time)",
    "feeder_flowing": "true/false (material actually leaving the feeder; false while running = jammed)",
    "gate_open": "true/false",
    "estop_healthy": "true/false",
    "spilled_kg": "number",
    "spilled": "true/false",
    "belt_empty": "true/false (nothing left on the conveyor belt)",
    "hopper_level_kg": "number",
    "any_unacknowledged_trip": "true/false",
    "latched_alarm_ids": "sorted list of alarm ids (see alarms)",
    "first_out": "alarm id of the first-out alarm, or null",
    "hopper_weight_agrees": "true/false (WT-105's reading within 5 kg of the true hopper weight)",
    "start_inhibit": 'sorted list of reason names, ["NONE"] when the most recent start was accepted',
}

RULES = [
    "A scenario has `given` (preconditions), `when` (the stimulus under test), `expect` (conditions that must all "
    "hold), and `within` (a time limit in seconds). The runner applies `given`, lets it settle, applies `when`, then "
    "polls `expect` every 0.1 s scan until all hold or the limit passes.",
    "`given` may include line_state: \"idle\", \"running\" (the full start sequence is driven first) or \"manual\" "
    "(Manual mode selected from idle, every device off; then the device pushbuttons apply).",
    "`expect` must describe the RESPONSE to `when`: a scenario whose expectations would already hold without the "
    "`when` stimulus is rejected as vacuous by the review gate. Assert something only the stimulus causes.",
    "Name the stimulus under test in `trigger` (one or more `when` keys). The review gate removes exactly those keys "
    "and requires the scenario to FAIL without them; anything else in `when` is treated as setup.",
    "A refused start must be proven with start_inhibit, not only by the line staying idle.",
    "Set `within` to the time the behavior needs plus some margin; use the timing facts below.",
    "Prefer behavior not already covered by the existing scenarios listed below; do not duplicate them.",
    "Use only the vocabulary keys given; any other key is rejected before anything runs.",
]

EXAMPLES = ("faults/feeder_trip_while_running.yaml", "faults/bin_low_blocks_start.yaml", "shutdown/normal_stop.yaml")


def build_context(scenarios_dir: Path) -> str:
    io = build_line_io_image()
    existing = Scenario.discover(scenarios_dir)
    spec = {
        "io_tags": [
            {"tag": n, "type": io.tag(n).type.name, "units": io.tag(n).units, "description": io.tag(n).description}
            for n in io.names()
        ],
        "vocabulary": VALUE_SHAPES,
        "interlock_rows": [{"name": r.name, "kind": r.kind} for r in INTERLOCKS],
        "line_states": [s.name.lower() for s in LINE_STATES],
        "fault_reasons": [r for r in FAULT_REASONS if r],
        "alarms": [{"id": a, "description": d, "class": "warning" if w else "trip"} for a, d, w in ALARMS],
        "start_inhibit_reasons": [m.name for m in StartInhibit if m],
        "timing": {
            "scan_s": DT,
            "conveyor_proof_timeout_s": DEFAULT_LINE_CONFIG["conveyor_proof_timeout_s"],
            "purge_time_s": DEFAULT_LINE_CONFIG["purge_time_s"],
            "motor_start_proof_timeout_s": DEFAULT_DEVICE_PROOF_TIMEOUT_S,
            "gate_travel_timeout_s": DEFAULT_GATE_TRAVEL_TIMEOUT_S,
            "gate_travel_time_s": DEFAULT_PLANT_CONFIG["gate_travel_time_s"],
            "motor_start_delay_s": DEFAULT_PLANT_CONFIG["conveyor_start_delay_s"],
            "feeder_plug_detect_s": DEFAULT_PLANT_CONFIG["feeder_plug_detect_s"],
            "normal_start_to_running_s_measured": 1.5,
            "hopper_high_pct": DEFAULT_PLANT_CONFIG["hopper_high_pct"],
            "hopper_high_high_pct": DEFAULT_PLANT_CONFIG["hopper_high_high_pct"],
            "bin_low_pct": DEFAULT_PLANT_CONFIG["bin_low_pct"],
            "default_bin_level_pct": 20.0,
        },
        "existing_scenarios": sorted(s.name for s in existing),
    }
    examples = "\n".join(
        f"--- example: {name}\n{(scenarios_dir / name).read_text(encoding='utf-8').strip()}" for name in EXAMPLES
    )
    text = (
        "You propose commissioning test scenarios for a simulated bulk-material line "
        "(bin -> gate -> feeder -> conveyor -> hopper) with a deterministic controller. Your output is only ever a "
        "proposal: every candidate goes through an automated review gate and then an engineer. You never run or "
        "change anything.\n\n"
        "## Rules\n" + "\n".join(f"- {r}" for r in RULES) + "\n\n"
        "## Line specification (JSON)\n" + json.dumps(spec, indent=1, sort_keys=False) + "\n\n"
        "## Example scenarios (YAML)\n" + examples + "\n"
    )
    if len(text) > MAX_CONTEXT_CHARS:
        raise ValueError(f"generation context is {len(text)} chars, over the {MAX_CONTEXT_CHARS} limit")
    return text
