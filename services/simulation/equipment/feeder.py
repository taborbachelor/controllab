"""Screw feeder: a Motor plus a rate output.

Material only flows if the motor is confirmed RUNNING — matching a real
VFD-driven feeder, where a speed reference does nothing until the drive
actually runs (docs/CONTROL-LAB.md §5.2).
"""
from __future__ import annotations

from services.simulation.equipment.motor import Motor, MotorState


class Feeder:
    def __init__(
        self,
        name: str,
        max_rate_kg_s: float,
        start_delay_s: float = 0.5,
    ) -> None:
        self.name = name
        self.max_rate_kg_s = max_rate_kg_s
        self.motor = Motor(name=f"{name}.motor", start_delay_s=start_delay_s)
        self.speed_pct = 0.0  # 0-100, operator/control setpoint (SC-103)

    @property
    def state(self) -> MotorState:
        return self.motor.state

    def command(self, run: bool, speed_pct: float | None = None) -> None:
        self.motor.command(run)
        if speed_pct is not None:
            self.speed_pct = max(0.0, min(100.0, speed_pct))

    def current_rate_kg_s(self) -> float:
        if not self.motor.running:
            return 0.0
        return self.max_rate_kg_s * (self.speed_pct / 100.0)

    def step(self, dt: float) -> None:
        self.motor.step(dt)
