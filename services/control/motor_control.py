"""Control-side wrapper around one motor's I/O tags: issues the run (and
optional speed) command, and supervises something Simulation doesn't
report on its own — a **start-proof** timeout. Commanded to run, but
RUNNING never confirms within start_proof_timeout_s: that's a "fail to
start" condition Control has to detect by timing, because the device
itself has no way to report "I was asked to start and didn't" — all it
can report is its current state.

`faulted` (VFD fault / overload) is different: the device reports that
itself, so it's a plain pass-through of the fault feedback tag, no timing
needed.

Default start_proof_timeout_s=3.0 matches the "prove running... within 3s"
window already specified in docs/CONTROL-LAB.md §6.2's start sequence.

This module only ever touches the shared IOImage — never Motor,
MotorState, or any other simulation object (docs/CONTROL-LAB.md §3.2).
tests/unit/test_control_boundary.py enforces that mechanically.

Detecting a fault is this module's whole job. Deciding what to do about
one (stop the line, go to FAULTED) is line control's job (Phase 2 step 3)
— kept separate on purpose.
"""
from __future__ import annotations

from services.control.errors import ControlError, require_tag_type
from services.simulation.engine.io_image import IOImage, TagType


class MotorControl:
    def __init__(
        self,
        io: IOImage,
        run_tag: str,
        running_fb_tag: str,
        fault_fb_tag: str,
        speed_tag: str | None = None,
        start_proof_timeout_s: float = 3.0,
    ) -> None:
        require_tag_type(io, run_tag, TagType.DO)
        require_tag_type(io, running_fb_tag, TagType.DI)
        require_tag_type(io, fault_fb_tag, TagType.DI)
        if speed_tag is not None:
            require_tag_type(io, speed_tag, TagType.AO)

        self.io = io
        self.run_tag = run_tag
        self.running_fb_tag = running_fb_tag
        self.fault_fb_tag = fault_fb_tag
        self.speed_tag = speed_tag
        self.start_proof_timeout_s = start_proof_timeout_s

        # Latches until the run command changes or clear_fault() is
        # called — NOT auto-cleared just because the motor eventually
        # confirms running late while still commanded. Something took
        # longer than expected either way; that's worth keeping visible
        # rather than silently erasing once it catches up.
        self.start_proof_fault = False
        self._elapsed_s = 0.0
        self._last_commanded = False

    @property
    def commanded_run(self) -> bool:
        return self.io.read(self.run_tag)

    @property
    def running(self) -> bool:
        return self.io.read(self.running_fb_tag)

    @property
    def faulted(self) -> bool:
        """Simulation-reported fault (VFD fault / overload) — a plain
        pass-through, no supervision timing needed."""
        return self.io.read(self.fault_fb_tag)

    def command_run(self, run: bool) -> None:
        self.io.write_output(self.run_tag, run)

    def command_speed(self, speed_pct: float) -> None:
        if self.speed_tag is None:
            raise ControlError(f"{self.run_tag} has no speed output configured")
        self.io.write_output(self.speed_tag, speed_pct)

    def clear_fault(self) -> None:
        """Gives start-proof one more window on the next scan. Doesn't
        touch the trip feedback tag — that clears when Simulation clears
        it (or, once Phase 4 exists, when an operator resets the alarm
        built on top of it). Mirrors Motor.clear_fault()'s name on the
        simulation side on purpose — same idea, different layer."""
        self.start_proof_fault = False
        self._elapsed_s = 0.0

    def scan(self, dt: float) -> None:
        """Call once per scan cycle, after Simulation has published this
        tick's feedback and before the next tick's commands are applied."""
        commanded = self.commanded_run
        if commanded != self._last_commanded:
            self._elapsed_s = 0.0
            self.start_proof_fault = False
            self._last_commanded = commanded

        if not commanded or self.running:
            self._elapsed_s = 0.0
            return

        # Rounded to avoid float drift from repeated += dt — same class of
        # fix as Motor/Gate on the simulation side.
        self._elapsed_s = round(self._elapsed_s + dt, 9)
        if self._elapsed_s >= self.start_proof_timeout_s:
            self.start_proof_fault = True
