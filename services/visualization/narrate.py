"""Plain-English narration of the live line, for someone who has never seen
it before: what the line is doing, why, and what to do next.

A pure function of the dashboard's snapshot (LiveSession.snapshot() plus
the pacer's `running`), so every case is testable without a browser. It
explains; it never decides anything. Everything it says is derived from
what the controller and the plant already report -- if the narration and
the alarm board ever disagree, the alarm board is right and this has a bug.

Output: {"tone", "headline", "detail", "steps"}. `tone` is one of ok /
info / warn / trip (the card's color). `steps` is an ordered checklist,
each {"text", "done"}, used for recovery procedures so a newcomer can see
which parts are finished.
"""
from __future__ import annotations

from services.testing.rig import DEFAULT_PLANT_CONFIG

_HH_KG = DEFAULT_PLANT_CONFIG["hopper_capacity_kg"] * DEFAULT_PLANT_CONFIG["hopper_high_high_pct"] / 100

# Why the controller tripped the line (LineController.fault_reason), in
# plain words, and what the operator does about the cause before resetting.
_FAULTS: dict[str, tuple[str, str]] = {
    "hopper high-high": (
        "The hopper got too full (95 % or more), so the controller stopped everything to prevent an overflow.",
        "Lower the hopper level (Engineer tools → Set hopper level, e.g. 50 %)",
    ),
    "feeder trip": (
        "The feeder's motor drive reported a fault, so the line stopped.",
        "Clear the feeder fault (Engineer tools → Feeder trip, click it off), then reset the drive "
        "(Engineer tools → Reset feeder drive)",
    ),
    "conveyor trip": (
        "The conveyor motor's overload tripped, so the line stopped.",
        "Clear the conveyor fault (Engineer tools → Conveyor trip, click it off), then reset the overload "
        "(Engineer tools → Reset conveyor overload)",
    ),
    "feeder jam": (
        "The feeder jammed: its motor kept turning but no material came out, and the plug switch in its "
        "discharge chute caught it.",
        "Clear the jam (Engineer tools → Feeder jam, click it off)",
    ),
    "hopper weight signal failed": (
        "The hopper's weight transmitter (WT-105) lost its signal, so the controller no longer knows how "
        "full the hopper is. Unknown means stop.",
        "Restore the transmitter (Engineer tools → Instrument faults → WT-105 → Restore)",
    ),
    "conveyor failed to prove running": (
        "The conveyor was told to start but never confirmed it was moving, so the start was abandoned.",
        "Clear the conveyor fault if one is injected (Engineer tools → Conveyor fail-to-start, click it off)",
    ),
    "feeder failed to prove running": (
        "The feeder was told to start but never confirmed it was running, so the start was abandoned.",
        "Clear the feeder fault if one is injected (Engineer tools → Feeder fail-to-start, click it off)",
    ),
    "gate failed to prove open": (
        "The source bin's gate was told to open but never reached its open position, so the start was abandoned.",
        "Free the stuck gate (Engineer tools → Bin A/B/C gate stuck, click it off), then reset it (Engineer "
        "tools → Reset bin A/B/C gate actuator)",
    ),
    "gate travel fault": (
        "A bin gate didn't reach its commanded position in time -- open when it should be closed pours from "
        "the wrong bin.",
        "Free the stuck gate (Engineer tools → Bin A/B/C gate stuck, click it off), then reset it (Engineer "
        "tools → Reset bin A/B/C gate actuator)",
    ),
    "outlet travel fault": (
        "The hopper's outlet gate didn't reach its commanded position in time: stuck shut, a batch can't "
        "discharge; stuck open, the hopper drains when it should hold.",
        "Free the outlet gate (Manual mode: open or close it), then reset",
    ),
    "batch feed stalled": (
        "The batch was feeding a bin, but nothing reached the belt scale (material bridging in the bin, "
        "say), so the batch stopped instead of waiting forever for its weight.",
        "Break up the bridge (Engineer tools → Bin bridged, click it off), empty the hopper in Manual, then reset",
    ),
    "discharge timeout": (
        "The batch discharge opened the hopper's outlet, but the hopper never emptied in time (a plugged "
        "outlet, or material bridging in the hopper).",
        "Empty the hopper (Manual mode: open the outlet), then reset",
    ),
    "conveyor jam": (
        "The conveyor belt jammed: it stopped moving while its motor strained against it (the motor current "
        "said so), so the line stopped before the overload relay had to.",
        "Clear the jam (Engineer tools → Conveyor jam, click it off); if the overload tripped, reset it "
        "(Engineer tools → Reset conveyor overload)",
    ),
    "conveyor lost confirmation": (
        "The conveyor motor was running but the belt stopped moving (a slipping or broken belt). Material "
        "would pile up at the feeder, so the line stopped.",
        "Fix the belt (Engineer tools → Belt slip, click it off)",
    ),
}

