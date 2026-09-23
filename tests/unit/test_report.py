"""Unit tests for the coverage-matrix logic, using lightweight fakes for
Scenario/ScenarioResult rather than real YAML files or a real rig --
build_report() only ever reads .interlock/.name and .passed.
"""
from dataclasses import dataclass
from pathlib import Path

from services.testing.report import INTERLOCKS, CoverageReport, InterlockRow, RowCoverage, build_report


@dataclass
class FakeScenario:
    name: str
    interlock: str | None = None
    path: Path = Path("fake.yaml")


@dataclass
class FakeResult:
    passed: bool
    not_observable: bool = False
    not_observed: tuple = ()


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


def test_the_alarms_row_is_applicable_now_that_alarms_exist():
    """Phase 4 steps 1-2: AlarmManager exists and is wired into
    LineController, so this row is real, testable coverage now -- not
    a permanent not_applicable stub."""
    report = build_report([])
    row = next(r for r in report.rows if r.row.name == "No active latched alarms")
    assert row.row.applicable is True
    assert row.status == "not_covered"  # this fixture tags no scenarios at all


def test_a_row_marked_not_applicable_reports_that_status_regardless_of_scenarios():
    """Direct unit test of the not_applicable status branch itself,
    decoupled from whether any row in the real INTERLOCKS table
    currently happens to be marked that way -- true right now (every
    row is applicable), but this behavior still needs its own test."""
    row = InterlockRow("Fake Row", "Trip", applicable=False, note="doesn't exist yet")
    coverage = RowCoverage(row=row, scenarios=[("S1", True)])
    assert coverage.status == "not_applicable"


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
    """A synthetic CoverageReport, not the real INTERLOCKS table -- this
    is aggregate-property logic, and pinning it to today's exact row
    count/mix (as the old version of this test did, via
    len(INTERLOCKS) arithmetic) breaks it every time the real table
    changes, which is exactly what happened when the alarms row stopped
    being permanently not_applicable."""
    report = CoverageReport(
        results=[],
        rows=[
            RowCoverage(row=InterlockRow("Covered", "Trip"), scenarios=[("S1", True)]),
            RowCoverage(row=InterlockRow("Gap", "Trip"), scenarios=[]),
            RowCoverage(row=InterlockRow("N/A", "Trip", applicable=False), scenarios=[]),
        ],
        unknown_tags=[],
    )
    assert report.covered_count == 1
    assert report.not_applicable_count == 1
    assert report.gap_count == 1


def test_gap_count_includes_covered_but_failing():
    results = [(FakeScenario("S1", interlock="Hopper not high-high"), FakeResult(False))]
    report = build_report(results)
    assert report.covered_count == 0
    assert report.gap_count == len(INTERLOCKS)  # every row is a gap here -- none are not_applicable anymore

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


def test_a_row_whose_scenarios_observed_nothing_is_not_observable_not_a_gap():
    """Phase 9 step 3: against a controller with no status block, a
    scenario that could observe nothing neither covers its row nor leaves
    a gap -- the test exists, it just can't see anything here."""
    report = build_report([(FakeScenario("S1", "Hopper not high-high"), FakeResult(False, not_observable=True))])
    row = next(r for r in report.rows if r.row.name == "Hopper not high-high")
    assert row.status == "not_observable"
    assert report.failed_count == 0 and report.not_observable_count == 1


def test_one_observing_scenario_is_enough_to_cover_the_row():
    report = build_report([
        (FakeScenario("S1", "E-stop healthy"), FakeResult(False, not_observable=True)),
        (FakeScenario("S2", "E-stop healthy"), FakeResult(True, not_observed=("line_state",))),
    ])
    row = next(r for r in report.rows if r.row.name == "E-stop healthy")
    assert row.status == "covered"


def test_verdict_is_partial_when_nothing_failed_but_something_went_unobserved():
    from services.testing.report import INTERLOCKS

    every_row = [(FakeScenario(f"S{i}", row.name), FakeResult(True)) for i, row in enumerate(INTERLOCKS)]
    assert build_report(every_row).verdict == "PASS"
    partly = every_row[:-1] + [(every_row[-1][0], FakeResult(True, not_observed=("line_state",)))]
    assert build_report(partly).verdict == "PARTIAL"
    failing = every_row[:-1] + [(every_row[-1][0], FakeResult(False))]
    assert build_report(failing).verdict == "FAIL"
