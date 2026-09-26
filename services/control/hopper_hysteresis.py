"""On/off feed demand from hopper level, with hysteresis
(docs/CONTROL-LAB.md §6.2, "Hopper level control (RUNNING only)").

Deliberately the simplest thing that could work: a fixed speed, cycled
on and off between a stop point and a lower restart point, rather than
modulating rate. "A PI rate controller comes later" — this is that
"later" not having happened yet, on purpose.

Pure logic, no I/O image or device-control dependency — easy to unit
test in isolation, and reusable if a future rate controller ever wants a
fallback for when tuning is disabled.
"""
from __future__ import annotations


class HopperHysteresis:
    def __init__(self, restart_below_pct: float = 60.0) -> None:
        self.restart_below_pct = restart_below_pct
        self.feed_demand = True  # start out wanting to feed

    def rearm(self) -> None:
        """Back to wanting to feed, called at each Start: a "no feed" left
        over from the last run (it stopped at the high switch) must not
        hold a new run's feed in the dead band between 60 % and LSH-105."""
        self.feed_demand = True

    def evaluate(self, hopper_high: bool, hopper_level_pct: float) -> bool:
        """hopper_high is the LSH-105 switch (the stop point, ~80% per
        docs/CONTROL-LAB.md §5.2's Hopper default). hopper_level_pct is
        computed by the caller from WT-105 and a known hopper capacity —
        there's no discrete switch at the 60% restart point, only LSH-105
        (stop) and LSHH-105 (a separate hard trip, not this class's
        concern). Returns the current feed demand."""
        if hopper_high:
            self.feed_demand = False
        elif hopper_level_pct < self.restart_below_pct:
            self.feed_demand = True
        return self.feed_demand
