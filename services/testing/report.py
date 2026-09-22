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

Pure logic, no I/O — `scripts/scenario_report.py` is the thin CLI that
runs the scenarios and prints this.
"""
from __future__ import annotations

from dataclasses import dataclass

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
        applicable=False,
        note="no alarm system exists yet -- Phase 4",
    ),
    InterlockRow("Hopper not high-high", "Permissive"),
    InterlockRow(
        "Bin not low",
        "Permissive",
        note='the "warning only while running" half has no mechanism yet -- '
        "no alarm/notification system exists before Phase 4/5",
    ),
    InterlockRow(
        "Conveyor proven running",
        "Permissive + trip for feeder",
        note="the permissive half (feeder cannot run onto a stopped belt) is proven "
        "structurally, not by a declarative scenario -- LineController's public API "
        "has no way to even attempt the wrong order; see tests/integration/"
        "test_line_controller.py::test_wrong_order_spillage_is_structurally_"
        "unreachable_through_control",
    ),
    InterlockRow("Hopper high-high", "Trip"),
    InterlockRow("Any motor fail-to-start / trip", "Trip"),
    InterlockRow("Gate travel timeout", "Trip"),
]


@dataclass
class RowCoverage:
    row: InterlockRow
    scenarios: list[tuple[str, bool]]  # (scenario name, passed)

    @property
    def status(self) -> str:
        if not self.row.applicable:
            return "not_applicable"
        if not self.scenarios:
            return "not_covered"
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
    def covered_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "covered")

    @property
    def not_applicable_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "not_applicable")

    @property
    def gap_count(self) -> int:
        """Rows that are genuinely missing coverage right now --
        not_covered or covered_but_failing both count; a row whose only
        scenario is failing is not meaningfully "covered.\""""
        return sum(1 for row in self.rows if row.status in ("not_covered", "covered_but_failing"))


def build_report(results: list[tuple[Scenario, ScenarioResult]]) -> CoverageReport:
    known_names = {row.name for row in INTERLOCKS}
    unknown_tags = sorted(
        {s.interlock for s, _ in results if s.interlock is not None and s.interlock not in known_names}
    )

    rows = [
        RowCoverage(
            row=row,
            scenarios=[(s.name, r.passed) for s, r in results if s.interlock == row.name],
        )
        for row in INTERLOCKS
    ]

    return CoverageReport(results=results, rows=rows, unknown_tags=unknown_tags)
