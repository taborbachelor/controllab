"""TagHistory is deliberately generic (services/telemetry/tag_history.py's
own docstring) -- these tests build a bare synthetic IOImage, the same
way test_io_image.py and test_motor_control.py/test_gate_control.py do,
to prove it never assumes this line's actual tags.
"""
from services.simulation.engine.io_image import IOImage, TagType
from services.telemetry.tag_history import TagHistory, write_csv


def make_image() -> IOImage:
    io = IOImage()
    io.define("DI-1", TagType.DI, description="a discrete input")
    io.define("AI-1", TagType.AI, units="kg", description="an analog input")
    return io


def test_record_captures_every_tag_at_that_moment():
    io = make_image()
    io.write_input("DI-1", True)
    io.write_input("AI-1", 12.5)

    history = TagHistory(io)
    history.record(t=1.0)

    assert len(history.samples) == 1
    sample = history.samples[0]
    assert sample.t == 1.0
    assert sample.values == {"DI-1": True, "AI-1": 12.5}


def test_multiple_records_accumulate_in_order():
    io = make_image()
    history = TagHistory(io)

    history.record(t=0.0)
    io.write_input("AI-1", 5.0)
    history.record(t=0.1)

    assert [s.t for s in history.samples] == [0.0, 0.1]
    assert history.samples[0].values["AI-1"] == 0.0
    assert history.samples[1].values["AI-1"] == 5.0


def test_tag_names_is_the_sorted_union_of_recorded_tags():
    io = make_image()
    history = TagHistory(io)
    history.record(t=0.0)
    assert history.tag_names == ["AI-1", "DI-1"]


def test_tag_names_includes_a_tag_defined_after_recording_started():
    io = make_image()
    history = TagHistory(io)
    history.record(t=0.0)

    io.define("DO-1", TagType.DO, description="added mid-run")
    history.record(t=0.1)

    assert history.tag_names == ["AI-1", "DI-1", "DO-1"]


def test_record_is_a_snapshot_not_a_live_view():
    """A later write must not retroactively change an earlier sample --
    each record() call is a point-in-time copy, not a reference into the
    live IOImage."""
    io = make_image()
    history = TagHistory(io)
    history.record(t=0.0)
    io.write_input("AI-1", 999.0)
    assert history.samples[0].values["AI-1"] == 0.0


def test_write_csv_produces_a_header_and_one_row_per_sample(tmp_path):
    io = make_image()
    io.write_input("DI-1", True)
    io.write_input("AI-1", 1.5)
    history = TagHistory(io)
    history.record(t=0.0)
    io.write_input("AI-1", 2.5)
    history.record(t=0.1)

    out = tmp_path / "tags.csv"
    write_csv(history, out)

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "t,AI-1,DI-1"
    assert lines[1] == "0.0,1.5,True"
    assert lines[2] == "0.1,2.5,True"


def test_write_csv_blanks_a_column_for_a_sample_missing_it(tmp_path):
    io = make_image()
    history = TagHistory(io)
    history.record(t=0.0)
    io.define("DO-1", TagType.DO)
    io.write_output("DO-1", True)
    history.record(t=0.1)

    out = tmp_path / "tags.csv"
    write_csv(history, out)

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "t,AI-1,DI-1,DO-1"
    assert lines[1] == "0.0,0.0,False,"  # DO-1 didn't exist yet -- blank, not a crash
    assert lines[2] == "0.1,0.0,False,True"
