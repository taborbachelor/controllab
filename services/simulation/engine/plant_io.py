"""Wires Plant (Simulation) to the shared I/O image.

Plant itself stays a plain simulation object with no knowledge of the I/O
image — these functions are the *only* place that bridges the two, so a
future change in how Simulation and Control talk (a real protocol adapter,
for instance) never has to touch Plant's own code.

The tag list matches docs/CONTROL-LAB.md §5.3 exactly — `test_plant_io.py`
asserts that directly, so the two can't silently drift apart.

Scan-cycle order (docs/CONTROL-LAB.md §3.3): commands are applied *before*
`plant.step()`, so they take effect that tick; inputs are published
*after*, so Control's next scan sees this tick's results, not last tick's.
`scan()` does both, in the right order, around one `plant.step()` call.
"""
from __future__ import annotations

from services.simulation.engine.io_image import IOImage, TagType
from services.simulation.equipment.plant import Plant

# (name, type, units, description) — one row per docs/CONTROL-LAB.md §5.3.
_TAGS: list[tuple[str, TagType, str, str]] = [
    ("LT-101", TagType.AI, "%", "Bin level"),
    ("LSL-101", TagType.DI, "", "Bin low level switch"),
    ("XV-102.CMD_OPEN", TagType.DO, "", "Gate open command (de-energized = close)"),
    ("ZSO-102", TagType.DI, "", "Gate open limit switch"),
    ("ZSC-102", TagType.DI, "", "Gate closed limit switch"),
    ("M-103.RUN", TagType.DO, "", "Feeder motor run command"),
    ("M-103.RUNNING", TagType.DI, "", "Feeder motor running feedback (VFD)"),
    ("M-103.FAULT", TagType.DI, "", "Feeder VFD fault"),
    ("SC-103", TagType.AO, "%", "Feeder speed reference"),
    ("LSH-103", TagType.DI, "", "Feeder discharge chute plug switch (jam)"),
    ("M-104.RUN", TagType.DO, "", "Conveyor motor run command"),
    ("M-104.RUNNING", TagType.DI, "", "Conveyor motor running feedback (contactor aux)"),
    ("M-104.OL", TagType.DI, "", "Conveyor motor overload tripped"),
    ("ZSS-104", TagType.DI, "", "Conveyor motion (zero-speed) switch"),
    ("IT-104", TagType.AI, "A", "Conveyor motor current"),
    ("FT-104", TagType.AI, "kg/s", "Belt scale flow rate at the conveyor head"),
    ("WT-105", TagType.AI, "kg", "Hopper weight"),
    ("WT-105.FLT", TagType.DI, "", "Hopper weight input channel fault (wire break / transmitter failed)"),
    ("LSH-105", TagType.DI, "", "Hopper high level switch (80%; 1 = below, fail-safe polarity)"),
    ("LSHH-105", TagType.DI, "", "Hopper high-high level switch (95%; 1 = below, fail-safe polarity)"),
    ("ES-001", TagType.DI, "", "E-stop healthy (1 = healthy; fail-safe polarity)"),
    # Bins B and C (master specification, item 6), each with its own gate.
    ("LT-111", TagType.AI, "%", "Bin B level, %"),
    ("LSL-111", TagType.DI, "", "Bin B low level switch"),
    ("XV-112.CMD_OPEN", TagType.DO, "", "Bin B gate open command (de-energized = close)"),
    ("ZSO-112", TagType.DI, "", "Bin B gate open limit switch"),
    ("ZSC-112", TagType.DI, "", "Bin B gate closed limit switch"),
    ("LT-121", TagType.AI, "%", "Bin C level, %"),
    ("LSL-121", TagType.DI, "", "Bin C low level switch"),
    ("XV-122.CMD_OPEN", TagType.DO, "", "Bin C gate open command (de-energized = close)"),
    ("ZSO-122", TagType.DI, "", "Bin C gate open limit switch"),
    ("ZSC-122", TagType.DI, "", "Bin C gate closed limit switch"),
    # The hopper's outlet gate (master specification, item 7).
    ("XV-106.CMD_OPEN", TagType.DO, "", "Hopper outlet gate open command (de-energized = close)"),
    ("ZSO-106", TagType.DI, "", "Hopper outlet gate open limit switch"),
    ("ZSC-106", TagType.DI, "", "Hopper outlet gate closed limit switch"),
    ("DS-107.READY", TagType.DI, "", "Downstream consumer ready to take material (1 = ready; fail-safe polarity)"),
]


