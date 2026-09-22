"""Continuous invariant checks (docs/CONTROL-LAB.md §7, item 6): run on
every scan of every scenario, not just asserted once at the end. An
invariant violation is a stronger failure than "the expected outcome
hasn't happened yet" — it means the system did something actively
wrong, not just that it's still working on getting there.

Covers three of the four invariants §7 lists, in order:

- Material is conserved — always true, zero grace.
- The feeder is never running while the conveyor is not proven running,
  beyond one scan — the one-scan grace matches the standard one-tick
  scan-cycle lag everywhere else in this project (LineController takes
  one tick to react to a freshly-published tag).
- No motor output is energized while the E-stop is tripped — always
  true, zero grace: Plant.step() handles the whole trip atomically
  within one call, so there's no tick where it's observably false.

"No spillage during normal start and stop" is deliberately NOT here —
it's true only for scenarios about normal operation, not fault ones (a
belt-slip trip, for instance, can spill for the one tick before
LineController reacts). Making it universal would mean either weakening
it to tolerate fault-path spillage, defeating the point, or wrongly
failing scenarios that are deliberately testing what a fault looks like.
It belongs in a scenario's own `expect`, not this cross-cutting checker.
"""
from __future__ import annotations

from services.testing.rig import Rig


class InvariantViolation(AssertionError):
    """Raised the instant a check fails — a distinct type from a plain
    assertion failure, so a scenario report can tell "the system did
    something actively wrong" apart from "the expected outcome hasn't
    happened yet, still within its window."""


class Invariants:
    def __init__(self, rig: Rig) -> None:
        self.rig = rig
        self.starting_mass_kg = rig.plant.total_mass_kg()
        self._feeder_unconfirmed_ticks = 0

    def rebaseline(self) -> None:
        """Reset the conservation baseline to the plant's CURRENT total.

        A scenario's `given`/`when` can deliberately preset a vessel
        level (hopper_level_pct, bin_level_pct) as a Testing stimulus --
        that's a legitimate setup action, not a physical event, and
        checking it against the mass the rig started with at raw
        construction would flag every such scenario as "material
        appeared from nowhere." The runner calls this once after each
        setup phase (given, then when) completes, so conservation is
        checked against "as configured for this scenario," not "as
        originally built" -- see runner.py."""
        self.starting_mass_kg = self.rig.plant.total_mass_kg()

    def check(self) -> None:
        self._check_material_conserved()
        self._check_feeder_not_running_unconfirmed()
        self._check_no_motor_energized_during_estop()

    def _check_material_conserved(self) -> None:
        accounted = self.rig.plant.accounted_mass_kg()
        if abs(accounted - self.starting_mass_kg) > 1e-6:
            raise InvariantViolation(
                f"material not conserved: accounted {accounted:.6f} kg, "
                f"started with {self.starting_mass_kg:.6f} kg"
            )

    def _check_feeder_not_running_unconfirmed(self) -> None:
        feeder_running = self.rig.plant.feeder.motor.running
        conveyor_confirmed = self.rig.line.interlocks.conveyor_confirmed_running
        if feeder_running and not conveyor_confirmed:
            self._feeder_unconfirmed_ticks += 1
        else:
            self._feeder_unconfirmed_ticks = 0
        if self._feeder_unconfirmed_ticks > 1:
            raise InvariantViolation("feeder ran onto an unconfirmed conveyor for more than one scan")

    def _check_no_motor_energized_during_estop(self) -> None:
        if not self.rig.plant.estop.tripped:
            return
        if self.rig.plant.feeder.motor.running or self.rig.plant.conveyor.motor.running:
            raise InvariantViolation("a motor is energized while the E-stop is tripped")
