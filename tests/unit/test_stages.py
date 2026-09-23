"""Multi-stage scenarios (`then:`): stages run in order, each applied once
the previous one's expectations hold; the scenario passes only if all do."""
from pathlib import Path

import pytest

from services.testing.runner import run_scenario
from services.testing.scenario import Scenario, ScenarioLoadError

REPO = Path(__file__).resolve().parents[2]


def write(tmp_path, text):
    path = tmp_path / "s.yaml"
    path.write_text(text, encoding="utf-8")
    return Scenario.load(path)


BASE = """name: s
given: {line_state: running}
when: {feeder_trip: true}
expect: {line_state: faulted}
within: {seconds: 0.5}
"""


def test_a_single_stage_scenario_has_exactly_one_stage():
    s = Scenario.load(REPO / "scenarios" / "faults" / "feeder_trip_while_running.yaml")
    assert len(s.stages) == 1 and s.then == ()
    assert run_scenario(s).stage_elapsed == (0.2,)


def test_stages_run_in_order_and_each_is_timed(tmp_path):
    s = write(tmp_path, BASE + """then:
  - when: {acknowledge: true}
    expect: {any_unacknowledged_trip: false}
    within: {seconds: 0.5}
""")
    result = run_scenario(s)
    assert result.passed and result.stage_elapsed == (0.2, 0.1)
    assert result.elapsed_s == 0.2  # the response to `when`, as before


def test_a_failing_later_stage_fails_the_scenario_and_says_which(tmp_path):
    s = write(tmp_path, BASE + """then:
  - when: {reset: true}
    expect: {line_state: idle}
    within: {seconds: 0.5}
""")
    result = run_scenario(s)  # the drive is still tripped: reset is refused
    assert not result.passed
    assert result.detail.startswith("stage 2/2: timed out after 0.5s")


@pytest.mark.parametrize("stage", [
    "  - when: {reset: true}\n",                                    # no expect/within
    "  - expect: {}\n    within: {seconds: 1}\n",                   # expects nothing
    "  - expect: {line_state: idle}\n    within: {seconds: 1}\n    wait: 3\n",  # unknown key
])
def test_malformed_stages_fail_at_load(tmp_path, stage):
    with pytest.raises(ScenarioLoadError):
        write(tmp_path, BASE + "then:\n" + stage)


def test_later_stages_are_real_stimuli_not_setup(tmp_path):
    """The stage-2 'reset refused' claim is only meaningful because reset
    DOES work once its cause is gone: the recovery scenario proves both."""
    result = run_scenario(Scenario.load(REPO / "scenarios" / "faults" / "feeder_trip_recovery.yaml"))
    assert result.passed and len(result.stage_elapsed) == 5
