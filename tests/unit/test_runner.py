import pytest

from services.testing.runner import run_scenario
from services.testing.scenario import Scenario, ScenarioLoadError


def load(tmp_path, text: str) -> Scenario:
    p = tmp_path / "s.yaml"
    p.write_text(text, encoding="utf-8")
    return Scenario.load(p)


def test_unsupported_given_line_state_raises_load_error(tmp_path):
    s = load(
        tmp_path,
        """
        name: Bad given
        given: {line_state: faulted}
        expect: {line_state: idle}
        within: {seconds: 1.0}
        """,
    )
    with pytest.raises(ScenarioLoadError):
        run_scenario(s)


def test_unknown_given_field_raises_load_error(tmp_path):
    s = load(
        tmp_path,
        """
        name: Bad field
        given: {not_a_real_field: true}
        expect: {line_state: idle}
        within: {seconds: 1.0}
        """,
    )
    with pytest.raises(ScenarioLoadError):
        run_scenario(s)


def test_unknown_when_field_raises_load_error(tmp_path):
    s = load(
        tmp_path,
        """
        name: Bad when
        when: {not_a_real_field: true}
        expect: {line_state: idle}
        within: {seconds: 1.0}
        """,
    )
    with pytest.raises(ScenarioLoadError):
        run_scenario(s)


def test_unknown_expect_field_raises_load_error(tmp_path):
    s = load(
        tmp_path,
        """
        name: Bad expect
        expect: {not_a_real_field: true}
        within: {seconds: 1.0}
        """,
    )
    with pytest.raises(ScenarioLoadError):
        run_scenario(s)


def test_given_line_state_running_unreachable_raises_load_error(tmp_path):
    """A conveyor that can never start makes 'given: line_state: running'
    an impossible setup -- that's a broken scenario, not a system finding,
    so it must raise rather than report a quiet failed result."""
    s = load(
        tmp_path,
        """
        name: Impossible given
        given: {conveyor_fail_to_start: true, line_state: running}
        expect: {line_state: running}
        within: {seconds: 1.0}
        """,
    )
    with pytest.raises(ScenarioLoadError):
        run_scenario(s)


def test_expectation_never_met_times_out_as_a_failed_result_not_an_error(tmp_path):
    s = load(
        tmp_path,
        """
        name: Never happens
        expect: {line_state: running}
        within: {seconds: 0.3}
        """,
    )
    result = run_scenario(s)
    assert result.passed is False
    assert "timed out" in result.detail
    assert "line_state" in result.detail


def test_passing_scenario_reports_elapsed_time_less_than_the_window(tmp_path):
    s = load(
        tmp_path,
        """
        name: Trivially true
        expect: {line_state: idle}
        within: {seconds: 5.0}
        """,
    )
    result = run_scenario(s)
    assert result.passed is True
    assert result.elapsed_s <= 5.0
