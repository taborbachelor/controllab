"""I/O mapping files (Phase 9 step 4): load, validate, and fail loudly."""
from pathlib import Path

import pytest

from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.map_file import MapFileError, load_map
from services.protocols.register_map import ControllerRanges
from services.simulation.engine.plant_io import build_line_io_image

REPO = Path(__file__).resolve().parents[2]
RELOCATED = REPO / "configs" / "io" / "relocated.yaml"


def comparable(m):
    return (
        sorted(m.points, key=lambda p: (p.table, p.address)),
        sorted((h.command, h.address, h.description) for h in m.hmi_coils),
        list(m.status_registers),
        m.hmi_request,
        m.hmi_ack,
    )


def test_the_committed_line_map_file_is_exactly_the_built_in_map():
    """The format can express the real contract, and configs/io/line.yaml
    can't drift from line_map.py."""
    loaded, name = load_map(REPO / "configs" / "io" / "line.yaml", build_line_io_image())
    assert comparable(loaded) == comparable(LINE_REGISTER_MAP)
    assert loaded.commands == LINE_REGISTER_MAP.commands  # the request/ack bit order
    assert name == "ControlLab line map (default)"


def test_the_relocated_map_is_five_ranges_at_its_own_offsets():
    loaded, _ = load_map(RELOCATED, build_line_io_image())
    assert loaded.controller_ranges() == ControllerRanges(
        discrete_inputs=(1000, 12), input_registers=(2000, 2), holding_read=(4100, 1),
        coils=(3000, 3), holding_write=(4000, 8),
    )


def write(tmp_path, text):
    path = tmp_path / "map.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def relocated_with(tmp_path, old, new):
    text = RELOCATED.read_text(encoding="utf-8")
    assert old in text
    return write(tmp_path, text.replace(old, new))


def test_leaving_out_the_status_block_declares_a_controller_without_one(tmp_path):
    no_status = RELOCATED.read_text(encoding="utf-8").split("\nstatus:")[0] + "\n"
    path = write(tmp_path, no_status.replace("ack: 4006", "ack: 4001"))  # keep the write range contiguous
    loaded, _ = load_map(path, build_line_io_image())
    assert loaded.status_registers == ()
    assert loaded.controller_ranges().holding_write == (4000, 2)


def test_a_partial_status_block_is_refused(tmp_path):
    path = relocated_with(tmp_path, "  start_inhibit: 4007\n", "")
    with pytest.raises(MapFileError, match=r"all six registers or none -- missing \['start_inhibit'\]"):
        load_map(path, build_line_io_image())


def test_every_problem_is_reported_at_once_including_validate(tmp_path):
    text = RELOCATED.read_text(encoding="utf-8")
    text = text.replace("name: Relocated", "nmae: typo\nname: Relocated")
    text = text.replace("    acknowledge: 3103\n", "")
    text = text.replace("  2001: {tag: WT-105, scale: 10, full_scale: 2000}", "  2001: WT-105")
    with pytest.raises(MapFileError) as e:
        load_map(write(tmp_path, text), build_line_io_image())
    message = str(e.value)
    assert "unknown key 'nmae'" in message
    assert "hmi.commands: missing ['acknowledge']" in message
    assert "input_registers[2001]: an analog point is {tag, scale, full_scale}, exactly" in message


def test_the_register_map_rules_still_apply_to_a_file(tmp_path):
    """A hole in a controller range, and a tag in the wrong table: the
    same RegisterMap.validate() every built-in map passes."""
    path = relocated_with(tmp_path, "  1010: ES-001", "  1011: ES-001")
    with pytest.raises(MapFileError, match="isn't one contiguous range"):
        load_map(path, build_line_io_image())
    path = relocated_with(tmp_path, "  3002: M-104.RUN", "  3002: M-104.RUNNING")
    with pytest.raises(MapFileError, match="M-104.RUNNING: DI belongs in discrete_input, not coil"):
        load_map(path, build_line_io_image())


def test_the_generated_document_says_when_there_is_no_status_block(tmp_path):
    from services.protocols.register_map import render_markdown

    no_status = RELOCATED.read_text(encoding="utf-8").split("\nstatus:")[0] + "\n"
    loaded, _ = load_map(write(tmp_path, no_status.replace("ack: 4006", "ack: 4001")), build_line_io_image())
    md = render_markdown(loaded, build_line_io_image(), "T", source="`map.yaml`")
    assert "| 4000 | 2 | analog outputs, HMI ack word (no status block) |" in md
    assert "from `map.yaml`" in md
