"""The review gate for candidate scenarios (docs/CONTROL-LAB.md §10,
Phase 8 step 1).

Phase 8's rule is that AI output is only ever a *proposal in a reviewable
file*, reviewed by an engineer before it becomes a test. This module is
what stands between a proposed scenario file and that engineer: a fixed,
deterministic battery of checks that throws out what's broken and flags
what needs judgment, so the engineer's attention goes where it matters.

It deliberately knows nothing about AI -- a candidate written by a person
gets exactly the same review -- and uses no model, network, or new
dependency. Whatever generates candidates later (Phase 8 step 2) feeds
this gate; it never feeds scenarios/ directly.

Checks, in order (a load or vocabulary error stops the review early,
since nothing after it can run):

  load         the file parses as a scenario (Scenario.load)
  vocabulary   every given/when/expect key is one the runner knows
  line_state   given.line_state is one the runner can reach
  interlock    the tag names a real §6.3 row (or warns it counts toward nothing)
  duplicate    not identical to an existing scenario
  built-in     runs against the built-in controller -- a FAIL is not a
               rejection: it's either a wrong test or a real finding, and
               only an engineer can say which, so it's marked for judgment
  determinism  two runs record identical event logs
  external     the run across Modbus (Phase 7) agrees with the built-in one
  vacuous      with `when` removed it must NOT still pass -- a test whose
               expectations hold without its stimulus proves nothing,
               the classic failure mode of generated tests
  margin       passes with more than one scan to spare (else brittle)

Verdicts: REJECTED (any error), NEEDS JUDGMENT (clean, but fails against
the controller), READY FOR REVIEW (clean and passing). Nothing here ever
moves a file into scenarios/ -- accepting a candidate is the engineer's act.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

from services.testing.report import INTERLOCKS
from services.testing.rig import DT
from services.testing.runner import ScenarioResult, run_scenario
from services.testing.scenario import Scenario, ScenarioLoadError
from services.testing.vocabulary import APPLY_ACTIONS, CONTROLLER_FIELDS, READ_FIELDS

ERROR, WARNING, JUDGMENT, OK = "error", "warning", "judgment", "ok"
LINE_STATES = {"idle", "running"}
REJECTED, NEEDS_JUDGMENT, READY = "REJECTED", "NEEDS JUDGMENT", "READY FOR REVIEW"


@dataclass
class Finding:
    check: str
    level: str
    message: str


@dataclass
class Review:
    path: Path
    scenario: Scenario | None
    findings: list[Finding] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        levels = {f.level for f in self.findings}
        if ERROR in levels:
            return REJECTED
        if JUDGMENT in levels:
            return NEEDS_JUDGMENT
        return READY

    def add(self, check: str, level: str, message: str) -> None:
        self.findings.append(Finding(check, level, message))


def _event_log(result: ScenarioResult) -> list:
    return [(e.t, e.type, e.data) for e in result.events]


def review(path: Path, existing: list[Scenario]) -> Review:
    """Review one candidate file against the current suite `existing`."""
    r = Review(path=path, scenario=None)

    try:
        scenario = Scenario.load(path)
    except ScenarioLoadError as e:
        r.add("load", ERROR, str(e).replace(str(path) + ": ", ""))
        return r
    r.scenario = scenario
    r.add("load", OK, f"parses: {scenario.name!r}, within {scenario.within_s:g} s")

    given = dict(scenario.given)
    line_state = given.pop("line_state", "idle")
    unknown = sorted(
        [f"given.{k}" for k in given if k not in APPLY_ACTIONS]
        + [f"when.{k}" for k in scenario.when if k not in APPLY_ACTIONS]
        + [f"expect.{k}" for k in scenario.expect if k not in READ_FIELDS]
        + [f"then[{n}].when.{k}" for n, st in enumerate(scenario.then, 2) for k in st.when if k not in APPLY_ACTIONS]
        + [f"then[{n}].expect.{k}" for n, st in enumerate(scenario.then, 2) for k in st.expect if k not in READ_FIELDS]
    )
    if unknown:
        r.add("vocabulary", ERROR, f"unknown keys: {', '.join(unknown)}")
        return r
    if not scenario.expect:
        r.add("vocabulary", ERROR, "expect is empty -- the scenario asserts nothing")
        return r
    r.add("vocabulary", OK, "every key is in the scenario vocabulary")
    if line_state not in LINE_STATES:
        r.add("line_state", ERROR, f"given.line_state {line_state!r} isn't reachable (known: {', '.join(sorted(LINE_STATES))})")
        return r

    rows = {row.name for row in INTERLOCKS}
    if scenario.interlock is None:
        r.add("interlock", WARNING, "no interlock tag -- it won't count toward the §6.3 coverage matrix")
    elif scenario.interlock not in rows:
        r.add("interlock", ERROR, f"interlock {scenario.interlock!r} matches no §6.3 row")
    else:
        r.add("interlock", OK, f"covers §6.3 row {scenario.interlock!r}")

    signature = (scenario.given, scenario.when, scenario.expect, scenario.then)
    twins = [s.name for s in existing if (s.given, s.when, s.expect, s.then) == signature]
    if twins:
        r.add("duplicate", WARNING, f"identical given/when/expect to existing scenario {twins[0]!r}")
    else:
        r.add("duplicate", OK, "not a duplicate of an existing scenario")

    try:
        first = run_scenario(scenario)
        second = run_scenario(scenario)
        external = run_scenario(scenario, external=True)
    except ScenarioLoadError as e:
        r.add("built-in", ERROR, f"can't be set up: {e}".replace(str(path) + ": ", ""))
        return r

    if first.passed:
        r.add("built-in", OK, f"passes against the built-in controller in {first.elapsed_s:.2f} s")
    else:
        r.add("built-in", JUDGMENT,
              f"FAILS against the built-in controller -- a wrong test or a real finding: {first.detail}")

    if (first.passed, _event_log(first)) != (second.passed, _event_log(second)):
        r.add("determinism", ERROR, "two runs recorded different event logs")
    else:
        r.add("determinism", OK, "two runs recorded identical event logs")

    if (external.passed, external.elapsed_s, _event_log(external)) != (first.passed, first.elapsed_s, _event_log(first)):
        r.add("external", ERROR, "the run across Modbus disagrees with the built-in run")
    else:
        r.add("external", OK, "the run across Modbus matches the built-in run exactly")

    if first.passed:
        if scenario.when:
            without = run_scenario(dataclasses.replace(scenario, when={}))
            if without.passed:
                r.add("vacuous", ERROR,
                      "still passes with `when` removed -- its expectations hold without the stimulus, so it tests nothing")
            else:
                r.add("vacuous", OK, "fails without its `when` stimulus, so the stimulus is what it tests")
            if scenario.trigger:
                # Stronger than dropping all of `when`: drop exactly the declared
                # trigger, keep any setup that rides along with it.
                rest = {k: v for k, v in scenario.when.items() if k not in scenario.trigger}
                without_trigger = run_scenario(dataclasses.replace(scenario, when=rest, trigger=()))
                names = ", ".join(scenario.trigger)
                if without_trigger.passed:
                    r.add("trigger", ERROR,
                          f"still passes without its declared trigger ({names}) -- the expectations don't depend on it")
                else:
                    r.add("trigger", OK, f"fails without its declared trigger ({names}), so the trigger is what it tests")
        else:
            r.add("vacuous", WARNING, "no `when` -- it checks a steady state, not a response")

        margin = scenario.within_s - first.elapsed_s
        if margin < DT - 1e-9:
            r.add("margin", WARNING, f"passes with only {margin:.2f} s to spare -- brittle to any timing change")
        else:
            r.add("margin", OK, f"{margin:.2f} s of margin under the {scenario.within_s:g} s limit")
        _field_check(r, scenario)
    return r


def _field_check(r: Review, scenario: Scenario) -> None:
    """What the scenario proves from field evidence alone -- against a
    controller that publishes no status block (runner status=False). Not
    an error to prove nothing there (a refused command changes nothing in
    the field), but a partly field-observable scenario must still depend
    on its stimulus in field terms, or a status-less run would pass it
    vacuously."""
    blind = run_scenario(scenario, status=False)
    stages = scenario.stages
    total = sum(len(st.expect) for st in stages)
    field = sum(1 for st in stages for k in st.expect if k not in CONTROLLER_FIELDS)
    if blind.not_observable:
        r.add("field", OK, f"{field}/{total} expectation(s) field-observable; without a status block it is "
                           "not observable (a stage asserts only controller state)")
        return
    if not blind.passed:
        r.add("field", WARNING, f"fails on field evidence alone, though it passes with the status block: {blind.detail}")
        return
    if scenario.when and run_scenario(dataclasses.replace(scenario, when={}), status=False).passed:
        r.add("field", WARNING, "its field-observable expectations hold without the stimulus -- against a controller "
                                "without a status block it would pass vacuously")
    else:
        r.add("field", OK, f"{field}/{total} expectation(s) field-observable, and on field evidence alone it still "
                           "fails without its stimulus")


def render_markdown(reviews: list[Review], root: Path | None = None) -> str:
    """Deterministic, like the commissioning report: no timestamps, and
    paths relative to `root` when given."""
    mark = {OK: "✅", WARNING: "⚠️", JUDGMENT: "🔎", ERROR: "❌"}
    lines = ["# Candidate Scenario Review", ""]
    counts = {v: sum(1 for r in reviews if r.verdict == v) for v in (READY, NEEDS_JUDGMENT, REJECTED)}
    lines += [
        f"{len(reviews)} candidate(s): {counts[READY]} ready for review, {counts[NEEDS_JUDGMENT]} need judgment, "
        f"{counts[REJECTED]} rejected. A candidate only becomes a test when an engineer moves it into `scenarios/`.",
        "",
        "| Verdict | Candidate | File |",
        "|---|---|---|",
    ]

    def rel(p: Path) -> str:
        try:
            return p.resolve().relative_to(root.resolve()).as_posix() if root else p.name
        except ValueError:
            return p.name

    for r in reviews:
        name = r.scenario.name if r.scenario else "(unreadable)"
        lines.append(f"| **{r.verdict}** | {name} | `{rel(r.path)}` |")
    lines.append("")
    for r in reviews:
        name = r.scenario.name if r.scenario else "(unreadable)"
        lines += [f"## {name} — {r.verdict}", "", f"`{rel(r.path)}`", ""]
        lines += [f"- {mark[f.level]} **{f.check}** — {f.message.replace('|', '/')}" for f in r.findings]
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
