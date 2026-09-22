import pytest

from services.simulation.engine.io_image import IOImage, IOImageError, TagType


def make_image() -> IOImage:
    io = IOImage()
    io.define("DI-1", TagType.DI, description="a discrete input")
    io.define("DO-1", TagType.DO, description="a discrete output")
    io.define("AI-1", TagType.AI, units="kg", description="an analog input")
    io.define("AO-1", TagType.AO, units="%", description="an analog output")
    return io


def test_tags_default_to_type_appropriate_zero_value():
    io = make_image()
    assert io.read("DI-1") is False
    assert io.read("DO-1") is False
    assert io.read("AI-1") == 0.0
    assert io.read("AO-1") == 0.0


def test_define_rejects_duplicate_name():
    io = make_image()
    with pytest.raises(IOImageError):
        io.define("DI-1", TagType.DI)


def test_read_undefined_tag_raises():
    io = make_image()
    with pytest.raises(IOImageError):
        io.read("NOPE-1")


def test_write_undefined_tag_raises():
    io = make_image()
    with pytest.raises(IOImageError):
        io.write_input("NOPE-1", True)
    with pytest.raises(IOImageError):
        io.write_output("NOPE-1", True)


def test_either_side_may_read_any_tag():
    io = make_image()
    io.write_input("DI-1", True)
    io.write_output("DO-1", True)
    assert io.read("DI-1") is True
    assert io.read("DO-1") is True


def test_simulation_cannot_write_an_output_tag():
    """write_input() is Simulation's method — DO/AO are Control's to set."""
    io = make_image()
    with pytest.raises(IOImageError):
        io.write_input("DO-1", True)
    with pytest.raises(IOImageError):
        io.write_input("AO-1", 50.0)


def test_control_cannot_write_an_input_tag():
    """write_output() is Control's method — DI/AI are Simulation's to set."""
    io = make_image()
    with pytest.raises(IOImageError):
        io.write_output("DI-1", True)
    with pytest.raises(IOImageError):
        io.write_output("AI-1", 50.0)


def test_discrete_tag_rejects_non_bool():
    io = make_image()
    with pytest.raises(IOImageError):
        io.write_input("DI-1", 1)  # int, not bool — rejected on purpose
    with pytest.raises(IOImageError):
        io.write_input("DI-1", "true")


def test_analog_tag_rejects_bool_even_though_bool_is_an_int_subclass():
    io = make_image()
    with pytest.raises(IOImageError):
        io.write_input("AI-1", True)


def test_analog_tag_accepts_int_and_stores_as_float():
    io = make_image()
    io.write_input("AI-1", 5)
    assert io.read("AI-1") == 5.0
    assert isinstance(io.read("AI-1"), float)


def test_define_with_initial_value():
    io = IOImage()
    io.define("AI-1", TagType.AI, initial=42.0)
    assert io.read("AI-1") == 42.0


def test_tag_introspection_and_container_protocol():
    io = make_image()
    assert len(io) == 4
    assert "DI-1" in io
    assert "NOPE" not in io
    assert set(io.names()) == {"DI-1", "DO-1", "AI-1", "AO-1"}
    t = io.tag("AI-1")
    assert t.units == "kg"
    assert t.description == "an analog input"
    assert t.type == TagType.AI
