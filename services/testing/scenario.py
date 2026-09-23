"""Loads a declarative commissioning scenario from YAML
(CLAUDE.md §10's `given`/`when`/`expect`/`within` shape) into a Scenario
object the runner can execute.

    name: Conveyor Emergency Stop
    given:
        line_state: running
    when:
        estop: tripped
    expect:
        line_state: estopped
        conveyor_running: false
        feeder_running: false
    within:
        seconds: 0.5

`given` and `when` are optional (an empty scenario starts from IDLE and
applies no stimulus); `name`, `expect`, and `within` are required. An
optional `interlock:` field names which row of docs/CONTROL-LAB.md §6.3
this scenario covers, for the coverage report.

**Multi-stage (`then:`, Phase 4 completion).** A fault's lifecycle --
trip, reset refused while the cause remains, clear the cause, reset,
restart -- is a sequence of operator actions, each taken only after the
previous result was seen. `then:` is an optional list of further stages,
each its own `when`/`expect`/`within`, run in order: a stage's `when` is
applied the tick after the previous stage's expectations were all met,
the way an operator acts on what the HMI shows. The scenario passes only
if every stage does. The first stage is the top-level when/expect/within,
so a single-stage scenario is exactly what it always was.

    then:
      - when: {acknowledge: true, reset: true}
        expect: {line_state: faulted, any_unacknowledged_trip: false}
        within: {seconds: 1.0}

**`trigger:` (optional)** names the `when` key(s) that ARE the stimulus
under test, as opposed to setup riding along with it (e.g. a level preset
in the same `when`). The review gate then proves the scenario fails with
exactly those keys removed -- the causality check a generated scenario
most needs, since a model can put the requested action in `when` without
the expectations depending on it. AI-generated candidates must declare it.

A stage that claims something is *refused* ("reset while the jam
remains") must expect something only the command's evaluation can
produce, or it passes before the command is even processed: in the
example, `any_unacknowledged_trip: false` can only hold after the scan
that consumed the acknowledge -- the same scan that evaluated the reset.

**`title:` and `description:` (optional)** are for people, not the runner:
`description` is one line saying what the scenario proves, and `title`
names a stage's purpose ("Reset is refused while the chute is still
plugged") -- top level for the first stage, inside a `then:` entry for the
others. Run summaries (services/testing/verdict.py) print them next to the
checks; pass or fail still comes only from the checks.

**`given` is preconditions, `when` is the triggering stimulus — this
distinction is load-bearing, not stylistic.** The runner (runner.py)
settles `given` (runner.SETTLE_TICKS: published through the I/O image
and then scanned by Control) before `when` is ever applied; `when`'s effects get no such
grace before the polling loop begins checking `expect`. A field like
`hopper_level_pct` used to model "the hopper is already high before the
operator does anything" belongs in `given`; used to model "the level
changes and that change is what's being reacted to," it belongs in
`when`. Getting this backwards doesn't error — it produces a scenario
that's checking a stale reading for its first tick, which usually shows
up as either a spurious `expect` mismatch or (if the line was mid-start)
an unexpected fault, not an obvious "you did this wrong" message.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class ScenarioLoadError(Exception):
    """A malformed scenario file: missing a required key, invalid YAML,
    or a value of the wrong shape. Raised at load time, not partway
    through a run."""


class GivenUnreachable(ScenarioLoadError):
    """`given.line_state` was never reached. Against the built-in
    controller that means the rig or the scenario is wrong, so it stays a
    ScenarioLoadError; the real-time runner (Phase 9) catches it, because
    against someone else's controller "never reached RUNNING" is a
    finding about that controller."""


@dataclass(frozen=True)
class Stage:
    when: dict
    expect: dict
    within_s: float
    title: str = ""


@dataclass
class Scenario:
    name: str
    path: Path
    given: dict
    when: dict
    expect: dict
    within_s: float
    interlock: str | None = None
    then: tuple[Stage, ...] = ()
    trigger: tuple[str, ...] = ()
    description: str = ""
    title: str = ""  # the first stage's title

    @property
    def stages(self) -> list[Stage]:
        """Every stage in order: the top-level when/expect/within first."""
        return [Stage(self.when, self.expect, self.within_s, self.title), *self.then]

    @classmethod
    def load(cls, path: Path) -> "Scenario":
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise ScenarioLoadError(f"{path}: invalid YAML: {e}") from e

        if not isinstance(raw, dict):
            raise ScenarioLoadError(f"{path}: top level must be a mapping")

        missing = [k for k in ("name", "expect", "within") if k not in raw]
        if missing:
            raise ScenarioLoadError(f"{path}: missing required key(s): {', '.join(missing)}")

        within_s = _within_s(raw["within"], path)
        then = raw.get("then") or []
        if not isinstance(then, list):
            raise ScenarioLoadError(f"{path}: then must be a list of stages")
        stages = []
        for n, stage in enumerate(then, start=2):
            if not isinstance(stage, dict) or set(stage) - {"when", "expect", "within", "title"}                     or not {"expect", "within"} <= set(stage):
                raise ScenarioLoadError(
                    f"{path}: stage {n} must have expect and within, optionally when and title, and nothing else")
            if not isinstance(stage["expect"], dict) or not stage["expect"]:
                raise ScenarioLoadError(f"{path}: stage {n} must expect something")
            stages.append(Stage(stage.get("when") or {}, stage["expect"], _within_s(stage["within"], f"{path}: stage {n}"),
                                str(stage.get("title") or "")))

        trigger = raw.get("trigger") or []
        if isinstance(trigger, str):
            trigger = [trigger]
        when = raw.get("when") or {}
        if not isinstance(trigger, list) or any(k not in when for k in trigger):
            raise ScenarioLoadError(f"{path}: trigger must list keys of `when` (the stimulus under test)")

        return cls(
            name=raw["name"],
            path=path,
            given=raw.get("given") or {},
            when=raw.get("when") or {},
            expect=raw["expect"],
            within_s=within_s,
            interlock=raw.get("interlock"),
            then=tuple(stages),
            trigger=tuple(trigger),
            description=str(raw.get("description") or ""),
            title=str(raw.get("title") or ""),
        )

    @staticmethod
    def discover(root: Path) -> list["Scenario"]:
        """Every *.yaml file under root, sorted for a stable, repeatable
        run order (docs/CONTROL-LAB.md §7, item 3: deterministic)."""
        return [Scenario.load(p) for p in sorted(root.rglob("*.yaml"))]


def _within_s(within: object, where: object) -> float:
    if not isinstance(within, dict):
        raise ScenarioLoadError(f"{where}: within must be a mapping (seconds: ... or milliseconds: ...)")
    if "seconds" in within:
        return float(within["seconds"])
    if "milliseconds" in within:
        return float(within["milliseconds"]) / 1000.0
    raise ScenarioLoadError(f"{where}: within must specify seconds or milliseconds")
