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
  unknown" (WT-105 = 0, diagnostic set). A plain switch can fail too
  (a broken wire, a dead switch): it reads 0 and, having no diagnostic,
  says nothing else. What 0 *means* is then the switch's wiring polarity:
  on a fail-safe switch (ES-001, LSH-105, LSHH-105: 1 = healthy) a failure
  reads as the tripped state, which is the point of wiring it that way;
  on any other switch it reads as "all clear". An analog input without a
  diagnostic can't fail in a way this model distinguishes from stuck, so
  `fail()` refuses it.

Three more ways an instrument degrades without failing (the master
specification's "noisy analog signals, sensor drift/out-of-calibration,
high response latency"). None of them sets a diagnostic: to the
controller each is a plausible reading, which is what makes them worth
testing.

- **Noisy** (`add_noise(tag, amplitude)`): an analog reading carries
  noise, uniform within +/- `amplitude` engineering units. Reproducible:
  each instrument draws from its own random stream, seeded from the
  plant's seed and the tag name, so a scenario gives the same readings
  every run.
- **Drifting** (`drift(tag, rate_per_s)`): an analog reading's offset grows
  by `rate_per_s` every simulated second from the moment it starts (an
  out-of-calibration transmitter walking away from the truth).
- **Slow** (`lag(tag, seconds)`): the instrument reports what was true
  `seconds` ago (dead time): a sluggish switch, a transmitter behind a long
  impulse line. Any input can lag.

An analog reading is clamped to its instrument's calibrated range
(`ranges`), as a real 4-20 mA loop saturates at either end: a drifting
transmitter pins at full scale instead of reading 120 %. One fault per
instrument at a time; injecting another replaces it.

`restore(tag)` returns the instrument to health (a field repair). The
state is held by the Plant, like every other injected fault (§5.4:
Simulation's hooks), and applied by services/simulation/engine/plant_io.py
as it publishes, so Plant's own physics never see a sensor fault -- only
what's reported does.
"""
from __future__ import annotations

import math
import random
from collections import deque
from enum import Enum, auto


class InstrumentFault(Enum):
    HEALTHY = auto()
    STUCK = auto()
    FAILED = auto()
    NOISY = auto()
    DRIFTING = auto()
    SLOW = auto()


class Instruments:
    def __init__(
        self,
        diagnosed: set[str] | frozenset[str] = frozenset(),
        ranges: dict[str, tuple[float, float]] | None = None,
        seed: int = 0,
    ) -> None:
        """`diagnosed`: the analog instruments whose input channel has a
        fault diagnostic (and so can report FAILED). `ranges`: each analog
        instrument's calibrated range, which its reading never leaves.
        `seed`: the root of every noise stream."""
        self.diagnosed = frozenset(diagnosed)
        self.ranges = dict(ranges or {})
        self.seed = seed
        # Simulated time, set by the Plant each step: drift and dead time run on it.
        self.now = 0.0
        self._faults: dict[str, InstrumentFault] = {}
        self._last: dict[str, object] = {}
        self._frozen: dict[str, object] = {}
        self._noise: dict[str, tuple[float, random.Random]] = {}
        self._drift: dict[str, tuple[float, float]] = {}  # tag -> (rate per s, start time)
        self._lag: dict[str, tuple[float, deque]] = {}  # tag -> (seconds, (time, true value) history)

    def fault(self, tag: str) -> InstrumentFault:
        return self._faults.get(tag, InstrumentFault.HEALTHY)

    def stick(self, tag: str) -> None:
        self._require_known(tag)
        self._faults[tag] = InstrumentFault.STUCK
        self._frozen[tag] = self._last[tag]  # the last value it reported

    def fail(self, tag: str) -> None:
        """Signal lost: an analog input with a channel diagnostic reads
        bottom of range with the diagnostic set; a switch reads 0 (open
        circuit), with nothing to say it's a failure."""
        self._require_known(tag)
        if tag not in self.diagnosed and not isinstance(self._last[tag], bool):
            raise ValueError(
                f"{tag} is an analog input with no channel diagnostic, so a failure can't be told from a "
                "stuck reading (use stick)"
            )
        self._faults[tag] = InstrumentFault.FAILED

    def add_noise(self, tag: str, amplitude: float) -> None:
        self._require_analog(tag, "noise")
        if not amplitude > 0:
            raise ValueError(f"noise amplitude must be positive, got {amplitude!r}")
        self._clear(tag)
        self._faults[tag] = InstrumentFault.NOISY
        self._noise[tag] = (float(amplitude), random.Random(f"{self.seed}:{tag}"))

    def drift(self, tag: str, rate_per_s: float) -> None:
        self._require_analog(tag, "drift")
        if rate_per_s == 0:
            raise ValueError("a drift rate of 0 is no drift")
        self._clear(tag)
        self._faults[tag] = InstrumentFault.DRIFTING
        self._drift[tag] = (float(rate_per_s), self.now)

    def lag(self, tag: str, seconds: float) -> None:
        self._require_known(tag)
        if not seconds > 0:
            raise ValueError(f"a lag must be positive, got {seconds!r}")
        self._clear(tag)
        self._faults[tag] = InstrumentFault.SLOW
        # Until `seconds` have passed it keeps reporting what it last reported.
        self._lag[tag] = (float(seconds), deque([(-math.inf, self._last[tag])]))

    def restore(self, tag: str) -> None:
        self._require_known(tag)
        self._clear(tag)

    def _clear(self, tag: str) -> None:
        self._faults.pop(tag, None)
        self._frozen.pop(tag, None)
        self._noise.pop(tag, None)
        self._drift.pop(tag, None)
        self._lag.pop(tag, None)

    def report(self, tag: str, true_value):
        """What the instrument puts on the wire, given the process's true value."""
        fault = self.fault(tag)
        if fault is InstrumentFault.STUCK:
            value = self._frozen[tag]
        elif fault is InstrumentFault.FAILED:
            # A switch's open circuit reads 0; an analog signal under range is
            # clamped to the bottom of the card's range.
            value = False if isinstance(true_value, bool) else 0.0
        elif fault is InstrumentFault.NOISY:
            amplitude, rng = self._noise[tag]
            value = self._clamp(tag, true_value + rng.uniform(-amplitude, amplitude))
        elif fault is InstrumentFault.DRIFTING:
            rate, start = self._drift[tag]
            value = self._clamp(tag, true_value + rate * (self.now - start))
        elif fault is InstrumentFault.SLOW:
            seconds, history = self._lag[tag]
            history.append((self.now, true_value))
            cutoff = self.now - seconds + 1e-9
            while len(history) > 1 and history[1][0] <= cutoff:
                history.popleft()
            value = history[0][1]
        else:
            value = true_value
        self._last[tag] = value
        return value

    def _clamp(self, tag: str, value: float) -> float:
        lo, hi = self.ranges.get(tag, (-math.inf, math.inf))
        return min(max(value, lo), hi)

    def channel_fault(self, tag: str) -> bool:
        """The input card's diagnostic for `tag`: set only while FAILED, and
        only on a channel that has one (a switch's open circuit raises none)."""
        return tag in self.diagnosed and self.fault(tag) is InstrumentFault.FAILED

    def _require_known(self, tag: str) -> None:
        if tag not in self._last:
            raise ValueError(f"{tag} is not an instrument this plant reports")

    def _require_analog(self, tag: str, what: str) -> None:
        self._require_known(tag)
        if isinstance(self._last[tag], bool):
            raise ValueError(f"{tag} is a switch: {what} applies to an analog reading")
