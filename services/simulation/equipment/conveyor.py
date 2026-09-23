"""Belt conveyor: a Motor plus a transport-delay material queue.

Material entering the belt takes transit_time_s to reach the discharge
end — modeled as a FIFO queue of (arrival_time, mass) parcels rather than
a continuous field, which is all the commissioning-relevant behavior needs
(docs/CONTROL-LAB.md §10, "Determinism over realism").

The queue's clock is the belt's own travel, not plant time: it advances
only while the belt is actually moving (motion_confirmed), so a stopped or
slipping belt holds its load where it is. (It first advanced with plant
time, so a stopped belt kept delivering into the hopper; that hid whether
a stop sequence purged the belt at all -- a controller that skipped the
purge passed every scenario. Found in the logic review, 2026-09-23.)
"""
from __future__ import annotations

from collections import deque

from services.simulation.equipment.motor import Motor, MotorState


class Conveyor:
    def __init__(
        self,
        name: str,
        length_m: float,
        speed_m_s: float,
        start_delay_s: float = 1.0,
    ) -> None:
        self.name = name
        self.length_m = length_m
        self.speed_m_s = speed_m_s
        self.transit_time_s = length_m / speed_m_s
        self.motor = Motor(name=f"{name}.motor", start_delay_s=start_delay_s)
        self._belt: deque[tuple[float, float]] = deque()  # (arrival at belt travel time, mass_kg)
        self._time_s = 0.0  # belt travel time: advances only while the belt moves

        # Fault injection: motion switch (ZSS-104) never confirms, even
        # while the motor is genuinely running — belt slip / broken belt.
        self.motion_switch_stuck_false = False

    @property
    def state(self) -> MotorState:
        return self.motor.state

    @property
    def motion_confirmed(self) -> bool:
        """ZSS-104 equivalent: true only while material can actually move."""
        if self.motion_switch_stuck_false:
            return False
        return self.motor.running

    def command(self, run: bool) -> None:
        self.motor.command(run)

    def load(self, mass_kg: float) -> float:
        """Material fed onto the belt. Returns the mass SPILLED (not
        accepted) — non-zero whenever the belt isn't confirmed moving."""
        if mass_kg <= 0:
            return 0.0
        if not self.motion_confirmed:
            return mass_kg  # spilled: fed onto a stopped/slipping belt
        self._belt.append((self._time_s + self.transit_time_s, mass_kg))
        return 0.0

    def step(self, dt: float) -> float:
        """Advances the belt. Returns the mass delivered off the
        discharge end this tick (0.0 if nothing has arrived yet)."""
        self.motor.step(dt)
        if not self.motion_confirmed:
            return 0.0  # a stopped or slipping belt carries nothing anywhere
        self._time_s += dt
        delivered = 0.0
        while self._belt and self._belt[0][0] <= self._time_s + 1e-9:
            _, mass = self._belt.popleft()
            delivered += mass
        return delivered

    @property
    def mass_on_belt_kg(self) -> float:
        return sum(mass for _, mass in self._belt)
