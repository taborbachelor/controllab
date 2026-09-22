"""Simulated time source for the plant.

All simulation and control logic advances in fixed steps of simulated time.
Nothing in this project reads the wall clock — that's what makes scenarios
deterministic and reproducible (docs/CONTROL-LAB.md §3.3, §7).
"""
from __future__ import annotations


class SimClock:
    """Fixed-step simulated clock.

    ``time_s`` advances by exactly ``dt_s`` each call to :meth:`tick`.
    There is no relationship to wall-clock time — a test that "runs" ten
    simulated minutes takes however long the Python code takes to execute,
    not ten minutes.
    """

    def __init__(self, dt_s: float = 0.1) -> None:
        if dt_s <= 0:
            raise ValueError("dt_s must be positive")
        self.dt_s = dt_s
        self.tick_count = 0
        self.time_s = 0.0

    def tick(self) -> float:
        """Advance one scan cycle. Returns the new simulated time.

        Computed as ``tick_count * dt_s`` rather than accumulated by
        repeated addition, to avoid floating-point drift over long runs.
        """
        self.tick_count += 1
        self.time_s = round(self.tick_count * self.dt_s, 9)
        return self.time_s

    def reset(self) -> None:
        self.tick_count = 0
        self.time_s = 0.0