# Whether each fault's cause is gone, judged from what the field reports --
# so the checklist ticks off the fix as soon as it's done, not only after a
# reset. (The controller makes the real decision; this only reads the same
# signals it does.)
_CLEARED = {
    "hopper high-high": lambda v, inj: v["LSHH-105"] and v["WT-105"] < _HH_KG,
    "feeder trip": lambda v, inj: not v["M-103.FAULT"],
    "conveyor trip": lambda v, inj: not v["M-104.OL"],
    "feeder jam": lambda v, inj: not v["LSH-103"],
    "hopper weight signal failed": lambda v, inj: not v["WT-105.FLT"],
    "conveyor failed to prove running": lambda v, inj: not inj.get("conveyor_fail_to_start"),
    "feeder failed to prove running": lambda v, inj: not inj.get("feeder_fail_to_start"),
    "gate failed to prove open": lambda v, inj: not any(inj.get(k) for k in ("gate_stuck", "gate_b_stuck", "gate_c_stuck")),
    "gate travel fault": lambda v, inj: not any(inj.get(k) for k in ("gate_stuck", "gate_b_stuck", "gate_c_stuck")),
    "conveyor lost confirmation": lambda v, inj: not inj.get("belt_slip"),
    "conveyor jam": lambda v, inj: not inj.get("conveyor_jam") and not v["M-104.OL"],
    "outlet travel fault": lambda v, inj: v.get("ZSC-106", True),
    "discharge timeout": lambda v, inj: v["WT-105"] <= 5.0,
    "batch feed stalled": lambda v, inj: not inj.get("bin_bridged"),
}

# Why a start was refused (LineController.last_start_refusal), in plain
# words, with the fix. Matched by prefix: "unacknowledged alarm: ..." carries ids.
_REFUSALS: list[tuple[str, str, str]] = [
    ("bin low", "the source bin is nearly empty (below 10 %)",
     "Refill it (Engineer tools → Set bin A/B/C level, e.g. 50 %), or choose another source bin"),
    ("hopper at high-high", "the hopper is already too full (95 % or more)",
     "Lower the hopper (Engineer tools → Set hopper level, e.g. 50 %)"),
    ("hopper weight signal failed", "the hopper weight transmitter has failed, so its level is unknown",
     "Restore it (Engineer tools → Instrument faults → WT-105 → Restore)"),
    ("unacknowledged alarm", "an alarm hasn't been acknowledged yet (someone has to confirm they've seen it)",
     "Press Acknowledge"),
    ("gate not closed", "a gate isn't proven closed at its closed limit switch: it may be stuck, or still closing",
     "Wait a moment for it to close; if it's stuck, clear the gate fault at the equipment (Engineer tools), "
     "then reset the gate"),
    # Batch mode (master specification, item 7)
    ("recipe is empty", "the recipe has no bin in it", "Enter a recipe (kg from at least one bin) and press Apply recipe"),
    ("recipe is more than fits", "the recipe is more than the hopper takes under its high switch",
     "Enter a smaller recipe"),
    ("hopper not empty", "a batch starts only from an empty hopper",
     "Empty the hopper (Manual mode: open the outlet, then close it)"),
    # Manual mode (docs/CONTROL-LAB.md §6.1)
    ("conveyor not proven running", "the conveyor isn't proven running, and the feeder may only feed onto a moving belt",
     "Start the conveyor first and wait for it to show running"),
    ("hopper at the high switch", "the hopper is at its high level switch (80 %), where Manual stops the feeder",
     "Let the hopper draw down, or lower it (Engineer tools → Set hopper level, e.g. 50 %)"),
    ("device commands need Manual mode", "the device buttons only work in Manual mode; in Auto the sequence drives "
     "the devices", "Select Manual (with the line stopped) to drive each device yourself"),
    ("line Start is an Auto command", "Start runs the automatic sequence, and Manual mode bypasses it",
     "Start each device with its own button, or select Auto"),
    ("mode change to", "the mode only changes at rest: with the line stopped in Auto, or with every device off "
     "in Manual", "Stop the line (or every device) first, then select the mode again"),
]
_START_PERMISSIVES = ("bin low", "hopper at high-high", "hopper weight signal failed", "unacknowledged alarm",
                      "gate not closed")

