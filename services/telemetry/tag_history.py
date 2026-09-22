"""Sampled tag history: a snapshot of every IOImage tag's value each time
record() is called -- the "CSV tag history" half of docs/CONTROL-LAB.md
§3.4 and §10's Phase 5 entry (the other half, the JSONL event log, is a
separate module -- this one doesn't need or want to know about it).

Deliberately generic and reusable, the same way IOImage itself is
(services/simulation/engine/io_image.py): this only ever calls IOImage's
existing public interface (names(), read()) -- no Plant, no
LineController, no line-specific tag name hardcoded anywhere. It would
work identically against any IOImage, for any plant.

Pull, not push: nothing in Simulation or Control calls into this.
Something outside -- a test, a scenario runner, a future
telemetry-enabled driver -- calls record() once per tick, the same tick
boundary services/testing/rig.py's tick() already uses. This is
deliberate (the Phase 5 architecture decision): it keeps every line of
Phase 2-4's already-tested Control code untouched, exactly the same
black-box observation Testing already relies on (services/testing/
vocabulary.py's READ_FIELDS never reaches into LineController's
internals either).

record() takes its timestamp from the caller rather than tracking time
itself, so this class stays ignorant of SimClock/dt the same way IOImage
itself is ignorant of simulated time -- whatever is driving the tick
loop already has that number.

File output is a separate concern: TagHistory only ever collects in
memory. write_csv() is a standalone function, not a method, so the
recorder itself never needs to import csv or pathlib -- the same split
services/testing/report.py (pure logic) and scripts/scenario_report.py
(the thing that actually writes a file) already establish. Normal
pytest runs never call write_csv(); nothing here writes a file as a
side effect of anything else.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from services.simulation.engine.io_image import IOImage, TagValue


@dataclass
class TagSample:
    t: float
    values: dict[str, TagValue]


class TagHistory:
    def __init__(self, io: IOImage) -> None:
        self.io = io
        self.samples: list[TagSample] = []

    def record(self, t: float) -> None:
        """Snapshots every currently-defined tag's value. Safe to call
        every tick, or at whatever cadence a caller wants -- this class
        has no opinion on sampling rate."""
        values = {name: self.io.read(name) for name in self.io.names()}
        self.samples.append(TagSample(t=t, values=values))

    @property
    def tag_names(self) -> list[str]:
        """The column set for a CSV export: every tag name that has
        appeared in ANY recorded sample, not just IOImage's tag list at
        export time -- so a tag defined after recording started still
        gets a column instead of write_csv() needing a live IOImage
        reference at all. Sorted for a stable, deterministic column
        order (docs/CONTROL-LAB.md §7, item 3)."""
        names: set[str] = set()
        for sample in self.samples:
            names.update(sample.values.keys())
        return sorted(names)


def write_csv(history: TagHistory, path: Path) -> None:
    """Serializes a TagHistory to a CSV file: one row per sample, one
    column per tag (plus a leading `t` column). A sample missing a
    column present in a later one (a tag defined partway through
    recording) gets a blank cell, not a crash. This file is meant to be
    read, not parsed back in (docs/CONTROL-LAB.md §8: "every artifact is
    inspectable... plain text a human can read")."""
    columns = history.tag_names
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["t", *columns])
        for sample in history.samples:
            writer.writerow([sample.t, *(sample.values.get(name, "") for name in columns)])
