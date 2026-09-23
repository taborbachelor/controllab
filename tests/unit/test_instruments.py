"""Field-instrument faults (Phase 4 completion): stuck vs failed."""
import pytest

from services.simulation.equipment.instruments import InstrumentFault, Instruments


def reporting(**values):
    inst = Instruments(diagnosed={"WT-105"})
    for tag, value in values.items():
        inst.report(tag, value)
    return inst


def test_a_healthy_instrument_reports_the_truth():
    inst = reporting(WT=1.0)
    assert inst.report("WT", 42.0) == 42.0 and not inst.channel_fault("WT")


def test_a_stuck_instrument_keeps_its_last_reading_while_the_process_moves():
    inst = reporting(**{"WT-105": 500.0})
    inst.stick("WT-105")
    assert [inst.report("WT-105", v) for v in (600.0, 900.0, 1900.0)] == [500.0, 500.0, 500.0]
    assert not inst.channel_fault("WT-105")  # nothing says it's wrong


def test_a_switch_can_stick_too():
    inst = reporting(**{"LSHH-105": False})
    inst.stick("LSHH-105")
    assert inst.report("LSHH-105", True) is False


def test_a_failed_instrument_reads_bottom_of_range_and_raises_its_diagnostic():
    inst = reporting(**{"WT-105": 500.0})
    inst.fail("WT-105")
    assert inst.report("WT-105", 500.0) == 0.0
    assert inst.channel_fault("WT-105") and inst.fault("WT-105") is InstrumentFault.FAILED


def test_a_failed_switch_reads_open_with_no_diagnostic():
    """A broken wire on a switch reads 0 whatever the level. It has no
    channel diagnostic, so nothing else says it failed; on a fail-safe
    switch (LSHH-105: 1 = below) that 0 is the tripped state."""
    inst = reporting(**{"LSHH-105": True})
    inst.fail("LSHH-105")
    assert inst.report("LSHH-105", True) is False
    assert not inst.channel_fault("LSHH-105")


def test_an_analog_input_without_a_diagnostic_cannot_fail_only_stick():
    inst = reporting(**{"LT-101": 50.0})
    with pytest.raises(ValueError, match="no channel diagnostic"):
        inst.fail("LT-101")


def test_restore_returns_to_the_truth():
    inst = reporting(**{"WT-105": 500.0})
    inst.fail("WT-105")
    inst.restore("WT-105")
    assert inst.report("WT-105", 700.0) == 700.0 and not inst.channel_fault("WT-105")


def test_an_unknown_instrument_is_refused():
    with pytest.raises(ValueError, match="not an instrument"):
        reporting().stick("XX-999")
