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
    ("M-104.RUN", TagType.DO, "", "Conveyor motor run command"),
    ("M-104.RUNNING", TagType.DI, "", "Conveyor motor running feedback (contactor aux)"),
    ("M-104.OL", TagType.DI, "", "Conveyor motor overload tripped"),
    ("ZSS-104", TagType.DI, "", "Conveyor motion (zero-speed) switch"),
    ("WT-105", TagType.AI, "kg", "Hopper weight"),
    ("LSH-105", TagType.DI, "", "Hopper high level switch (80%)"),
    ("LSHH-105", TagType.DI, "", "Hopper high-high level switch (95%)"),
    ("ES-001", TagType.DI, "", "E-stop healthy (1 = healthy; fail-safe polarity)"),
]


def build_line_io_image() -> IOImage:
    """A fresh IOImage with exactly the tags in docs/CONTROL-LAB.md §5.3."""
    io = IOImage()
    for name, type_, units, description in _TAGS:
        io.define(name, type_, units=units, description=description)
    return io


def publish_plant_inputs(plant: Plant, io: IOImage) -> None:
    """Simulation -> I/O image: publish every DI/AI tag from the plant's
    current state. Call *after* plant.step()."""
    io.write_input("LT-101", plant.bin.level_pct)
    io.write_input("LSL-101", plant.bin.low)

    io.write_input("ZSO-102", plant.gate.is_open)
    io.write_input("ZSC-102", plant.gate.is_closed)

    io.write_input("M-103.RUNNING", plant.feeder.motor.running)
    io.write_input("M-103.FAULT", plant.feeder.motor.fault)

    io.write_input("M-104.RUNNING", plant.conveyor.motor.running)
    io.write_input("M-104.OL", plant.conveyor.motor.fault)
    io.write_input("ZSS-104", plant.conveyor.motion_confirmed)

    io.write_input("WT-105", plant.hopper.level_kg)
    io.write_input("LSH-105", plant.hopper.high)
    io.write_input("LSHH-105", plant.hopper.high_high)

    io.write_input("ES-001", plant.estop.healthy)


def apply_plant_commands(io: IOImage, plant: Plant) -> None:
    """I/O image -> Simulation: apply every DO/AO tag to the plant's
    devices. Call *before* plant.step(), so this tick's commands take
    effect on it. Goes through each device's own command()/current-value
    setters rather than setting internal state directly, so validation
    (e.g. Feeder's speed clamp) still applies."""
    plant.gate.command(io.read("XV-102.CMD_OPEN"))
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
