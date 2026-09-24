"""Passive material vessels: MaterialBin (source) and Hopper (surge/sink).

These are deliberately *not* state machines (docs/CONTROL-LAB.md §9): a
vessel's only behavior is its level, so giving it STARTING/STOPPING states
would be state for its own sake. Level thresholds are exposed as plain
properties, matching the discrete switches (LSL-101, LSH-105, LSHH-105)
they represent in the I/O list (docs/CONTROL-LAB.md §5.3).
"""
from __future__ import annotations


class MaterialBin:
    def __init__(
        self,
        name: str,
        capacity_kg: float,
        level_kg: float | None = None,
        low_pct: float = 10.0,
    ) -> None:
        self.name = name
        self.capacity_kg = capacity_kg
        self.level_kg = capacity_kg if level_kg is None else level_kg
        self.low_pct = low_pct
        # Fault injection: the material bridges (arches) over the outlet, so
        # nothing discharges though the bin is full -- the classic bulk-solids
        # flow failure. The level instruments can't see it: the level is real.
        self.bridged = False

    @property
    def level_pct(self) -> float:
        return 100.0 * self.level_kg / self.capacity_kg

    @property
    def low(self) -> bool:
        return self.level_pct <= self.low_pct

    @property
    def empty(self) -> bool:
        return self.level_kg <= 0.0

    def discharge(self, requested_kg: float) -> float:
        """Remove up to requested_kg. Returns the amount actually removed
        (less than requested once the bin runs low)."""
        if self.bridged:
            return 0.0
        available = max(0.0, self.level_kg)
        actual = min(requested_kg, available)
        self.level_kg -= actual
        return actual


class Hopper:
    def __init__(
        self,
        name: str,
        capacity_kg: float,
        level_kg: float = 0.0,
        draw_rate_kg_s: float = 0.0,
        high_pct: float = 80.0,
        high_high_pct: float = 95.0,
    ) -> None:
        self.name = name
        self.capacity_kg = capacity_kg
        self.level_kg = level_kg
        self.draw_rate_kg_s = draw_rate_kg_s
        self.high_pct = high_pct
        self.high_high_pct = high_high_pct
        self.total_discharged_kg = 0.0

    @property
    def level_pct(self) -> float:
        return 100.0 * self.level_kg / self.capacity_kg

    @property
    def high(self) -> bool:
        return self.level_pct >= self.high_pct

    @property
    def high_high(self) -> bool:
        return self.level_pct >= self.high_high_pct

    @property
    def free_capacity_kg(self) -> float:
        return max(0.0, self.capacity_kg - self.level_kg)

    def receive(self, offered_kg: float) -> float:
        """Accept up to offered_kg. Returns the amount NOT accepted
        (spilled) — non-zero once the hopper is full."""
        accepted = min(offered_kg, self.free_capacity_kg)
        self.level_kg += accepted
        return offered_kg - accepted

    def step(self, dt: float) -> None:
        draw = min(self.draw_rate_kg_s * dt, self.level_kg)
        self.level_kg -= draw
        self.total_discharged_kg += draw