_START_STEPS = {
    "conveyor": "Step 1 of 3: starting the conveyor, and waiting for its motion switch to prove the belt is moving.",
    "gate": "Step 2 of 3: the belt is moving, so the bin gate is opening.",
    "feeder": "Step 3 of 3: the gate is open, so the feeder is starting.",
}


def _unacked(alarms: list[dict]) -> list[dict]:
    return [a for a in alarms if not a["acknowledged"]]


def _alarm_notes(alarms: list[dict]) -> list[str]:
    """Things on the alarm board that need their own sentence."""
    ids = {a["id"] for a in alarms}
    notes = []
    if "LSHH-105.DISAGREE" in ids:
        notes.append(
            "The hopper's high-high level switch and its weight transmitter disagree, so one of them is wrong. "
            "The overfill trip listens to both (it trips if either says too full), which is why a stuck "
            "switch can't stop it from working."
        )
    if "LSH-105.DISAGREE" in ids:
        notes.append(
            "The hopper's high level switch disagrees with the weight transmitter. It's the switch the feeder "
            "stops at, so a wrong reading pauses the feed for no reason. A warning, not a trip."
        )
    return notes


def _verifying(s: dict, busy: dict) -> dict:
    live = s.get("verifying") is not None
    where = ("The picture shows it live, and the test beside it (below it, on a narrow screen) ticks off each stage as it passes." if live else
             "It runs in the background against that runtime; the picture below is not part of this run.")
    step = f" (runtime {busy['step']} of {busy['of']})" if busy.get("of", 1) > 1 else ""
    return {
        "tone": "info",
        "headline": f"Verifying: {busy['scenario']}{step}",
        "detail": f"The scenario runner is operating the line on the {busy['runtime']}, exactly as the automated "
                  "test suite does: it sets up the precondition, applies each stage's actions, and checks every "
                  f"expectation against its time limit. {where} Manual controls are locked until the result is in.",
        "steps": [],
    }


def _refusal(reasons: list[str]) -> tuple[list[str], list[dict]]:
    """Plain words and a fix for each refusal reason (matched by prefix)."""
    why, steps = [], []
    for reason in reasons:
        for prefix, plain, fix in _REFUSALS:
            if reason.startswith(prefix):
                why.append(plain)
                steps.append({"text": fix, "done": False})
    return why, steps


def _manual(s: dict, v: dict, alarms: list[dict], notes: list[str]) -> dict:
    """Manual mode: the operator drives each device; the checklist is the
    order that moves material, ticked off from what the field reports."""
    conveyor = v["M-104.RUNNING"] and v["ZSS-104"]
    gate = v["ZSO-102"]
    feeder = v["M-103.RUNNING"]
    base = ("Manual mode bypasses the start sequence, not the protection: the feeder only runs onto a moving "
            "belt and stops at the hopper's high switch, and every trip still works. Select Auto (with every "
            "device off) to go back to the automatic sequence.")
    refusal = s.get("last_start_refusal") or []
    if refusal:
        why, steps = _refusal(refusal)
        return {"tone": "warn", "headline": "Manual mode. The last request was refused.",
                "detail": "It refused because " + " and ".join(why) + ". " + base, "steps": steps}
    if v["M-104.RUN"] and conveyor and gate and feeder:
        headline = "Manual mode: material is flowing."
    elif not (v["M-104.RUN"] or v["XV-102.CMD_OPEN"] or v["M-103.RUN"]):
        headline = "Manual mode: every device is off. You drive each one."
    else:
        headline = "Manual mode: you're driving the devices."
    detail = base
    if v["M-104.RUN"] and not v["M-103.RUN"] and not v["LSH-105"]:
        detail = "The hopper is at its high switch, so the feeder is stopped. " + detail
    return {
        "tone": "warn" if _unacked(alarms) else "info",
        "headline": headline,
        "detail": " ".join([detail] + notes),
        "steps": [
            {"text": "Start the conveyor, and wait for it to show running", "done": bool(conveyor)},
            {"text": "Open the gate", "done": bool(gate)},
            {"text": "Start the feeder (only once the belt is moving)", "done": bool(feeder)},
        ],
    }


