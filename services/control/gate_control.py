"""Control-side wrapper around one gate's I/O tags: issues the open/close
command, and supervises a **travel timeout** Simulation doesn't report on
its own through the I/O image — there's no "gate fault" DI tag in the
field I/O list (docs/CONTROL-LAB.md §5.3), only the two limit switches.
If the commanded limit switch hasn't made within travel_timeout_s, that's
this module's own detection, by timing — exactly like MotorControl's
start-proof, and for the same reason.

Default travel_timeout_s=5.0 matches the "prove open... within 5s" window
already specified in docs/CONTROL-LAB.md §6.2's start sequence. Note this
is deliberately independent from — and normally tighter than — the
simulated Gate's own internal timeout_s (docs/CONTROL-LAB.md §5, Gate):
that one models a physical protection tripping regardless of what's
commanding it; this one is Control's own diagnostic window, meant to
catch a problem before (or independent of) the physical protection ever
engages. Two different timeouts modeling two different real things, not
redundancy.

Detecting the fault is this module's job; deciding what to do about it is
line control's (Phase 2 step 3).
"""
from __future__ import annotations

from services.control.errors import require_tag_type
from services.simulation.engine.io_image import IOImage, TagType


class GateControl:
    def __init__(
        self,
        io: IOImage,
        command_tag: str,
        open_fb_tag: str,
        closed_fb_tag: str,
        travel_timeout_s: float = 5.0,
    ) -> None:
        require_tag_type(io, command_tag, TagType.DO)
        require_tag_type(io, open_fb_tag, TagType.DI)
        require_tag_type(io, closed_fb_tag, TagType.DI)

        self.io = io
        self.command_tag = command_tag
        self.open_fb_tag = open_fb_tag
        self.closed_fb_tag = closed_fb_tag
        self.travel_timeout_s = travel_timeout_s

        # Latches until the command changes or clear_fault() is called —
        # NOT auto-cleared just because the gate eventually reaches the
        # target late while still commanded. See MotorControl's identical
        # choice for the reasoning.
        self.travel_fault = False
        self._elapsed_s = 0.0
        self._last_commanded = False

    @property
    def commanded_open(self) -> bool:
        return self.io.read(self.command_tag)

    @property
    def is_open(self) -> bool:
        return self.io.read(self.open_fb_tag)

    @property
    def is_closed(self) -> bool:
        return self.io.read(self.closed_fb_tag)

    def command_open(self, open_: bool) -> None:
        self.io.write_output(self.command_tag, open_)

    def clear_fault(self) -> None:
        """Gives travel-proof one more window on the next scan. Mirrors
        Gate.clear_fault() on the simulation side on purpose."""
        self.travel_fault = False
        self._elapsed_s = 0.0

    def scan(self, dt: float) -> None:
        """Call once per scan cycle, after Simulation has published this
        tick's feedback and before the next tick's commands are applied."""
        commanded = self.commanded_open
        if commanded != self._last_commanded:
            self._elapsed_s = 0.0
            self.travel_fault = False
            self._last_commanded = commanded

        at_target = self.is_open if commanded else self.is_closed
        if at_target:
            self._elapsed_s = 0.0
            return

        self._elapsed_s = round(self._elapsed_s + dt, 9)
        if self._elapsed_s >= self.travel_timeout_s:
            self.travel_fault = True
