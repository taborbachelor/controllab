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
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class ScenarioLoadError(Exception):
    """A malformed scenario file: missing a required key, invalid YAML,
    or a value of the wrong shape. Raised at load time, not partway
    through a run."""


@dataclass
class Scenario:
    name: str
    path: Path
    given: dict
    when: dict
    expect: dict
    within_s: float
    interlock: str | None = None

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

        within = raw["within"]
        if not isinstance(within, dict):
            raise ScenarioLoadError(f"{path}: within must be a mapping (seconds: ... or milliseconds: ...)")
        if "seconds" in within:
            within_s = float(within["seconds"])
        elif "milliseconds" in within:
            within_s = float(within["milliseconds"]) / 1000.0
        else:
            raise ScenarioLoadError(f"{path}: within must specify seconds or milliseconds")

        return cls(
            name=raw["name"],
            path=path,
            given=raw.get("given") or {},
            when=raw.get("when") or {},
            expect=raw["expect"],
            within_s=within_s,
            interlock=raw.get("interlock"),
        )

    @staticmethod
    def discover(root: Path) -> list["Scenario"]:
        """Every *.yaml file under root, sorted for a stable, repeatable
        run order (docs/CONTROL-LAB.md §7, item 3: deterministic)."""
        return [Scenario.load(p) for p in sorted(root.rglob("*.yaml"))]
