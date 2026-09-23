"""Cross-checks the hopper's point level switches against its continuous
weight transmitter (docs/CONTROL-LAB.md §6.3, "Hopper level instruments
agree").

The hopper has two independent level measurements: WT-105 (continuous,
kg) and two point switches, LSH-105 at 80 % and LSHH-105 at 95 %. Each
switch should be open exactly when WT-105 says the level is at or above
its switch point. When they disagree, one of them is wrong, and nothing in
either signal alone says which: a seized float or a welded contact reads
"healthy" forever (fail-safe polarity can't catch that, only a broken
wire), and a stuck transmitter reads a plausible number.

A disagreement is judged with two allowances, both stated rather than
tuned to a scenario:

- **Deadband** (`deadband_pct`, default 2 % of span, 40 kg on this
  hopper): a switch's actual trip point and a transmitter's reading each
  carry installation and calibration tolerance, so only a gap wider than
  that counts.
- **Delay** (`delay_s`, default 1.0 s): the two instruments respond at
  different speeds while the level moves through the switch point, so a
  disagreement must persist before it's reported.

While WT-105's channel has failed, nothing is judged: the comparison needs
a trustworthy weight, and WT-105.FAIL already reports that.

Stateful (the delay) and pure (no I/O image): the caller supplies the
readings each scan, the same shape as HopperHysteresis.
"""
from __future__ import annotations


class LevelSwitchCheck:
    def __init__(self, switch_pct: float, deadband_pct: float = 2.0, delay_s: float = 1.0) -> None:
        self.switch_pct = switch_pct
        self.deadband_pct = deadband_pct
        self.delay_s = delay_s
        self._elapsed_s = 0.0
        self.disagree = False

    def scan(self, switch_open: bool, level_pct: float, transmitter_failed: bool, dt: float) -> None:
        """`switch_open`: the switch says the level is at or above its point
        (already corrected for fail-safe polarity)."""
        if transmitter_failed:
            mismatch = False
        elif switch_open:
            mismatch = level_pct < self.switch_pct - self.deadband_pct
        else:
            mismatch = level_pct >= self.switch_pct + self.deadband_pct
        self._elapsed_s = round(self._elapsed_s + dt, 9) if mismatch else 0.0
        self.disagree = self._elapsed_s >= self.delay_s


class HopperLevelChecks:
    """Both hopper switches' cross-checks, scanned together once a tick
    (LineController.scan, before the alarm scan reads them)."""

    def __init__(
        self,
        high_pct: float = 80.0,
        high_high_pct: float = 95.0,
        deadband_pct: float = 2.0,
        delay_s: float = 1.0,
    ) -> None:
        self.lsh = LevelSwitchCheck(high_pct, deadband_pct, delay_s)
        self.lshh = LevelSwitchCheck(high_high_pct, deadband_pct, delay_s)

    def scan(self, interlocks, dt: float) -> None:
        level = interlocks.hopper_level_pct
        failed = interlocks.hopper_weight_failed
        self.lsh.scan(interlocks.hopper_high, level, failed, dt)
        self.lshh.scan(interlocks.hopper_high_high_switch, level, failed, dt)
