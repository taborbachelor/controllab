"""Slide gate state model: travels open/closed over a fixed time.

Limit switches only make at the end of travel — modeling the classic
"commanded but never arrived" gate fault (docs/CONTROL-LAB.md §5.4).

Known simplification: there's no continuous position, only time-in-state.
Reversing direction mid-travel (OPENING -> CLOSING or back) resets the
timer and takes the *full* nominal travel time from wherever it reversed,
not just the distance already covered. Real gates would close faster from
a half-open position. Acceptable for Phase 1-3 (commissioning tests care
about "did it reach the limit switch," not the exact reversal transient);
revisit with a real position variable if a test ever needs one.
"""
from __future__ import annotations

from enum import Enum, auto


class GateState(Enum):
    CLOSED = auto()
    OPENING = auto()
    OPEN = auto()
    CLOSING = auto()
    FAULT = auto()  # travel timeout


class Gate:
    def __init__(
        self,
        name: str,
        travel_time_s: float = 2.0,
        timeout_s: float | None = None,
    ) -> None:
        self.name = name
        self.travel_time_s = travel_time_s
        # Default timeout is generous (3x nominal travel) so a healthy
        # gate never trips it; a real gate would have a tighter, tuned one.
        self.timeout_s = timeout_s if timeout_s is not None else travel_time_s * 3
        self.state = GateState.CLOSED
        self.open_command = False
        self._elapsed_s = 0.0

        # Fault injection: travel never completes (limit switch stuck low).
        self.stuck = False

    @property
    def is_open(self) -> bool:
        return self.state == GateState.OPEN

    @property
    def is_closed(self) -> bool:
        return self.state == GateState.CLOSED

    def command(self, open_: bool) -> None:
        self.open_command = open_

    def clear_fault(self) -> None:
        if self.state == GateState.FAULT:
            self.state = GateState.CLOSED
            self._elapsed_s = 0.0

    def step(self, dt: float) -> None:
        if self.state == GateState.FAULT:
            return

        if self.state == GateState.CLOSED:
            if self.open_command:
                self.state = GateState.OPENING
                self._elapsed_s = 0.0
                self._advance_opening(dt)  # a 0s travel time resolves this same tick

        elif self.state == GateState.OPENING:
            if not self.open_command:
                self.state = GateState.CLOSING
                self._elapsed_s = 0.0
                self._advance_closing(dt)
            else:
                self._advance_opening(dt)

        elif self.state == GateState.OPEN:
            if not self.open_command:
                self.state = GateState.CLOSING
                self._elapsed_s = 0.0
                self._advance_closing(dt)

        elif self.state == GateState.CLOSING:
            if self.open_command:
                self.state = GateState.OPENING
                self._elapsed_s = 0.0
                self._advance_opening(dt)
            else:
                self._advance_closing(dt)

    def _advance_opening(self, dt: float) -> None:
        # Rounded to avoid float drift from repeated += dt (see Motor).
        self._elapsed_s = round(self._elapsed_s + dt, 9)
        if self._elapsed_s >= self.timeout_s:
            self.state = GateState.FAULT
            return
        if not self.stuck and self._elapsed_s >= self.travel_time_s:
            self.state = GateState.OPEN
            self._elapsed_s = 0.0

    def _advance_closing(self, dt: float) -> None:
        self._elapsed_s = round(self._elapsed_s + dt, 9)
        if self._elapsed_s >= self.timeout_s:
            self.state = GateState.FAULT
            return
        if not self.stuck and self._elapsed_s >= self.travel_time_s:
            self.state = GateState.CLOSED
            self._elapsed_s = 0.0
