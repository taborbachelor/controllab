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

# Motor current as a multiple of full-load current (FLA), by condition.
INRUSH_X = 6.0  # while starting across the line
NO_LOAD_X = 0.45  # running, empty belt
FULL_BELT_EXTRA_X = 0.4  # added at the belt's rated load
SLIP_X = 0.3  # running with the belt slipping or broken: the motor turns unloaded
JAM_X = 2.5  # running against a jammed belt


class Conveyor:
    def __init__(
        self,
        name: str,
        length_m: float,
        speed_m_s: float,
        start_delay_s: float = 1.0,
        full_load_a: float = 12.0,
        rated_load_kg: float = 50.0,
        jam_overload_s: float = 5.0,
    ) -> None:
        self.name = name
        self.full_load_a = full_load_a
        self.rated_load_kg = rated_load_kg  # material on the belt at its rated feed
        self.jam_overload_s = jam_overload_s  # the overload relay's trip time at jam current
        self.length_m = length_m
        self.speed_m_s = speed_m_s
        self.transit_time_s = length_m / speed_m_s
        self.motor = Motor(name=f"{name}.motor", start_delay_s=start_delay_s)
        self._belt: deque[tuple[float, float]] = deque()  # (arrival at belt travel time, mass_kg)
        self._time_s = 0.0  # belt travel time: advances only while the belt moves

        # Fault injection: motion switch (ZSS-104) never confirms, even
        # while the motor is genuinely running — belt slip / broken belt.
        self.motion_switch_stuck_false = False
        # Fault injection: the belt jams (a blocked chute, a seized pulley).
        # The belt stops and holds its load; the motor keeps turning against
        # it at jam current until its thermal overload trips.
        self.jammed = False
        self._jam_s = 0.0

    @property
    def state(self) -> MotorState:
        return self.motor.state

    @property
    def motion_confirmed(self) -> bool:
        """ZSS-104 equivalent: true only while material can actually move."""
        if self.motion_switch_stuck_false or self.jammed:
            return False
        return self.motor.running

    @property
    def current_a(self) -> float:
        """The motor's current (IT-104): inrush while starting, then a load
        term, far higher against a jam and far lower with a slipping belt.
        Zero whenever the motor isn't energized."""
        state = self.motor.state
        if state == MotorState.STARTING:
            return INRUSH_X * self.full_load_a
        if state != MotorState.RUNNING:
            return 0.0
        if self.jammed:
            return JAM_X * self.full_load_a
        if self.motion_switch_stuck_false:
            return SLIP_X * self.full_load_a
        load = min(1.0, self.mass_on_belt_kg / self.rated_load_kg) if self.rated_load_kg > 0 else 0.0
        return (NO_LOAD_X + FULL_BELT_EXTRA_X * load) * self.full_load_a

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
        if self.jammed and self.motor.running:
            self._jam_s = round(self._jam_s + dt, 9)
            if self._jam_s >= self.jam_overload_s:
                self.motor.overload()
        else:
            self._jam_s = 0.0
        if not self.motion_confirmed:
            return 0.0  # a stopped, slipping or jammed belt carries nothing anywhere
        self._time_s += dt
        delivered = 0.0
        while self._belt and self._belt[0][0] <= self._time_s + 1e-9:
            _, mass = self._belt.popleft()
            delivered += mass
        return delivered

    @property
    def mass_on_belt_kg(self) -> float:
        return sum(mass for _, mass in self._belt)