def build_line_io_image() -> IOImage:
    """A fresh IOImage with exactly the tags in docs/CONTROL-LAB.md §5.3."""
    io = IOImage()
    for name, type_, units, description in _TAGS:
        io.define(name, type_, units=units, description=description)
    return io


def publish_plant_inputs(plant: Plant, io: IOImage) -> None:
    """Simulation -> I/O image: publish every DI/AI tag from the plant's
    current state, as its instrument reports it (plant.instruments: a stuck
    or failed sensor reports something other than the truth). Call *after*
    plant.step()."""
    def publish(tag: str, true_value) -> None:
        io.write_input(tag, plant.instruments.report(tag, true_value))

    publish("LT-101", plant.bin.level_pct)
    publish("LSL-101", plant.bin.low)

    publish("ZSO-102", plant.gate.is_open)
    publish("ZSC-102", plant.gate.is_closed)

    for level, low, opened, closed, which in (("LT-111", "LSL-111", "ZSO-112", "ZSC-112", "B"),
                                               ("LT-121", "LSL-121", "ZSO-122", "ZSC-122", "C")):
        bin_, gate = plant.bins[which]
        publish(level, bin_.level_pct)
        publish(low, bin_.low)
        publish(opened, gate.is_open)
        publish(closed, gate.is_closed)

    publish("M-103.RUNNING", plant.feeder.motor.running)
    publish("M-103.FAULT", plant.feeder.motor.fault)
    publish("LSH-103", plant.feeder.plugged)

    publish("M-104.RUNNING", plant.conveyor.motor.running)
    publish("M-104.OL", plant.conveyor.motor.fault)
    publish("ZSS-104", plant.conveyor.motion_confirmed)
    publish("IT-104", plant.conveyor.current_a)
    publish("FT-104", plant.belt_flow_kg_s)

    publish("WT-105", plant.hopper.level_kg)
    # The input card's own diagnostic for WT-105, not an instrument reading.
    io.write_input("WT-105.FLT", plant.instruments.channel_fault("WT-105"))
    # Fail-safe polarity, like ES-001: the contact is closed (1) while the
    # level is BELOW the switch point and opens at it, so a broken wire, a
    # dead switch or a lost input reads 0 -- "high" -- and stops the feed /
    # trips the line, instead of silently reading "not high".
    publish("LSH-105", not plant.hopper.high)
    publish("LSHH-105", not plant.hopper.high_high)

    publish("ES-001", plant.estop.healthy)
    publish("ZSO-106", plant.outlet.is_open)
    publish("ZSC-106", plant.outlet.is_closed)
    # Fail-safe like ES-001: a lost signal reads "not ready", so discharge stops.
    publish("DS-107.READY", plant.downstream.ready)


def apply_plant_commands(io: IOImage, plant: Plant) -> None:
    """I/O image -> Simulation: apply every DO/AO tag to the plant's
    devices. Call *before* plant.step(), so this tick's commands take
    effect on it. Goes through each device's own command()/current-value
    setters rather than setting internal state directly, so validation
    (e.g. Feeder's speed clamp) still applies."""
    plant.gate.command(io.read("XV-102.CMD_OPEN"))
    plant.gate_b.command(io.read("XV-112.CMD_OPEN"))
    plant.gate_c.command(io.read("XV-122.CMD_OPEN"))
    plant.outlet.command(io.read("XV-106.CMD_OPEN"))
    plant.feeder.command(io.read("M-103.RUN"), io.read("SC-103"))
    plant.conveyor.command(io.read("M-104.RUN"))


def scan(plant: Plant, io: IOImage, dt: float) -> None:
    """One full scan cycle: apply this tick's commands, advance the
    plant, then publish the results for the next scan to read.

    Before the first call, publish once directly
    (`publish_plant_inputs(plant, io)`) so Control's first scan sees the
    plant's real starting state rather than the I/O image's tag defaults.
    """
    apply_plant_commands(io, plant)
    plant.step(dt)
    publish_plant_inputs(plant, io)
