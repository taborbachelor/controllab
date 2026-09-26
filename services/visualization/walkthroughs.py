"""Guided walkthroughs for the live dashboard: short stories, step by step,
for someone who has never seen the line before.

Each step says what to do, highlights the control that does it, can do it
for the viewer ("Do it for me"), and completes when the line actually
reaches the step's condition -- judged on the live session, never on a
click. So a step completes the same way whether the viewer pressed the
real button or let the walkthrough press it, and a walkthrough can't claim
something happened that didn't. After each step, `then` explains what just
happened and why.

Actions go through LiveSession.command() / stimulus(): the same validated
path every button uses. Every walkthrough is run to completion in the test
suite (tests/unit/test_walkthroughs.py).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# A condition sees the session snapshot and the events recorded since the
# step began (dicts: {"t", "type", ...}).
Condition = Callable[[dict, list[dict]], bool]


@dataclass(frozen=True)
class Step:
    say: str
    until: Condition
    do: tuple[tuple[str, object], ...] = ()  # (command or stimulus key, value)
    target: str | None = None  # CSS selector of the control to highlight
    then: str = ""


@dataclass(frozen=True)
class Walkthrough:
    id: str
    title: str
    summary: str
    steps: tuple[Step, ...]


# ---- condition helpers -----------------------------------------------------

def state_is(*states: str) -> Condition:
    return lambda s, ev: s["state"] in states


def pressed(command: str, *, still: str | None = None) -> Condition:
    """The command was applied since the step began (and, optionally, the
    line is still in `still` -- i.e. the controller refused it)."""
    return lambda s, ev: any(e["type"] == "command_issued" and e["command"] == command for e in ev) and (
        still is None or s["state"] == still
    )


def all_acknowledged(s: dict, ev: list[dict]) -> bool:
    return all(a["acknowledged"] for a in s["alarms"])


def ready_to_start(s: dict, ev: list[dict]) -> bool:
    """IDLE with every gate back at its closed limit switch: after a trip
    the gates take their travel time to close, and Start waits for them
    (the gates-closed permissive)."""
    return s["state"] == "idle" and all(s["values"].get(t, True) for t in ("ZSC-102", "ZSC-112", "ZSC-122", "ZSC-106"))


# ---- reusable steps ----------------------------------------------------------

START = Step(
    say="Press Start.",
    do=(("start", True),),
    target='[data-cmd="start"]',
    until=state_is("running"),
    then="The line started: conveyor first, then the gate, then the feeder, and material is flowing.",
)
ACK = Step(
    say="Press Acknowledge, to confirm you've seen the alarm.",
    do=(("acknowledge", True),),
    target='[data-cmd="acknowledge"]',
    until=all_acknowledged,
    then="Acknowledged. That only says someone has seen it; it doesn't restart anything.",
)
RESET = Step(
    say="Press Reset.",
    do=(("reset", True),),
    target='[data-cmd="reset"]',
    until=ready_to_start,
    then="The cause is gone and the alarm is acknowledged, so the controller accepted the reset. The line is "
    "stopped, its gates are closed, and it's ready again.",
)


WALKTHROUGHS: tuple[Walkthrough, ...] = (
    Walkthrough(
        id="normal",
        title="A normal start and stop",
        summary="Watch the start-up sequence, material moving, and a clean shutdown.",
        steps=(
            Step(
                say="Press Start.",
                do=(("start", True),),
                target='[data-cmd="start"]',
                until=state_is("starting", "running"),
                then="The controller first checked it was safe to start (bin not empty, hopper not full, no alarms "
                "waiting), then began from the END of the line: the conveyor starts first.",
            ),
            Step(
                say="Watch the picture: the conveyor proves it's moving, then the gate opens, then the feeder "
                "starts. Nothing to click.",
                until=state_is("running"),
                then="Everything is running. Starting from the far end means material never lands on something "
                "that isn't moving yet.",
            ),
            Step(
                say="Watch material arrive: brown dashes move along the feeder and up the conveyor, and the "
                "hopper's weight starts climbing.",
                until=lambda s, ev: s["values"]["WT-105"] >= 20.0,
                then="The hopper is filling. Left running, the feeder would pause when the hopper reaches 80 % "
                "and start again below 60 %.",
            ),
            Step(
                say="Press Stop.",
                do=(("stop", True),),
                target='[data-cmd="stop"]',
                until=state_is("stopping", "idle"),
                then="Stopping works the other way round: the feeder and gate stopped first, so nothing new is "
                "loaded onto the belt.",
            ),
            Step(
                say="Watch: the conveyor keeps running for a moment to clear the belt, then stops.",
                until=state_is("idle"),
                then="Stopped, with an empty belt. That's the normal cycle.",
            ),
        ),
    ),
    Walkthrough(
        id="refused",
        title="Why won't it start?",
        summary="The controller refuses to start when it isn't safe, and says why.",
        steps=(
            Step(
                say="Nearly empty the bin: set the bin level to 5 % (Engineer tools → Set bin level).",
                do=(("bin_level_pct", 5),),
                target='[data-level="bin_level_pct"]',
                until=lambda s, ev: s["values"]["LSL-101"],
                then="The bin's low-level switch lit (the small circle at the bin's left).",
            ),
            Step(
                say="Press Start.",
                do=(("start", True),),
                target='[data-cmd="start"]',
                until=lambda s, ev: "bin low" in s["last_start_refusal"],
                then="Refused. Running the feeder on an empty bin would do nothing useful, so the controller "
                "checks first. The What's happening card at the top says why.",
            ),
            Step(
                say="Refill the bin: set its level to 50 %.",
                do=(("bin_level_pct", 50),),
                target='[data-level="bin_level_pct"]',
                until=lambda s, ev: not s["values"]["LSL-101"],
                then="The low-level switch went out.",
            ),
            Step(
                say="Press Start again.",
                do=(("start", True),),
                target='[data-cmd="start"]',
                until=state_is("running"),
                then="It starts now, because the reason it refused is gone. (The low-bin warning stays listed "
                "until acknowledged, but a warning never blocks a start.)",
            ),
        ),
    ),
    Walkthrough(
        id="estop",
        title="Emergency stop",
        summary="Hit the E-stop mid-run, then bring the line back safely.",
        steps=(
            START,
            Step(
                say="Hit the emergency stop (Engineer tools → E-stop).",
                do=(("estop", "tripped"),),
                target='[data-fault="estop"]',
                until=state_is("estopped"),
                then="Everything dropped at the same instant: every motor off, the gate closed. An emergency "
                "stop doesn't sequence anything.",
            ),
            Step(
                say="Try pressing Reset while the E-stop is still pressed.",
                do=(("reset", True),),
                target='[data-cmd="reset"]',
                until=pressed("reset", still="estopped"),
                then="Refused: the controller won't reset while the E-stop is still pressed.",
            ),
            Step(
                say="Release the E-stop (Engineer tools → E-stop, click it again).",
                do=(("estop", "healthy"),),
                target='[data-fault="estop"]',
                until=lambda s, ev: s["values"]["ES-001"],
                then="Released. The line still doesn't restart on its own: someone has to decide it's safe.",
            ),
            ACK,
            RESET,
        ),
    ),
    Walkthrough(
        id="feeder_trip",
        title="A motor fault and its recovery",
        summary="The feeder's drive faults mid-run; recover it the way an operator would.",
        steps=(
            START,
            Step(
                say="Make the feeder's motor drive fault (Engineer tools → Feeder trip).",
                do=(("feeder_trip", True),),
                target='[data-fault="feeder_trip"]',
                until=state_is("faulted"),
                then="The drive reported a fault and the controller tripped the line: feeder, gate and conveyor "
                "all off. The alarm is marked FIRST OUT, so it's clear what started it.",
            ),
            Step(
                say="Try Reset now.",
                do=(("reset", True),),
                target='[data-cmd="reset"]',
                until=pressed("reset", still="faulted"),
                then="Refused. The drive is still reporting a fault, and the controller won't restart onto a "
                "known problem.",
            ),
            Step(
                say="Fix it at the equipment: clear the fault (Engineer tools → Feeder trip, click it off), then "
                "reset the drive (Field resets → Reset feeder drive).",
                do=(("feeder_trip", False), ("feeder_drive_reset", True)),
                target='[data-fault="feeder_trip"]',
                until=lambda s, ev: not s["values"]["M-103.FAULT"],
                then="The drive is healthy again. The line is still stopped: nothing restarts by itself.",
            ),
            ACK,
            RESET,
            Step(
                say="Press Start to prove it's recovered.",
                do=(("start", True),),
                target='[data-cmd="start"]',
                until=state_is("running"),
                then="Running again. Fault, refused reset, repair, acknowledge, reset, restart: that's the whole "
                "recovery procedure, and it's also one of ControlLab's automated test scenarios.",
            ),
        ),
    ),
    Walkthrough(
        id="overfill",
        title="Overfill protection with a broken sensor",
        summary="A level switch fails silently; the line still protects itself and names the culprit.",
        steps=(
            START,
            Step(
                say="Break the hopper's high-high level switch so it's stuck saying 'not full' (Engineer tools → "
                "Instrument faults → LSHH-105 → Stuck).",
                do=(("sensor_stuck", "LSHH-105"),),
                target='[data-inst="LSHH-105"][data-kind="stuck"]',
                until=lambda s, ev: s["injected"]["instruments"].get("LSHH-105") == "stuck",
                then="The switch is frozen, and nothing on screen shows it's broken. That's exactly how a real "
                "seized switch behaves.",
            ),
            Step(
                say="Now overfill the hopper: set it to 98 % (Engineer tools → Set hopper level).",
                do=(("hopper_level_pct", 98),),
                target='[data-level="hopper_level_pct"]',
                until=state_is("faulted"),
                then="It tripped anyway. The overfill trip listens to two independent measurements, the switch "
                "and the hopper's weight, and trips if either says too full. The weight caught it.",
            ),
            Step(
                say="Watch the alarms: a second one appears within a second.",
                until=lambda s, ev: any(a["id"] == "LSHH-105.DISAGREE" for a in s["alarms"]),
                then="The controller noticed the switch and the weight disagree, and named the switch. On a "
                "real line, that's the prompt to go and test it.",
            ),
            Step(
                say="Repair: restore the switch (Instrument faults → LSHH-105 → Restore) and bring the hopper "
                "down to 50 %.",
                do=(("sensor_restored", "LSHH-105"), ("hopper_level_pct", 50)),
                target='[data-inst="LSHH-105"][data-kind="restored"]',
                until=lambda s, ev: not s["injected"]["instruments"] and s["values"]["WT-105"] < 1_100.0,
                then="The switch works again and both measurements agree.",
            ),
            ACK,
            RESET,
        ),
    ),
    Walkthrough(
        id="manual",
        title="Drive the line by hand (Manual mode)",
        summary="Start each device yourself, and see which protections still hold when the sequence is bypassed.",
        steps=(
            Step(
                say="Select Manual mode (Operator panel, next to Mode).",
                do=(("select_manual", True),),
                target='[data-cmd="select_manual"]',
                until=state_is("manual"),
                then="The line is in Manual. Nothing moved: every device waits for its own button. The mode can "
                "only change at rest, so this works because the line was stopped.",
            ),
            Step(
                say="Try the wrong order first: press the feeder's Start while the conveyor is stopped.",
                do=(("start_feeder", True),),
                target='[data-cmd="start_feeder"]',
                until=lambda s, ev: pressed("start_feeder")(s, ev)
                and "conveyor not proven running" in s["last_start_refusal"],
                then="Refused, and the card says why: the feeder may only feed onto a moving belt. Manual mode "
                "bypasses the start sequence, not the protection.",
            ),
            Step(
                say="Start the conveyor.",
                do=(("start_conveyor", True),),
                target='[data-cmd="start_conveyor"]',
                until=lambda s, ev: s["values"]["M-104.RUNNING"] and s["values"]["ZSS-104"],
                then="The motor runs and the motion switch proves the belt is moving. From now on, losing that "
                "proof while the motor runs would trip the line, exactly as in Auto.",
            ),
            Step(
                say="Open the gate.",
                do=(("open_gate", True),),
                target='[data-cmd="open_gate"]',
                until=lambda s, ev: s["values"]["ZSO-102"],
                then="The gate is open. On its own it moves nothing: the feeder has to run for material to "
                "leave the bin. (Stroking a gate to check its limit switches is a classic Manual-mode job.)",
            ),
            Step(
                say="Now start the feeder.",
                do=(("start_feeder", True),),
                target='[data-cmd="start_feeder"]',
                until=lambda s, ev: s["values"]["M-103.RUNNING"],
                then="Accepted this time: the belt is proven running. Material flows from the bin up into the "
                "hopper.",
            ),
            Step(
                say="Stop the conveyor while the feeder is still running.",
                do=(("stop_conveyor", True),),
                target='[data-cmd="stop_conveyor"]',
                until=lambda s, ev: pressed("stop_conveyor")(s, ev) and not s["values"]["M-103.RUN"]
                and s["state"] == "manual",
                then="The feeder stopped in the same scan, so it never fed a stopped belt, and nothing tripped: "
                "stopping the conveyor was your command. A belt that stops on its own would have tripped the line.",
            ),
            Step(
                say="Close the gate.",
                do=(("close_gate", True),),
                target='[data-cmd="close_gate"]',
                until=lambda s, ev: s["values"]["ZSC-102"],
                then="Every device is off, so the line is at rest in Manual.",
            ),
            Step(
                say="Select Auto to hand the line back to the automatic sequence.",
                do=(("select_auto", True),),
                target='[data-cmd="select_auto"]',
                until=lambda s, ev: s["state"] == "idle" and s["line_mode"] == "auto",
                then="Back in Auto, stopped and ready: Start now runs the whole sequence again.",
            ),
        ),
    ),
)

BY_ID = {w.id: w for w in WALKTHROUGHS}


def catalog() -> list[dict]:
    return [{"id": w.id, "title": w.title, "summary": w.summary, "steps": len(w.steps)} for w in WALKTHROUGHS]
