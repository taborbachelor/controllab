import pytest

from services.testing.scenario import Scenario, ScenarioLoadError


def write(tmp_path, text: str, name: str = "s.yaml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_loads_a_minimal_scenario(tmp_path):
    p = write(
        tmp_path,
        """
        name: Minimal
        expect:
          line_state: idle
        within:
          seconds: 1.0
        """,
    )
    s = Scenario.load(p)
    assert s.name == "Minimal"
    assert s.given == {}
    assert s.when == {}
    assert s.expect == {"line_state": "idle"}
    assert s.within_s == 1.0
    assert s.interlock is None


def test_within_milliseconds_converts_to_seconds(tmp_path):
    p = write(
        tmp_path,
        """
        name: MS
        expect: {line_state: idle}
        within: {milliseconds: 500}
        """,
    )
    assert Scenario.load(p).within_s == 0.5


def test_given_when_and_interlock_are_captured(tmp_path):
    p = write(
        tmp_path,
        """
        name: Full
        given: {line_state: running}
        when: {estop: tripped}
        expect: {line_state: estopped}
        within: {seconds: 0.5}
        interlock: "E-stop healthy"
        """,
    )
    s = Scenario.load(p)
    assert s.given == {"line_state": "running"}
    assert s.when == {"estop": "tripped"}
    assert s.interlock == "E-stop healthy"


def test_missing_name_raises(tmp_path):
    p = write(tmp_path, "expect: {line_state: idle}\nwithin: {seconds: 1.0}\n")
    with pytest.raises(ScenarioLoadError):
        Scenario.load(p)


def test_missing_expect_raises(tmp_path):
    p = write(tmp_path, "name: X\nwithin: {seconds: 1.0}\n")
    with pytest.raises(ScenarioLoadError):
        Scenario.load(p)


def test_missing_within_raises(tmp_path):
    p = write(tmp_path, "name: X\nexpect: {line_state: idle}\n")
    with pytest.raises(ScenarioLoadError):
        Scenario.load(p)


def test_within_without_seconds_or_milliseconds_raises(tmp_path):
    p = write(tmp_path, "name: X\nexpect: {line_state: idle}\nwithin: {}\n")
    with pytest.raises(ScenarioLoadError):
        Scenario.load(p)


def test_non_mapping_top_level_raises(tmp_path):
    p = write(tmp_path, "- just\n- a\n- list\n")
    with pytest.raises(ScenarioLoadError):
        Scenario.load(p)


def test_invalid_yaml_raises(tmp_path):
    p = write(tmp_path, "name: [unclosed\n")
    with pytest.raises(ScenarioLoadError):
        Scenario.load(p)


def test_discover_finds_and_sorts_all_yaml_files(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "a").mkdir()
    write(tmp_path / "b", "name: B\nexpect: {line_state: idle}\nwithin: {seconds: 1.0}\n", "s.yaml")
    write(tmp_path / "a", "name: A\nexpect: {line_state: idle}\nwithin: {seconds: 1.0}\n", "s.yaml")

    found = Scenario.discover(tmp_path)
    assert [s.name for s in found] == ["A", "B"]  # sorted by path, deterministic
