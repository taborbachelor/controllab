"""The interlock coverage matrix (docs/CONTROL-LAB.md §6.3, and the
Testing-tiers table's "Commissioning suite... producing a report").

Cross-references every scenario's `interlock:` tag against the full §6.3
table, distinguishing three real states per row — conflating any two of
them would misrepresent what's actually missing:

- **covered** — at least one scenario tags this row, and all of them
  currently pass.
- **covered but failing** — at least one scenario tags this row, but not
  all of them pass. Surfaced loudly, never folded into "not covered" —
  a regression in existing coverage is a different, more urgent kind of
  problem than a row nobody has written a test for yet.
- **not covered** — no scenario tags this row. A real, actionable gap.
- **not applicable yet** — the row's own underlying mechanism doesn't
  exist in the codebase yet (e.g. the alarm system, Phase 4). Writing a
  scenario for it would mean fabricating coverage for something nothing
  implements — worse than leaving it visibly blank.
- **not observable** — scenarios tag this row, but against this
  controller none of them could observe anything: every expectation
  needs a status block it doesn't publish (Phase 9 step 3). Not covered
  (nothing was verified) and not a gap (the test exists and would run
  against a controller that publishes it).

Pure logic, no I/O — `scripts/scenario_report.py` is the thin CLI that
runs the scenarios and prints this.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from services.testing.runner import ScenarioResult
from services.testing.scenario import Scenario


@dataclass(frozen=True)
class InterlockRow:
    name: str
    kind: str
    applicable: bool = True
    note: str = ""


# docs/CONTROL-LAB.md §6.3, verbatim row names -- a scenario's `interlock:`
# field must match one of these exactly to be counted (see unknown_tags
# below for what happens when it doesn't).
INTERLOCKS: list[InterlockRow] = [
    InterlockRow("E-stop healthy", "Permissive + trip"),
    InterlockRow(
        "No active latched alarms",
        "Permissive",
        note="the full latch/acknowledge lifecycle is proven by multi-stage scenarios: "
        "refused on the unacknowledged alarm alone once its cause is gone, accepted once "
        "acknowledged (alarm_lifecycle_start_refused_until_acknowledged), and a recovered "
        "but unacknowledged warning never blocking (unacknowledged_warning_never_blocks_start)",
    ),
    InterlockRow("Hopper not high-high", "Permissive"),
    InterlockRow(
        "Bin not low",
        "Permissive",
        note='the "warning only while running" half is proven by a scenario reaching the '
        "warning, and sustained over 10 s of running at the pytest level -- a declarative "
        "scenario passes the moment its expectations first hold, so it can't show the line "
        "never trips later; see tests/integration/test_line_controller.py::"
        "test_bin_low_while_running_stays_a_warning_for_the_whole_run",
    ),
    # Hardening (2026-09-25): a gate stuck open no longer lets a start through.
    InterlockRow("Gates proven closed", "Permissive"),
    InterlockRow(
        "Conveyor proven running",
        "Permissive + trip for feeder",
        note="the permissive half (feeder cannot run onto a stopped belt) is proven "
        "declaratively in Manual mode, the one place an operator can attempt the wrong "
        "order (manual_feeder_refused_without_conveyor); in Auto the sequence has no way "
        "to attempt it, see tests/integration/test_line_controller.py::"
        "test_wrong_order_spillage_is_structurally_unreachable_through_control",
    ),
    InterlockRow("Hopper high-high", "Trip"),
    InterlockRow("Hopper level instruments agree", "Alarm"),
    InterlockRow("Any motor fail-to-start / trip", "Trip"),
    InterlockRow("Gate travel timeout", "Trip"),
    InterlockRow("Feeder jam", "Trip"),
    InterlockRow("Hopper weight signal healthy", "Permissive + trip"),
    # Master specification, item 5: the conveyor motor current and the belt scale.
    InterlockRow("Conveyor motor current normal", "Trip"),
    InterlockRow("Material flowing on the belt", "Alarm"),
    # Master specification, item 7: Batch mode's own protections.
    InterlockRow("Batch start permissives", "Permissive"),
    InterlockRow("Batch dose flows", "Trip"),
    InterlockRow("Hopper discharges", "Trip"),
    InterlockRow("Batch weighed in within tolerance", "Alarm"),
]


@dataclass
class RowCoverage:
    row: InterlockRow
    scenarios: list[tuple[str, bool]]  # (scenario name, passed) -- the ones that observed something
    unobservable: list[str] = field(default_factory=list)  # scenario names that observed nothing

    @property
    def status(self) -> str:
        if not self.row.applicable:
            return "not_applicable"
        if not self.scenarios:
            return "not_observable" if self.unobservable else "not_covered"
        return "covered" if all(passed for _, passed in self.scenarios) else "covered_but_failing"


@dataclass
class CoverageReport:
    results: list[tuple[Scenario, ScenarioResult]]
    rows: list[RowCoverage]
    unknown_tags: list[str]  # interlock: values matching no known row -- likely a typo

    @property
    def passed_count(self) -> int:
        return sum(1 for _, r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        """Ran, observed, and didn't do what was expected. A scenario that
        couldn't observe anything is neither this nor passed."""
        return sum(1 for _, r in self.results if not r.passed and not r.not_observable)

    @property
    def not_observable_count(self) -> int:
        return sum(1 for _, r in self.results if r.not_observable)

    @property
    def partly_observed_count(self) -> int:
        return sum(1 for _, r in self.results if r.passed and r.not_observed)

    @property
    def verdict(self) -> str:
        """FAIL on any failure or gap; PARTIAL when nothing failed but
        something went unobserved; otherwise PASS."""
        if self.failed_count or self.gap_count:
            return "FAIL"
        if self.not_observable_count or self.partly_observed_count:
            return "PARTIAL"
        return "PASS"

    @property
    def covered_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "covered")

    @property
    def not_applicable_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "not_applicable")

    @property
    def not_observable_row_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "not_observable")

    @property
    def gap_count(self) -> int:
        """Rows that are genuinely missing coverage right now --
        not_covered or covered_but_failing both count; a row whose only
        scenario is failing is not meaningfully "covered.\""""
        return sum(1 for row in self.rows if row.status in ("not_covered", "covered_but_failing"))


    def mode_counts(self) -> list["ModeCount"]:
        """Operating modes validated (docs/CONTROL-LAB.md §6.1): each mode's
        scenarios, by the mode each one runs in."""
        counts = []
        for mode in MODES:
            results = [r for s, r in self.results if scenario_mode(s) == mode]
            counts.append(ModeCount(
                mode,
                run=len(results),
                passed=sum(1 for r in results if r.passed),
                not_observable=sum(1 for r in results if r.not_observable),
            ))
        return counts


