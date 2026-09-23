"""Unit tests for the Plant <-> IOImage wiring. The full-line round trip
(driving material through the line purely via the I/O image) lives in
tests/integration/test_plant_io.py.
"""
from services.simulation.engine.io_image import TagType
from services.simulation.engine.plant_io import (
    apply_plant_commands,
    build_line_io_image,
    publish_plant_inputs,
)
from services.simulation.equipment.plant import Plant

# Matches docs/CONTROL-LAB.md §5.3 exactly. If this test fails, either the
# doc or services/simulation/engine/plant_io.py drifted — fix whichever is
# wrong, don't just update this list to match.
EXPECTED_TAGS = {
    "LT-101": TagType.AI,
    "LSL-101": TagType.DI,
    "XV-102.CMD_OPEN": TagType.DO,
    "ZSO-102": TagType.DI,
    "ZSC-102": TagType.DI,
    "M-103.RUN": TagType.DO,
    "M-103.RUNNING": TagType.DI,
    "M-103.FAULT": TagType.DI,
    "SC-103": TagType.AO,
    "LSH-103": TagType.DI,
    "M-104.RUN": TagType.DO,
    "M-104.RUNNING": TagType.DI,
    "M-104.OL": TagType.DI,
    "ZSS-104": TagType.DI,
    "WT-105": TagType.AI,
    "LSH-105": TagType.DI,
    "LSHH-105": TagType.DI,
    "ES-001": TagType.DI,
}


def test_line_io_image_matches_the_spec_exactly():
    io = build_line_io_image()
    assert set(io.names()) == set(EXPECTED_TAGS.keys())
    for name, expected_type in EXPECTED_TAGS.items():
        assert io.tag(name).type == expected_type, f"{name} should be {expected_type}"


def test_publish_reflects_a_freshly_constructed_plants_starting_state():
    plant = Plant()  # default config: bin starts full, everything else at rest
    io = build_line_io_image()
    publish_plant_inputs(plant, io)

    assert io.read("LT-101") == plant.bin.level_pct
    assert io.read("LSL-101") is False  # bin starts full, well above low
    assert io.read("ZSO-102") is False  # gate starts closed
    assert io.read("ZSC-102") is True
    assert io.read("M-103.RUNNING") is False
    assert io.read("M-104.RUNNING") is False
    assert io.read("WT-105") == 0.0  # hopper starts empty
    assert io.read("ES-001") is True  # e-stop starts healthy


def test_apply_commands_drives_the_conveyor_motor():
    plant = Plant()
    io = build_line_io_image()
    io.write_output("M-104.RUN", True)
    io.write_output("M-103.RUN", False)
    io.write_output("SC-103", 0.0)
    io.write_output("XV-102.CMD_OPEN", False)

    apply_plant_commands(io, plant)

    assert plant.conveyor.motor.run_command is True
    assert plant.feeder.motor.run_command is False


def test_apply_commands_clamps_feeder_speed_through_feeders_own_setter():
    """apply_plant_commands must go through Feeder.command(), not set
    speed_pct directly — otherwise the 0-100 clamp is bypassed."""
    plant = Plant()
    io = build_line_io_image()
    io.write_output("M-103.RUN", True)
    io.write_output("SC-103", 150.0)  # out of range on purpose
    io.write_output("M-104.RUN", False)
    io.write_output("XV-102.CMD_OPEN", False)

    apply_plant_commands(io, plant)

    assert plant.feeder.speed_pct == 100.0


def test_publish_reflects_gate_open_state():
    plant = Plant()
    plant.gate.command(True)
    for _ in range(30):  # well past default 2.0s travel time at dt=0.1
        plant.gate.step(0.1)
    assert plant.gate.is_open

    io = build_line_io_image()
    publish_plant_inputs(plant, io)
    assert io.read("ZSO-102") is True
    assert io.read("ZSC-102") is False
