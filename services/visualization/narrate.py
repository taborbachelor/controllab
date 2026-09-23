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

# Plain names for the things on the picture, used throughout.
BIN, GATE, FEEDER, CONVEYOR, HOPPER = "the bin", "the bin gate", "the feeder", "the conveyor", "the hopper"

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
        "The bin gate was told to open but never reached its open position, so the start was abandoned.",
        "Free the gate (Engineer tools → Gate stuck, click it off), then reset it (Engineer tools → Reset "
        "gate actuator)",
    ),
    "gate travel fault": (
        "The bin gate didn't reach its commanded position in time.",
        "Free the gate (Engineer tools → Gate stuck, click it off), then reset it (Engineer tools → Reset "
        "gate actuator)",
    ),
    "conveyor lost confirmation": (
        "The conveyor motor was running but the belt stopped moving (a slipping or broken belt). Material "
        "would pile up at the feeder, so the line stopped.",
        "Fix the belt (Engineer tools → Belt slip, click it off)",
    ),
}

# Why a start was refused (LineController.last_start_refusal), in plain
# words, with the fix. Matched by prefix: "unacknowledged alarm: ..." carries ids.
_REFUSALS: list[tuple[str, str, str]] = [
    ("bin low", "the bin is nearly empty (below 10 %)", "Refill the bin (Engineer tools → Set bin level, e.g. 50 %)"),
    ("hopper at high-high", "the hopper is already too full (95 % or more)",
     "Lower the hopper (Engineer tools → Set hopper level, e.g. 50 %)"),
    ("hopper weight signal failed", "the hopper weight transmitter has failed, so its level is unknown",
     "Restore it (Engineer tools → Instrument faults → WT-105 → Restore)"),
    ("unacknowledged alarm", "an alarm hasn't been acknowledged yet (someone has to confirm they've seen it)",
     "Press Acknowledge"),
]

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


def narrate(s: dict) -> dict:
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
        steps = []
        if fix:
            steps.append({"text": fix, "done": False})
        steps += [
            {"text": "Press Acknowledge (confirms you've seen the alarms)", "done": not _unacked(alarms)},
            {"text": "Press Reset (the controller only accepts it once the cause is gone)", "done": False},
        ]
        out = {
            "tone": "trip",
            "headline": "Tripped: the controller stopped the line.",
            "detail": " ".join([what, "It stopped the feeder, closed the gate and stopped the conveyor. "
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
            why, steps = [], []
            for reason in refusal:
                for prefix, plain, fix in _REFUSALS:
                    if reason.startswith(prefix):
                        why.append(plain)
                        steps.append({"text": fix, "done": False})
            steps.append({"text": "Press Start again", "done": False})
            out = {
                "tone": "warn",
                "headline": "Stopped. The last Start was refused.",
                "detail": "The controller checks that it's safe to start before it moves anything. It refused because "
                + " and ".join(why) + ".",
                "steps": steps,
            }
        else:
            unacked = _unacked(alarms)
            out = {
                "tone": "info" if not unacked else "warn",
                "headline": "Stopped and ready.",
                "detail": "Press Start: the conveyor starts first, then the bin gate opens, then the feeder runs, "
                "moving material from the bin up into the hopper. Or pick a guided walkthrough."
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
