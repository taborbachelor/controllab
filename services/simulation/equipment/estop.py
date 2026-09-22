"""Plant-wide emergency stop.

Modeled at the Simulation layer, not Control, because a real E-stop
removes power at the hardware level regardless of what any controller
commands (docs/CONTROL-LAB.md §5.2, tag ES-001). ``Plant.step()`` enforces
this directly on the motors before running any device logic.
"""
from __future__ import annotations


class EStop:
    def __init__(self) -> None:
        self.healthy = True  # ES-001: 1 = healthy (fail-safe polarity)

    def trip(self) -> None:
        self.healthy = False

    def reset(self) -> None:
        self.healthy = True

    @property
    def tripped(self) -> bool:
        return not self.healthy
