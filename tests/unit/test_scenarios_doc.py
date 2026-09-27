"""docs/SCENARIOS.md is the reference an engineer writes scenarios from, so
it must not drift from the code: every action, every expectation field,
every value a field can take is documented, nothing documented is
unknown, and every example in it is a real scenario that passes and fails
without its stimulus."""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from services.control.line_state import LineState, StartInhibit
from services.protocols.controller_status import ALARMS, FAULT_REASONS
from services.testing.runner import run_scenario
from services.testing.scenario import Scenario
from services.testing.vocabulary import APPLY_ACTIONS, READ_FIELDS

DOC = (Path(__file__).resolve().parents[2] / "docs" / "SCENARIOS.md").read_text(encoding="utf-8")


def _section(heading: str) -> str:
    start = DOC.index(f"\n## {heading}")
    end = DOC.find("\n## ", start + 1)
    return DOC[start:end if end != -1 else None]


def _first_column_keys(section: str) -> set[str]:
    """Every backticked name in the first column of the section's tables."""
    keys = set()
    for row in re.findall(r"^\| (.+?) \|", section, flags=re.M):
        keys |= set(re.findall(r"`([a-z_0-9]+)`", row))
    return keys


def test_every_action_is_documented_and_nothing_else():
    documented = _first_column_keys(_section("Actions")) - {"line_state"}
    assert documented == set(APPLY_ACTIONS)


def test_every_expectation_field_is_documented_and_nothing_else():
    documented = _first_column_keys(_section("Expectations"))
    assert documented == set(READ_FIELDS)


def test_every_value_is_documented():
    values = _section("Expectations")
    for state in LineState:
        assert f"`{state.name.lower()}`" in values, state
    for reason in StartInhibit:
        if reason:
            assert f"| `{reason.name}` |" in values, reason
    for reason in FAULT_REASONS:
        if reason:
            assert f"`{reason}`" in values, reason
    for alarm_id, description, is_warning in ALARMS:
        assert f"| `{alarm_id}` | {description} | {'warning' if is_warning else 'trip'} |" in values, alarm_id


def _examples() -> list[str]:
    return re.findall(r"```yaml\n(.*?)```", DOC, flags=re.S)


def test_the_examples_are_found():
    assert len(_examples()) == 3


@pytest.mark.parametrize("n", range(3))
def test_each_example_is_a_real_scenario_that_passes(tmp_path, n):
    f = tmp_path / "example.yaml"
    f.write_text(_examples()[n], encoding="utf-8")
    scenario = Scenario.load(f)
    assert run_scenario(scenario).passed
    if scenario.trigger:
        without = dataclasses.replace(scenario, when={k: v for k, v in scenario.when.items()
                                                      if k not in scenario.trigger})
        assert not run_scenario(without).passed, "the example passes without its stimulus"
