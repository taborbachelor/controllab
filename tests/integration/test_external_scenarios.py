"""Every commissioning scenario, run against the reference external
controller across Modbus (Phase 7 step 3b). The runner, vocabulary,
invariants and scenario files are the same ones the built-in suite uses;
only the rig's `line` differs -- a RemoteLine whose commands are latched
HMI requests and whose state is read back from the published status
registers."""
from pathlib import Path

import pytest

from services.testing.runner import run_scenario
from services.testing.scenario import Scenario

SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "scenarios"
SCENARIOS = Scenario.discover(SCENARIOS_DIR)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_scenario_passes_against_the_external_controller(scenario):
    result = run_scenario(scenario, external=True)
    assert result.passed, f"{scenario.name} (external): {result.detail}"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_external_run_records_exactly_the_built_in_event_log(scenario):
    """Stronger than pass/fail: the same events, at the same simulated
    times. Lockstep keeps the built-in tick order (controller scans, then
    the plant moves), and the latched HMI request is taken in the very
    scan a built-in command would be consumed -- so crossing the wire
    changes nothing a scenario can observe."""
    built_in = run_scenario(scenario)
    external = run_scenario(scenario, external=True)
    as_tuples = lambda r: [(e.t, e.type, e.data) for e in r.events]  # noqa: E731
    assert as_tuples(external) == as_tuples(built_in)
    assert external.elapsed_s == built_in.elapsed_s
