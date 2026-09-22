"""Discovers every declarative scenario under scenarios/ and runs each
through services.testing.runner -- so `pytest` alone covers them, no
separate tool required. The standalone runner/report (Phase 3 step 3) is
for the richer coverage-matrix output, not the only way to run these.
"""
from pathlib import Path

import pytest

from services.testing.runner import run_scenario
from services.testing.scenario import Scenario

SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "scenarios"
SCENARIOS = Scenario.discover(SCENARIOS_DIR)


def test_scenarios_directory_is_not_empty():
    assert SCENARIOS, f"expected at least one *.yaml scenario under {SCENARIOS_DIR}"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_scenario(scenario: Scenario):
    result = run_scenario(scenario)
    assert result.passed, f"{scenario.name} ({scenario.path.relative_to(SCENARIOS_DIR)}): {result.detail}"
