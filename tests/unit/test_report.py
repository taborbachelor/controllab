"""Unit tests for the coverage-matrix logic, using lightweight fakes for
Scenario/ScenarioResult rather than real YAML files or a real rig --
build_report() only ever reads .interlock/.name and .passed.
"""
from dataclasses import dataclass
from pathlib import Path

from services.testing.report import INTERLOCKS, build_report


@dataclass
class FakeScenario:
    name: str
    interlock: str | None = None
    path: Path = Path("fake.yaml")


@dataclass
class FakeResult:
    passed: bool


def test_a_row_with_no_matching_scenario_is_not_covered():
    report = build_report([])
    row = next(r for r in report.rows if r.row.name == "Hopper not high-high")
    assert row.status == "not_covered"


def test_a_row_with_one_passing_scenario_is_covered():
    results = [(FakeScenario("S1", interlock="Hopper not high-high"), FakeResult(True))]
    report = build_report(results)
    row = next(r for r in report.rows if r.row.name == "Hopper not high-high")
    assert row.status == "covered"


def test_a_row_with_a_failing_scenario_is_covered_but_failing_not_not_covered():
    results = [(FakeScenario("S1", interlock="Hopper not high-high"), FakeResult(False))]
    report = build_report(results)
    row = next(r for r in report.rows if r.row.name == "Hopper not high-high")
    assert row.status == "covered_but_failing"


def test_a_row_with_one_passing_and_one_failing_scenario_is_covered_but_failing():
    results = [
        (FakeScenario("S1", interlock="Hopper not high-high"), FakeResult(True)),
        (FakeScenario("S2", interlock="Hopper not high-high"), FakeResult(False)),
    ]
    report = build_report(results)
    row = next(r for r in report.rows if r.row.name == "Hopper not high-high")
    assert row.status == "covered_but_failing"


def test_the_alarms_row_is_not_applicable_regardless_of_scenarios():
    report = build_report([])
    row = next(r for r in report.rows if r.row.name == "No active latched alarms")
    assert row.status == "not_applicable"
    assert row.row.applicable is False


def test_unknown_interlock_tag_is_reported_as_a_likely_typo():
    results = [(FakeScenario("S1", interlock="Gate travle timeout"), FakeResult(True))]
    report = build_report(results)
    assert report.unknown_tags == ["Gate travle timeout"]
    # And it must NOT silently count toward the real "Gate travel timeout" row.
    row = next(r for r in report.rows if r.row.name == "Gate travel timeout")
    assert row.status == "not_covered"


def test_untagged_scenarios_do_not_appear_as_unknown_tags():
    results = [(FakeScenario("S1", interlock=None), FakeResult(True))]
    report = build_report(results)
    assert report.unknown_tags == []


def test_covered_count_excludes_not_applicable_and_gaps():
    results = [(FakeScenario("S1", interlock="Hopper not high-high"), FakeResult(True))]
    report = build_report(results)
    assert report.covered_count == 1
    assert report.not_applicable_count == 1  # the alarms row
    assert report.gap_count == len(INTERLOCKS) - 1 - 1  # everything except that one covered row and the N/A row


def test_gap_count_includes_covered_but_failing():
    results = [(FakeScenario("S1", interlock="Hopper not high-high"), FakeResult(False))]
    report = build_report(results)
    assert report.covered_count == 0
    assert report.gap_count == len(INTERLOCKS) - 1  # every row except the N/A one is a gap here

    row = next(r for r in report.rows if r.row.name == "Hopper not high-high")
    assert row.status == "covered_but_failing"


def test_passed_count_reflects_results_not_rows():
    results = [
        (FakeScenario("S1", interlock="Hopper not high-high"), FakeResult(True)),
        (FakeScenario("S2", interlock="Hopper not high-high"), FakeResult(False)),
    ]
    report = build_report(results)
    assert report.passed_count == 1


def test_interlocks_table_has_exactly_the_eight_docs_rows():
    """A change to docs/CONTROL-LAB.md §6.3 that isn't mirrored here
    should be caught by a human reviewing this test failing, not
    discovered by someone noticing the report quietly under- or
    over-counts."""
    assert len(INTERLOCKS) == 8
    assert len({row.name for row in INTERLOCKS}) == 8  # no duplicate rows
