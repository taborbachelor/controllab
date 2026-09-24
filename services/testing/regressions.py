"""Deliberate control-logic regressions: test fixtures that prove the
scenario suite catches a bad change to the controller.

Each is a named subclass of the real LineController with one plausible bad
change -- the kind a well-meaning edit introduces ("the plug switch keeps
nuisance-tripping, drop that trip"). They live here in Testing, are built
only when asked for by name (`controllab test --regression NAME`, the
dashboard's controller-build selector, tests/unit/test_regressions.py),
and never touch services/control/: production code is never modified to
demonstrate a failure.

Where a regression changes one branch of a production method, the method
is copied here with that branch changed and the change marked, so the diff
reads like the bad commit it stands for. tests/unit/test_regressions.py
proves each one is caught by the suite, and by the scenario named as its
demonstration, failing at the stage it should.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.control.interlocks import Interlocks
from services.control.line_controller import LineController
from services.control.line_state import StartInhibit


class JamTripRemoved(LineController):
    """The feeder-jam trip deleted from RUNNING: "the plug switch keeps
    nuisance-tripping". Production's _running_trip_reason, minus one branch."""

    def _running_trip_reason(self) -> str | None:
        if self.interlocks.hopper_high_high:
            return "hopper high-high"
        if self.feeder_ctrl.faulted:
            return "feeder trip"
        # REGRESSION: the plug-switch (feeder jam) trip was removed here.
        if self.feeder_ctrl.start_proof_fault:
            return "feeder failed to prove running"
        if self.interlocks.hopper_weight_failed:
            return "hopper weight signal failed"
        if self.conveyor_ctrl.faulted:
            return "conveyor trip"
        if not self.interlocks.conveyor_confirmed_running:
            return "conveyor lost confirmation"
        if self.gate_ctrl.travel_fault:
            return "gate travel fault"
        return None


class ResetIgnoresJam(LineController):
    """Reset allowed while the chute is still plugged: "operators need to
    reset faster". Production's _standing_cause, minus one branch."""

    def _standing_cause(self) -> str | None:
        if self.interlocks.hopper_high_high:
            return "hopper high-high"
        if self.conveyor_ctrl.faulted:
            return "conveyor trip"
        if self.feeder_ctrl.faulted:
            return "feeder trip"
        # REGRESSION: the plug-switch (feeder jam) check was removed here.
        if self.interlocks.hopper_weight_failed:
            return "hopper weight signal failed"
        return None


class _SwitchOnlyInterlocks(Interlocks):
    @property
    def hopper_high_high(self) -> bool:
        # REGRESSION: the 1oo2 vote reverted to the switch alone.
        return self.hopper_high_high_switch


class HighHighSwitchOnly(LineController):
    """The high-high trip back on the level switch alone: "the weight
    transmitter vote is redundant". A switch stuck healthy then removes the
    overfill trip."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Reclassed in place, not replaced, because the alarm manager and the
        # level checks already hold this same Interlocks object.
        self.interlocks.__class__ = _SwitchOnlyInterlocks


class FeederStartsWithConveyor(LineController):
    """The start sequence "sped up": the feeder commanded together with the
    conveyor instead of after the belt proves running and the gate opens."""

    def _begin_start_sequence(self) -> None:
        super()._begin_start_sequence()
        # REGRESSION: feeder started in the same scan as the conveyor.
        self.feeder_ctrl.command_run(True)
        self.feeder_ctrl.command_speed(self.feed_speed_pct)


class PurgeTooShort(LineController):
    """The belt purge cut to a quarter "to make stops quicker": shorter than
    the belt's transit time, so a normal stop leaves material on the belt."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # REGRESSION: purge time cut to a quarter of the commissioned value.
        self.purge_time_s = self.purge_time_s / 4


class ManualFeederBeforeBelt(LineController):
    """Manual mode lets the feeder run before the belt proves running: "let
    operators prime the screw first". Production's _manual_feeder_refusal
    and _manual_feed_permitted, each minus its conveyor condition."""

    def _manual_feeder_refusal(self):
        inhibit, reasons = StartInhibit.NONE, []
        # REGRESSION: the conveyor-proven check was removed here.
        if self.interlocks.bin_low:
            inhibit |= StartInhibit.BIN_LOW
            reasons.append("bin low")
        if self.interlocks.hopper_high:
            inhibit |= StartInhibit.HOPPER_HIGH
            reasons.append("hopper at the high switch")
        if self.interlocks.hopper_high_high:
            inhibit |= StartInhibit.HOPPER_HIGH_HIGH
            reasons.append("hopper at high-high")
        if self.interlocks.hopper_weight_failed:
            inhibit |= StartInhibit.SENSOR_FAILED
            reasons.append("hopper weight signal failed")
        inhibit, reasons = self._unacked_refusal(inhibit, reasons)
        return inhibit, reasons

    def _manual_feed_permitted(self) -> bool:
        # REGRESSION: the proven-belt condition was removed here.
        return not self.interlocks.hopper_high


@dataclass(frozen=True)
class Regression:
    name: str
    cls: type[LineController]
    change: str
    demo_scenario: str  # scenario file (relative to scenarios/) that demonstrates it
    expected: str  # what correct behavior looks like, in words


REGRESSIONS: dict[str, Regression] = {
    r.name: r
    for r in (
        Regression(
            "jam-trip-removed", JamTripRemoved,
            "The feeder-jam (plug switch) trip was deleted from the RUNNING state.",
            "faults/feeder_jam_recovery.yaml",
            "Feeder jam -> line trips: feed stops, the conveyor clears the belt",
        ),
        Regression(
            "reset-ignores-jam", ResetIgnoresJam,
            "Reset is accepted while the discharge chute is still plugged.",
            "faults/feeder_jam_recovery.yaml",
            "Reset refused while the jam remains",
        ),
        Regression(
            "high-high-switch-only", HighHighSwitchOnly,
            "The 1oo2 overfill trip was reverted to the level switch alone.",
            "faults/hopper_high_high_switch_stuck_weight_trips.yaml",
            "Hopper overfilled with the switch stuck -> the weight transmitter trips the line",
        ),
        Regression(
            "feeder-starts-with-conveyor", FeederStartsWithConveyor,
            "The start sequence commands the feeder together with the conveyor.",
            "startup/normal_operation.yaml",
            "Start -> conveyor first, feeder only after the belt proves running",
        ),
        Regression(
            "purge-too-short", PurgeTooShort,
            "The stop sequence's belt purge was cut to a quarter, shorter than the belt's transit time.",
            "startup/normal_operation.yaml",
            "Stop -> the conveyor runs on until the belt is empty",
        ),
        Regression(
            "manual-feeder-before-belt", ManualFeederBeforeBelt,
            "Manual mode lets the feeder start and run before the conveyor proves running.",
            "manual/manual_feeder_refused_without_conveyor.yaml",
            "Manual feeder start with the conveyor stopped -> refused (CONVEYOR_NOT_RUNNING), feeder stays off",
        ),
    )
}
