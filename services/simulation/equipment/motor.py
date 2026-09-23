"""Motor-driven equipment state model (used by Feeder and Conveyor).

An explicit state machine rather than a bag of booleans — see
docs/CONTROL-LAB.md §9 ("Avoid implementing equipment as a collection of
arbitrary booleans. State transitions should be explicit and testable.").
"""
from __future__ import annotations

from enum import Enum, auto


class MotorState(Enum):
    STOPPED = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    FAULT = auto()
    ESTOP = auto()


class Motor:
    """A simulated motor: run command in, running/fault feedback out.

    Models the gap between "commanded to run" and "confirmed running"
    that every real control system has to account for: a start delay, a
    possible fail-to-start, and a possible trip while running.
    """

    def __init__(
        self,
        name: str,
        start_delay_s: float = 0.5,
        stop_delay_s: float = 0.5,
    ) -> None:
        self.name = name
        self.start_delay_s = start_delay_s
        self.stop_delay_s = stop_delay_s

        self.state = MotorState.STOPPED
        self.run_command = False
        self.fault = False
        self._elapsed_s = 0.0

        # Fault-injection hooks (docs/CONTROL-LAB.md §5.4). Persistent
        # until explicitly cleared by whoever set them — a standing fault
        # condition, not a one-shot event.
        self.fail_to_start = False
        self.trip_now = False

    @property
    def running(self) -> bool:
        return self.state == MotorState.RUNNING

    def command(self, run: bool) -> None:
        """Operator/control run command. Has no effect while FAULT or
        ESTOP — those require clear_fault()/estop_reset() first."""
        self.run_command = run

    def estop(self) -> None:
        """Power removed. A motor already in FAULT stays there: removing
        power doesn't reset a tripped overload relay or a VFD fault, so the
        fault still needs its own clear_fault() afterwards. (It became ESTOP
        with the fault flag still set, and estop_reset() then left it
        STOPPED-but-faulted, a state clear_fault() couldn't leave -- the
        overload could never be reset. Found in the 2026-09-23 logic review.)"""
        self.run_command = False
        if self.state == MotorState.FAULT:
            return
        self.state = MotorState.ESTOP
        self._elapsed_s = 0.0

    def estop_reset(self) -> None:
        """Leaves ESTOP for STOPPED. Does NOT restart the motor — a real
        line doesn't auto-restart after an E-stop (docs/CONTROL-LAB.md
        §6.2); a separate run command is required."""
        if self.state == MotorState.ESTOP:
            self.state = MotorState.STOPPED

    def clear_fault(self) -> None:
        if self.state == MotorState.FAULT:
            self.fault = False
            self.state = MotorState.STOPPED

    def step(self, dt: float) -> None:
        if self.state == MotorState.ESTOP:
            return  # only estop_reset() leaves this state
        if self.state == MotorState.FAULT:
            return  # only clear_fault() leaves this state

        if self.trip_now and self.state == MotorState.RUNNING:
            self._trip()
            return

        if self.state == MotorState.STOPPED:
            if self.run_command:
                self.state = MotorState.STARTING
                self._elapsed_s = 0.0
                self._advance_starting(dt)  # a 0s delay resolves this same tick

        elif self.state == MotorState.STARTING:
            if not self.run_command:
                self.state = MotorState.STOPPED
                self._elapsed_s = 0.0
            else:
                self._advance_starting(dt)

        elif self.state == MotorState.RUNNING:
            if not self.run_command:
                self.state = MotorState.STOPPING
                self._elapsed_s = 0.0
                self._advance_stopping(dt)

        elif self.state == MotorState.STOPPING:
            self._advance_stopping(dt)

    def _advance_starting(self, dt: float) -> None:
        """Elapsed time in STARTING, checked the same tick it's entered —
        so start_delay_s=0.0 confirms RUNNING immediately, the way a PLC
        TON timer with PT=0 expires on its first enabled scan."""
        # Rounded to avoid float drift from repeated += dt (e.g. ten
        # additions of 0.1 sum to 0.9999999999999999, not 1.0 — see
        # SimClock, which sidesteps the same class of bug differently).
        self._elapsed_s = round(self._elapsed_s + dt, 9)
        if self.fail_to_start:
            return  # commanded, but never confirms running
        if self._elapsed_s >= self.start_delay_s:
            self.state = MotorState.RUNNING
            self._elapsed_s = 0.0

    def _advance_stopping(self, dt: float) -> None:
        self._elapsed_s = round(self._elapsed_s + dt, 9)
        if self._elapsed_s >= self.stop_delay_s:
            self.state = MotorState.STOPPED
            self._elapsed_s = 0.0

    def _trip(self) -> None:
        self.fault = True
        self.state = MotorState.FAULT
        self.run_command = False
        self._elapsed_s = 0.0
