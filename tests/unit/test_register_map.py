"""RegisterMap validation, IOImageDataStore scaling/permissions, and the
drift guard on the committed map document. The store is exercised through
handle_pdu() -- the same bytes a PLC would send -- so the permission rules
are checked as Modbus exception responses, not Python exceptions."""
from pathlib import Path

import pytest

from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.modbus import ILLEGAL_DATA_ADDRESS, handle_pdu
from services.protocols.register_map import (
    COIL,
    DISCRETE_INPUT,
    HOLDING_REGISTER,
    INPUT_REGISTER,
    HmiCoil,
    HmiLatches,
    IOImageDataStore,
    Point,
    RegisterMap,
    contiguous_runs,
    to_raw,
)
from services.simulation.engine.io_image import IOImage, TagType
from services.simulation.engine.plant_io import build_line_io_image

REPO = Path(__file__).resolve().parents[2]


def small_io() -> IOImage:
    io = IOImage()
    io.define("DI-1", TagType.DI)
    io.define("DO-1", TagType.DO)
    io.define("AI-1", TagType.AI, units="%")
    io.define("AO-1", TagType.AO, units="%")
    return io


def small_map(**overrides) -> RegisterMap:
    points = {
        "DI-1": Point("DI-1", DISCRETE_INPUT, 0),
        "DO-1": Point("DO-1", COIL, 0),
        "AI-1": Point("AI-1", INPUT_REGISTER, 0, scale=100, full_scale=100),
        "AO-1": Point("AO-1", HOLDING_REGISTER, 0, scale=100, full_scale=100),
    }
    points.update(overrides)
    return RegisterMap(points=tuple(p for p in points.values() if p is not None), hmi_coils=(HmiCoil("start", 10),))


# ---- validation ------------------------------------------------------------

def test_the_line_map_is_valid_and_covers_all_17_tags():
    io = build_line_io_image()
    LINE_REGISTER_MAP.validate(io)
    assert sorted(p.tag for p in LINE_REGISTER_MAP.points) == sorted(io.names())


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"DI-1": Point("DI-1", COIL, 5)}, "DI belongs in discrete_input"),
        ({"AO-1": Point("AO-1", HOLDING_REGISTER, 0, scale=1000, full_scale=100)}, "doesn't fit in 16 bits"),
        ({"DO-1": None}, "DO-1: in the I/O image but not mapped"),
        ({"X": Point("GHOST", COIL, 3)}, "GHOST: not a tag"),
        ({"X": Point("DO-1", COIL, 10)}, "HMI start: coil 10 already used by DO-1"),
    ],
)
def test_validation_catches_contract_mistakes(overrides, expected):
    with pytest.raises(ValueError, match=expected):
        small_map(**overrides).validate(small_io())


def test_validation_reports_every_problem_at_once():
    bad = RegisterMap(points=(Point("DI-1", COIL, 0), Point("DO-1", COIL, 0)))
    with pytest.raises(ValueError) as e:
        bad.validate(small_io())
    msg = str(e.value)
    assert "DI belongs in discrete_input" in msg and "already used by DI-1" in msg and "AI-1: in the I/O image but not mapped" in msg


# ---- the data store ----------------------------------------------------------

def store(outputs_writable=False, commands=None):
    io = small_io()
    s = IOImageDataStore(small_map(), lambda: io, on_command=(commands.append if commands is not None else None), outputs_writable=outputs_writable)
    return s, io


def test_reads_reflect_the_io_image_with_scaling():
    s, io = store()
    io.write_input("DI-1", True)
    io.write_input("AI-1", 19.87)
    assert handle_pdu(s, bytes.fromhex("0200000001")) == bytes.fromhex("020101")
    assert handle_pdu(s, bytes.fromhex("0400000001")) == bytes.fromhex("040207C3")  # 1987


def test_analog_values_clamp_instead_of_wrapping():
    assert to_raw(-5.0, 100) == 0
    assert to_raw(700.0, 100) == 0xFFFF


def test_outputs_are_read_only_while_the_built_in_controller_owns_them():
    s, io = store(outputs_writable=False)
    io.write_output("DO-1", True)
    assert handle_pdu(s, bytes.fromhex("0100000001")) == bytes.fromhex("010101")  # readable
    assert handle_pdu(s, bytes.fromhex("0500000000")) == bytes((0x85, ILLEGAL_DATA_ADDRESS))
    assert handle_pdu(s, bytes.fromhex("0600000064")) == bytes((0x86, ILLEGAL_DATA_ADDRESS))
    assert io.read("DO-1") is True  # untouched