def _batch(s: dict, v: dict, notes: list[str]) -> dict:
    """Batch mode's four states: where the batch is, as a checklist."""
    b = s.get("batch") or {}
    order = ["loading", "processing", "discharging", "cleaning"]
    at = order.index(s["state"])
    loaded, target = b.get("loaded_kg", 0.0), b.get("target_kg", 0.0)
    detail = {
        "loading": f"Feeding bin {s.get('active_bin') or '?'} until the hopper holds its share of the recipe: "
                   f"{loaded:.0f} of {target:.0f} kg so far. Each bin's gate opens in turn, and feeding stops a "
                   "little early so the material still on the belt makes up the rest.",
        "processing": f"Loaded {loaded:.0f} kg against a recipe of {target:.0f} kg. Holding for "
                      f"{b.get('hold_s', 0):g} s (the process step) before the discharge.",
        "discharging": "The hopper's outlet gate is open and the batch is leaving the hopper; the gate closes once "
                       "the hopper is empty.",
        "cleaning": "The hopper is empty. The conveyor runs a little longer to clear the belt, then the outlet "
                    "closes and the line is ready for the next batch.",
    }[s["state"]]
    return {
        "tone": "info",
        "headline": f"Batch: {['Loading', 'Holding', 'Discharging', 'Cleaning out'][at]}.",
        "detail": " ".join([detail] + notes + ["Press Stop to abort the batch."]),
        "steps": [{"text": t, "done": i < at} for i, t in enumerate(
            ["Load each bin's share", "Hold", "Discharge the hopper", "Clean out the belt"])],
    }


