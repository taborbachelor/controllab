"""Evaluates the interlock table (docs/CONTROL-LAB.md §6.3) against
current I/O image tags and device-control state.

A query object, not a state machine — it has no memory of its own and no
opinion about what to DO with a trip; LineController decides that, per
the state and step it's currently in (the same physical condition means
something different during STARTING's proof steps than it does once
already RUNNING). It's reused across every state that needs to check a
trip or a permissive, so the same boolean expression (e.g. "is the
conveyor genuinely confirmed moving") isn't computed two different ways
in two different places.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from services.control.gate_control import GateControl
from services.control.motor_control import MotorControl
from services.simulation.engine.io_image import IOImage


@dataclass(frozen=True)
class PermissiveCheck:
    ok: bool
    reasons: list[str] = field(default_factory=list)


class Interlocks:
    def __init__(
        self,
        io: IOImage,
        feeder_ctrl: MotorControl,
        conveyor_ctrl: MotorControl,
        gate_ctrl: GateControl,
        hopper_capacity_kg: float,
    ) -> None:
        self.io = io
        self.feeder_ctrl = feeder_ctrl
        self.conveyor_ctrl = conveyor_ctrl
        self.gate_ctrl = gate_ctrl
        self.hopper_capacity_kg = hopper_capacity_kg

    @property
    def estop_healthy(self) -> bool:
        return self.io.read("ES-001")

    @property
    def bin_low(self) -> bool:
        return self.io.read("LSL-101")

    @property
    def feeder_plugged(self) -> bool:
        """LSH-103, the discharge-chute plug switch: a feeder jam. It stays
        made until the jam is physically cleared, so unlike a timing
        diagnostic it can gate a reset."""
        return self.io.read("LSH-103")

    @property
    def hopper_weight_failed(self) -> bool:
        """WT-105.FLT, the input channel's diagnostic: WT-105's value is
        meaningless (it reads 0.0, like an empty hopper), so nothing that
        depends on the hopper weight can be decided. docs/CONTROL-LAB.md §8:
        unknown means stopped."""
        return self.io.read("WT-105.FLT")

    @property
    def hopper_high(self) -> bool:
        """LSH-105 open. Fail-safe polarity (1 = below the switch point), so
        a broken wire reads high and stops the feed rather than letting it
        run on unwatched."""
        return not self.io.read("LSH-105")

    @property
    def hopper_high_high(self) -> bool:
        """LSHH-105 open. Fail-safe polarity (1 = below the switch point), so
        a broken wire trips the line rather than silently removing the
        overfill trip (docs/CONTROL-LAB.md §8: loss of signal is the unsafe
        condition)."""
        return not self.io.read("LSHH-105")

    @property
    def hopper_level_pct(self) -> float:
        """Computed from WT-105 (raw weight, kg) and a known hopper
        capacity — there's no percentage tag for the hopper the way
        LT-101 is one for the bin (docs/CONTROL-LAB.md §5.3 deliberately
        uses weight for the hopper; a real weigh-hopper measures mass
        directly). hopper_capacity_kg is a configured constant, the same
        way a real control program is commissioned with the vessel's
        known engineering capacity, not something read off a tag."""
        return 100.0 * self.io.read("WT-105") / self.hopper_capacity_kg

    @property
    def conveyor_motion_confirmed(self) -> bool:
        """ZSS-104 alone. See conveyor_confirmed_running for the combined
        check most interlocks actually want."""
        return self.io.read("ZSS-104")

    @property
    def conveyor_confirmed_running(self) -> bool:
        """RUNNING (M-104.RUNNING, the contactor aux — MotorControl.running)
        AND ZSS-104 (the motion switch) both true — the combination
        docs/CONTROL-LAB.md §6.2's start sequence calls "prove running."
        Checking RUNNING alone would miss a belt slip (docs/CONTROL-LAB.md
        §5.4): the motor can be genuinely energized while the belt itself
        isn't moving. This lives here rather than as a MotorControl
        feature because it's specific to a motor with an independent
        motion-confirmation signal — the feeder has no equivalent tag."""
        return self.conveyor_ctrl.running and self.conveyor_motion_confirmed

    def start_permissives_ok(self) -> PermissiveCheck:
        """Everything that must be true before a start is allowed
        (docs/CONTROL-LAB.md §6.3's Permissive rows).

        E-stop is deliberately NOT checked here: LineController's own
        scan() diverts to ESTOPPED before ever reaching a start-permissive
        check, so by the time this runs, e-stop is guaranteed healthy —
        including it here would be dead code that's always true.

        "No active latched alarms" is also NOT checked here, and never
        will be: AlarmManager (services/control/alarms.py, Phase 4 step 1)
        is built on top of this class, so this class checking it back
        would be circular. LineController._scan_idle() combines this
        check with the alarm set's own unacknowledged-trip state itself,
        the same way it's already the one place every other
        permissive/trip decision gets combined."""
        reasons: list[str] = []
        if self.hopper_high_high:
            reasons.append("hopper at high-high")
        if self.bin_low:
            reasons.append("bin low")
        if self.hopper_weight_failed:
            reasons.append("hopper weight signal failed")
        return PermissiveCheck(ok=not reasons, reasons=reasons)
