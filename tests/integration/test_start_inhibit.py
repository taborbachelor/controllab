"""StartInhibit: the machine-readable outcome of the most recent start
request (services/control/line_state.py). Set only when a start is
evaluated -- which is what lets a scenario prove START was issued."""
from services.control.line_state import StartInhibit, inhibit_names
from services.protocols.controller_status import decode, encode
from services.testing.rig import build_rig, run


def test_none_until_a_start_is_requested():
    rig = build_rig(plant_overrides={"bin_level_kg": 500.0})  # a permissive fails...
    run(rig, 1.0)
    assert rig.line.start_inhibit == StartInhibit.NONE  # ...but nobody pressed start


def test_each_permissive_reports_its_own_reason():
    rig = build_rig(plant_overrides={"bin_level_kg": 500.0})
    run(rig, 0.2)
    rig.line.start()
    run(rig, 0.2)
    assert (rig.line.state.name, inhibit_names(rig.line.start_inhibit)) == ("IDLE", ["BIN_LOW"])


def test_an_unacknowledged_alarm_alone_is_reported_once_its_condition_clears():
    """The isolated case the single-stage scenario can't express."""
    rig = build_rig()
    rig.plant.hopper.level_kg = 1_950.0
    run(rig, 0.3)
    rig.plant.hopper.level_kg = 500.0  # condition clears, alarm stays unacknowledged
    run(rig, 0.3)
    rig.line.start()
    run(rig, 0.2)
    assert inhibit_names(rig.line.start_inhibit) == ["UNACKNOWLEDGED_ALARM"]


def test_estopped_and_faulted_refusals_are_reported_without_changing_behavior():
    rig = build_rig()
    rig.plant.estop.trip()
    run(rig, 0.3)
    rig.line.start()
    run(rig, 0.3)
    assert (rig.line.state.name, rig.line.start_inhibit) == ("ESTOPPED", StartInhibit.ESTOP_ACTIVE)

    rig = build_rig()
    rig.line.start()
    run(rig, 3.0)
    rig.plant.feeder.motor.trip_now = True
    run(rig, 0.3)
    rig.line.start()
    run(rig, 0.3)
    assert (rig.line.state.name, rig.line.start_inhibit) == ("FAULTED", StartInhibit.LINE_FAULTED)


def test_an_accepted_start_clears_it():
    rig = build_rig(plant_overrides={"bin_level_kg": 500.0})
    run(rig, 0.2)
    rig.line.start()
    run(rig, 0.2)
    rig.plant.bin.level_kg = 5_000.0
    run(rig, 0.2)
    rig.line.start()
    run(rig, 0.2)
    assert (rig.line.state.name, rig.line.start_inhibit) == ("STARTING", StartInhibit.NONE)


def test_published_and_decoded_over_the_status_block():
    rig = build_rig()
    rig.plant.hopper.level_kg = 1_950.0
    run(rig, 0.3)
    rig.line.start()
    run(rig, 0.2)
    registers = encode(rig.line)
    assert registers[5] == int(StartInhibit.HOPPER_HIGH_HIGH | StartInhibit.UNACKNOWLEDGED_ALARM) == 6
    assert decode(registers).start_inhibit == rig.line.start_inhibit


def test_every_bit_of_the_register_is_assigned():
    """CAUSE_STANDING (2026-09-26) took the last free bit of the 16-bit
    register (it replaced a test that used 0x8000 as an unknown bit): every
    value now decodes whole, and a seventeenth reason needs a second register."""
    all_bits = 0
    for member in StartInhibit:
        all_bits |= int(member)
    assert all_bits == 0xFFFF
    assert decode([0, 0, 0, 0, 0, 0xFFFF, 0, 0, 0, 1, 0, 0, 0]).start_inhibit == StartInhibit(0xFFFF)