def test_outputs_are_writable_in_external_controller_mode():
    s, io = store(outputs_writable=True)
    assert handle_pdu(s, bytes.fromhex("050000FF00")) == bytes.fromhex("050000FF00")
    assert handle_pdu(s, bytes.fromhex("0600001388")) == bytes.fromhex("0600001388")  # 5000 -> 50.00 %
    assert io.read("DO-1") is True
    assert io.read("AO-1") == 50.0


def test_hmi_coils_are_momentary_and_issue_commands():
    commands = []
    s, _ = store(commands=commands)
    assert handle_pdu(s, bytes.fromhex("05000AFF00")) == bytes.fromhex("05000AFF00")
    assert handle_pdu(s, bytes.fromhex("05000A0000")) == bytes.fromhex("05000A0000")  # 0 does nothing
    assert commands == ["start"]
    assert handle_pdu(s, bytes.fromhex("01000A0001")) == bytes.fromhex("010100")  # always reads 0


def test_hmi_coils_work_even_while_outputs_are_read_only():
    commands = []
    s, _ = store(outputs_writable=False, commands=commands)
    handle_pdu(s, bytes.fromhex("05000AFF00"))
    assert commands == ["start"]


def test_a_read_spanning_an_unmapped_address_is_refused_not_padded():
    s, _ = store()
    assert handle_pdu(s, bytes.fromhex("0100000002")) == bytes((0x81, ILLEGAL_DATA_ADDRESS))


def test_a_refused_multi_write_changes_nothing():
    s, io = store(outputs_writable=True)
    # coils 0..1: coil 1 is unmapped, so the whole write is refused
    assert handle_pdu(s, bytes.fromhex("0F000000020103")) == bytes((0x8F, ILLEGAL_DATA_ADDRESS))
    assert io.read("DO-1") is False


def test_the_store_asks_for_the_io_image_each_time():
    """So the dashboard's New session (a fresh IOImage) is picked up
    without re-creating the server."""
    first, second = small_io(), small_io()
    current = [first]
    s = IOImageDataStore(small_map(), lambda: current[0])
    second.write_input("DI-1", True)
    current[0] = second
    assert handle_pdu(s, bytes.fromhex("0200000001")) == bytes.fromhex("020101")


# ---- the committed document --------------------------------------------------

def test_committed_map_document_matches_the_served_map():
    """docs/MODBUS-MAP.md is generated; if line_map.py changes and the
    document isn't regenerated, this fails. Regenerate with
    `python scripts/register_map.py --out docs/MODBUS-MAP.md`."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("register_map_script", REPO / "scripts" / "register_map.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (REPO / "docs" / "MODBUS-MAP.md").read_text(encoding="utf-8") == module.render()


# ---- external-controller mode (Phase 7 step 3) ---------------------------------

def test_latched_hmi_is_a_request_acknowledge_handshake():
    latches = HmiLatches(["start"])
    io = small_io()
    s = IOImageDataStore(small_map(), lambda: io, hmi_latches=latches)
    assert handle_pdu(s, bytes.fromhex("01000A0001")) == bytes.fromhex("010100")  # nothing requested
    latches.request("start")  # ControlLab side
    assert handle_pdu(s, bytes.fromhex("01000A0001")) == bytes.fromhex("010101")  # stays set until taken...
    assert handle_pdu(s, bytes.fromhex("01000A0001")) == bytes.fromhex("010101")  # ...across any number of reads
    handle_pdu(s, bytes.fromhex("05000A0000"))  # controller acknowledges by writing 0
    assert latches.requested["start"] is False


def test_unknown_hmi_request_is_rejected():
    with pytest.raises(ValueError):
        HmiLatches(["start"]).request("launch")


def test_output_writes_feed_the_heartbeat_but_hmi_writes_do_not():
    beats = []
    io = small_io()
    s = IOImageDataStore(small_map(), lambda: io, outputs_writable=True, hmi_latches=HmiLatches(["start"]),
                         on_output_write=lambda: beats.append(1))
    handle_pdu(s, bytes.fromhex("05000A0000"))  # HMI acknowledge
    assert beats == []
    handle_pdu(s, bytes.fromhex("050000FF00"))  # a coil output
    handle_pdu(s, bytes.fromhex("0600000064"))  # a holding-register output
    assert beats == [1, 1]


def test_contiguous_runs_never_span_a_hole():
    assert contiguous_runs([0, 1, 2, 5, 6, 100]) == [(0, 3), (5, 2), (100, 1)]
    assert contiguous_runs([3, 1, 2]) == [(1, 3)]
    assert contiguous_runs([]) == []
