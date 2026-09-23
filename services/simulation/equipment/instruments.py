"""Field-instrument faults (docs/CONTROL-LAB.md §5.4, "Sensor failure"):
the layer between what the plant is actually doing and what its
transmitters and switches report.

Until now every input was published straight from plant state, so a
sensor could only ever be right. A real instrument can be wrong in two
distinct ways, and a controller can tell them apart only in one:

- **Stuck** (`stick(tag)`): the instrument keeps reporting its last value
  while the process moves on -- a frozen transmitter, a seized float
  switch, a welded contact. It reports nothing about itself, so it is
  indistinguishable from a real reading; nothing in the I/O says it's
  wrong. Any input can stick.
- **Failed** (`fail(tag)`): the signal is gone -- a broken wire or a dead
  transmitter. On a 4-20 mA loop the current drops below range, the
  analog input card clamps the value to the bottom of its range (0.0 here,
  the same 0 a Modbus register would carry) and raises its channel
  diagnostic. That diagnostic is published as its own discrete input
  (`<tag>.FLT`), because it's the ONLY thing separating "the hopper is
  empty" (WT-105 = 0, diagnostic clear) from "the hopper weight is
  unknown" (WT-105 = 0, diagnostic set). Only instruments with such a
  channel can fail this way; a plain switch has no diagnostic, so its
  broken wire is simply "stuck at 0", and `fail()` refuses it and says so.

`restore(tag)` returns the instrument to health (a field repair). The
state is held by the Plant, like every other injected fault (§5.4:
Simulation's hooks), and applied by services/simulation/engine/plant_io.py
as it publishes, so Plant's own physics never see a sensor fault -- only
what's reported does.
"""
from __future__ import annotations

from enum import Enum, auto


class InstrumentFault(Enum):
    HEALTHY = auto()
    STUCK = auto()
    FAILED = auto()


class Instruments:
    def __init__(self, diagnosed: set[str] | frozenset[str] = frozenset()) -> None:
        """`diagnosed`: the analog instruments whose input channel has a
        fault diagnostic (and so can report FAILED)."""
        self.diagnosed = frozenset(diagnosed)
        self._faults: dict[str, InstrumentFault] = {}
        self._last: dict[str, object] = {}
        self._frozen: dict[str, object] = {}

    def fault(self, tag: str) -> InstrumentFault:
        return self._faults.get(tag, InstrumentFault.HEALTHY)

    def stick(self, tag: str) -> None:
        self._require_known(tag)
        self._faults[tag] = InstrumentFault.STUCK
        self._frozen[tag] = self._last[tag]  # the last value it reported

    def fail(self, tag: str) -> None:
        if tag not in self.diagnosed:
            raise ValueError(
                f"{tag} has no channel diagnostic, so it can't report a failure -- a broken switch just reads "
                "stuck (use stick)"
            )
        self._faults[tag] = InstrumentFault.FAILED

    def restore(self, tag: str) -> None:
        self._require_known(tag)
        self._faults.pop(tag, None)
        self._frozen.pop(tag, None)

    def report(self, tag: str, true_value):
        """What the instrument puts on the wire, given the process's true value."""
        fault = self.fault(tag)
        if fault is InstrumentFault.STUCK:
            value = self._frozen[tag]
        elif fault is InstrumentFault.FAILED:
            value = 0.0  # under-range, clamped to the bottom of the card's range
        else:
            value = true_value
        self._last[tag] = value
        return value

    def channel_fault(self, tag: str) -> bool:
        """The input card's diagnostic for `tag`: set only while FAILED."""
        return self.fault(tag) is InstrumentFault.FAILED

    def _require_known(self, tag: str) -> None:
        if tag not in self._last:
            raise ValueError(f"{tag} is not an instrument this plant reports")