MODES = ("Auto", "Manual")


def scenario_mode(scenario: Scenario) -> str:
    """The mode a scenario runs in: Manual when its `given` selects it,
    otherwise Auto (the default mode). A scenario that asks for a mode
    change from Auto -- and is refused -- runs in Auto."""
    return "Manual" if scenario.given.get("line_state") == "manual" else "Auto"


@dataclass(frozen=True)
class ModeCount:
    mode: str
    run: int
    passed: int
    not_observable: int

    @property
    def status(self) -> str:
        """validated / failing / not observable / not run."""
        if self.run == 0:
            return "not run"
        if self.passed + self.not_observable < self.run:
            return "failing"
        if self.passed == 0:
            return "not observable"
        return "validated"


def build_report(results: list[tuple[Scenario, ScenarioResult]]) -> CoverageReport:
    known_names = {row.name for row in INTERLOCKS}
    unknown_tags = sorted(
        {s.interlock for s, _ in results if s.interlock is not None and s.interlock not in known_names}
    )

    rows = [
        RowCoverage(
            row=row,
            scenarios=[(s.name, r.passed) for s, r in results if s.interlock == row.name and not r.not_observable],
            unobservable=[s.name for s, r in results if s.interlock == row.name and r.not_observable],
        )
        for row in INTERLOCKS
    ]

    return CoverageReport(results=results, rows=rows, unknown_tags=unknown_tags)
