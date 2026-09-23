"""Screw feeder: a Motor plus a rate output.

Material only flows if the motor is confirmed RUNNING — matching a real
VFD-driven feeder, where a speed reference does nothing until the drive
actually runs (docs/CONTROL-LAB.md §5.2).

**Jam (fault injection, `jammed`; docs/CONTROL-LAB.md §5.4).** A blocked
discharge: the screw can no longer move material, so flow stops at once,
but the drive holds current limit and keeps reporting RUNNING -- which is
exactly why a jam is dangerous: nothing the motor reports says anything is
wrong. What does notice is the discharge-chute plug switch (LSH-103):
material backs up into the blocked chute while the screw keeps pushing,
and after `plug_detect_s` of running against the jam the switch makes.
It then STAYS made, running or not, until the jam is physically cleared
(`jammed = False`), because the chute stays packed. That persistence is
what lets Control refuse a reset while the jam remains. The backed-up
material is not tracked as a separate mass: while jammed nothing leaves
the bin, so conservation holds without it.
"""
from __future__ import annotations

from services.simulation.equipment.motor import Motor, MotorState


class Feeder:
    def __init__(
        self,
        name: str,
        max_rate_kg_s: float,
        start_delay_s: float = 0.5,
        plug_detect_s: float = 2.0,
    ) -> None:
        self.name = name
        self.max_rate_kg_s = max_rate_kg_s
        self.motor = Motor(name=f"{name}.motor", start_delay_s=start_delay_s)
        self.speed_pct = 0.0  # 0-100, operator/control setpoint (SC-103)
        self.plug_detect_s = plug_detect_s
        # Fault-injection hook, persistent until cleared -- like Motor's.
        self.jammed = False
        self.plugged = False  # the LSH-103 plug switch
        self._pushing_s = 0.0

    @property
    def state(self) -> MotorState:
        return self.motor.state

    def command(self, run: bool, speed_pct: float | None = None) -> None:
        self.motor.command(run)
        if speed_pct is not None:
            self.speed_pct = max(0.0, min(100.0, speed_pct))

    def current_rate_kg_s(self) -> float:
        if not self.motor.running or self.jammed:
            return 0.0
        return self.max_rate_kg_s * (self.speed_pct / 100.0)

    def step(self, dt: float) -> None:
        self.motor.step(dt)
        if not self.jammed:
            self.plugged = False  # cleared jam = cleared chute
            self._pushing_s = 0.0
        elif self.motor.running and not self.plugged:
            # Rounded like every other timer here (float drift, Phase 1).
            self._pushing_s = round(self._pushing_s + dt, 9)
            if self._pushing_s >= self.plug_detect_s:
                self.plugged = True