def narrate(s: dict) -> dict:
    busy = (s.get("verification") or {}).get("busy")
    if busy:
        return _verifying(s, busy)
    running = s.get("running", True)
    state = s["state"]
    v = s["values"]
    alarms = s["alarms"]
    notes = _alarm_notes(alarms)

    if state == "external":
        out = {
            "tone": "info",
            "headline": "An external controller is running this line.",
            "detail": "ControlLab is only the plant here: a separate program (or a real PLC) reads the sensors and "
            "drives the motors over Modbus. The line's state and alarms live in that controller.",
            "steps": [],
        }
    elif state == "estopped":
        pressed = s["injected"].get("estop") == "tripped"
        out = {
            "tone": "trip",
            "headline": "Emergency stop. Everything is off.",
            "detail": "The E-stop cuts every motor and closes the gate at once, whatever the line was doing.",
            "steps": [
                {"text": "Release the E-stop (Engineer tools → E-stop, click it off)", "done": not pressed},
                {"text": "Press Acknowledge", "done": not _unacked(alarms)},
                {"text": "Press Reset", "done": False},
            ],
        }
    elif state == "faulted":
        what, fix = _FAULTS.get(s["fault_reason"] or "", (f"The line tripped ({s['fault_reason']}).", ""))
        inj = s["injected"]
        steps = [
            {"text": f"Repair {tag} (Engineer tools → Instrument faults → {tag} → Restore)", "done": False}
            for tag in sorted(inj.get("instruments", {}))
        ]
        if fix:
            cleared = _CLEARED.get(s["fault_reason"])
            steps.append({"text": fix, "done": bool(cleared and cleared(v, inj))})
        steps += [
            {"text": "Press Acknowledge (confirms you've seen the alarms)", "done": not _unacked(alarms)},
            {"text": "Press Reset (the controller only accepts it once the cause is gone)", "done": False},
        ]
        out = {
            "tone": "trip",
            "headline": "Tripped: the controller stopped the line.",
            "detail": " ".join([what, ("It stopped the feeder and closed the gate; the conveyor keeps running a "
                                       "little longer to clear the belt, then stops." if v["M-104.RUN"] else
                                       "It stopped the feeder, closed the gate and stopped the conveyor."),
                                "It won't restart until the cause is fixed and someone resets it."] + notes),
            "steps": steps,
        }
    elif state == "starting":
        out = {
            "tone": "info",
            "headline": "Starting up.",
            "detail": _START_STEPS.get(s.get("start_step") or "", "") + " Equipment starts from the end of the line "
            "backwards, so material never lands on something that isn't moving.",
            "steps": [],
        }
    elif state == "running":
        feeding = v["M-103.RUN"]
        detail = (
            "Material flows from the bin, through the gate and feeder, up the conveyor and into the hopper."
            if feeding else
            "The hopper has reached its high mark (80 %), so the feeder is paused; it starts again when the "
            "hopper drops below 60 %. The conveyor and gate stay as they are."
        )
        warn = [a for a in alarms if a["active"] and a["is_warning"]]
        if any(a["id"] == "LSL-101.LOW" for a in warn):
            detail += " The bin is running low: a warning, not a trip."
        out = {
            "tone": "warn" if warn else "ok",
            "headline": "Running." if feeding else "Running, feeder paused (hopper full).",
            "detail": " ".join([detail] + notes + ["Press Stop for a normal shutdown, or try a fault from "
                                                   "Engineer tools to see how the controller reacts."]),
            "steps": [],
        }
    elif state == "manual":
        out = _manual(s, v, alarms, notes)
    elif state in ("loading", "processing", "discharging", "cleaning"):
        out = _batch(s, v, notes)
    elif state == "stopping":
        out = {
            "tone": "info",
            "headline": "Stopping.",
            "detail": "The feeder and gate stopped first, so no new material is loaded. The conveyor keeps "
            "running a little longer to clear the belt, then stops too.",
            "steps": [],
        }
    else:  # idle
        refusal = s.get("last_start_refusal") or []
        if refusal:
            why, steps = _refusal(refusal)
            start = all(r.startswith(_START_PERMISSIVES) for r in refusal)
            if start:
                steps.append({"text": "Press Start again", "done": False})
            out = {
                "tone": "warn",
                "headline": "Stopped. The last Start was refused." if start else "Stopped. That request was refused.",
                "detail": ("The controller checks that it's safe to start before it moves anything. " if start else "")
                + "It refused because " + " and ".join(why) + ".",
                "steps": steps,
            }
        elif s.get("line_mode") == "batch":
            b = s.get("batch") or {}
            out = {
                "tone": "info",
                "headline": "Batch mode: ready for a batch.",
                "detail": "Enter a recipe (kg from each bin, and a hold time) and press Start: the line loads each bin's "
                f"share into the hopper, holds, discharges it, and cleans out. Batches completed: {b.get('completed', 0)}.",
                "steps": [],
            }
        else:
            unacked = _unacked(alarms)
            out = {
                "tone": "info" if not unacked else "warn",
                "headline": "Stopped and ready.",
                "detail": "Press Start: the conveyor starts first, then the bin gate opens, then the feeder runs, "
                "moving material from the bin up into the hopper. Or run a scenario (in the Scenarios panel) to have the controller verified "
                "automatically, stage by stage."
                + (" There's an alarm to acknowledge first (press Acknowledge)." if unacked else ""),
                "steps": [],
            }

    if not running:
        waiting = s.get("pending") or []
        out = {
            **out,
            "tone": "info",
            "headline": "Paused. Time is stopped. " + out["headline"],
            "detail": ("Press ▶ Run (under the picture) to continue."
                       + (f" Waiting to apply: {', '.join(waiting)}." if waiting else "")) + " " + out["detail"],
        }
    if s.get("violation"):
        out = {**out, "tone": "trip",
               "detail": out["detail"] + " Note: a physics check failed in this session (see the red banner); "
                                         "start a New session for a clean run."}
    return out
