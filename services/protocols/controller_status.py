"""The controller status block (docs/CONTROL-LAB.md §10, Phase 7 step 3b):
how a controller publishes its *internal* state -- line state, fault
reason, the alarm board -- over Modbus, the way a real PLC publishes
status words for its HMI.

Field I/O only shows what the plant is doing. A commissioning scenario
also asserts what the *controller* decided ("faulted, reason: feeder
trip, M-103.FAULT latched and first-out"), and when the controller is on
the far side of a Modbus connection the only honest way to see that is
for the controller to publish it. Five holding registers, written by the
controller every scan (see line_map.py for the addresses):

    line_state      code from LINE_STATES
    fault_reason    code from FAULT_REASONS (0 = none)
    alarms_active   bit i = ALARMS[i] active
    alarms_unacked  bit i = ALARMS[i] unacknowledged
    first_out       1 + index into ALARMS of the first-out alarm (0 = none)
    start_inhibit   StartInhibit bits: why the most recent start was refused
                    (added in Phase 8, appended after the HMI ack word so no
                    existing address moved)

Active + unacknowledged per alarm (rather than one "latched" mask) is what
lets the far side rebuild the full alarm board -- latched is just
active-or-unacknowledged -- so the scenario runner's EventLog works across
the wire unchanged.

The three code tables duplicate facts Control owns (its states, its
fault-reason strings, its alarm list), so each has a drift test in
tests/unit/test_controller_status.py that fails the moment Control gains
a state, reason, or alarm this table doesn't know. Codes are append-only:
a PLC program or HMI written against them must never see one renumbered.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.control.alarms import Alarm
from services.control.line_state import LineMode, LineState, StartInhibit

LINE_STATES: tuple[LineState, ...] = (
    LineState.IDLE,      # 0
    LineState.STARTING,  # 1
    LineState.RUNNING,   # 2
    LineState.STOPPING,  # 3
    LineState.FAULTED,   # 4
    LineState.ESTOPPED,  # 5
    LineState.MANUAL,    # 6  (Manual mode, completing Phase 2)
)

# The `mode` register (Manual mode, completing Phase 2).
MODES: tuple[LineMode, ...] = (
    LineMode.AUTO,    # 0
    LineMode.MANUAL,  # 1
)

FAULT_REASONS: tuple[str | None, ...] = (
    None,                                # 0
    "e-stop",                            # 1
    "hopper high-high",                  # 2
    "feeder trip",                       # 3
    "conveyor trip",                     # 4
    "feeder failed to prove running",    # 5
    "conveyor failed to prove running",  # 6
    "gate failed to prove open",         # 7
    "conveyor lost confirmation",        # 8
    "gate travel fault",                 # 9
    "feeder jam",                        # 10  (Phase 4 completion)
    "hopper weight signal failed",       # 11  (Phase 4 completion)
    "conveyor jam",                      # 12  (motor current, master specification item 5)
)

# (id, description, is_warning) in AlarmManager's registration order.
ALARMS: tuple[tuple[str, str, bool], ...] = (
    ("ES-001.TRIP", "E-stop tripped", False),                         # bit 0
    ("LSL-101.LOW", "Bin A low", True),                               # bit 1
    ("XV-102.TRAVEL_FAULT", "Bin A gate travel fault", False),        # bit 2
    ("M-103.FAULT", "Feeder trip (VFD fault/overload)", False),       # bit 3
    ("M-103.START_PROOF", "Feeder failed to prove running", False),   # bit 4
    ("M-104.OL", "Conveyor trip (overload)", False),                  # bit 5
    ("ZSS-104.LOST", "Conveyor motion loss (belt slip)", False),      # bit 6
    ("M-104.START_PROOF", "Conveyor failed to prove running", False), # bit 7
    ("WT-105.HIGH_HIGH", "Hopper high-high", False),                  # bit 8
    ("LSH-103.JAM", "Feeder jam (discharge chute plugged)", False),   # bit 9  (Phase 4 completion)
    ("WT-105.FAIL", "Hopper weight transmitter failed", False),       # bit 10 (Phase 4 completion)
    ("LSH-105.DISAGREE", "Hopper high switch disagrees with WT-105", True),         # bit 11 (level cross-check)
    ("LSHH-105.DISAGREE", "Hopper high-high switch disagrees with WT-105", False),  # bit 12 (level cross-check)
    ("IT-104.HIGH", "Conveyor motor overcurrent (jam)", False),                     # bit 13 (motor current)
    ("FT-104.NO_FLOW", "No flow on the belt while feeding", True),                  # bit 14 (belt scale)
    ("LSL-111.LOW", "Bin B low", True),                                             # bit 15 (bins B, C)
    ("XV-112.TRAVEL_FAULT", "Bin B gate travel fault", False),                      # bit 16 (second word)
    ("LSL-121.LOW", "Bin C low", True),                                             # bit 17
    ("XV-122.TRAVEL_FAULT", "Bin C gate travel fault", False),                      # bit 18
)
_ALARM_INDEX = {alarm_id: i for i, (alarm_id, _, _) in enumerate(ALARMS)}

REGISTER_NAMES = (
    "line_state", "fault_reason", "alarms_active", "alarms_unacked", "first_out", "start_inhibit", "mode",
    # Master specification, item 6: alarm bits 16-31, and the bins.
    "alarms_active_2", "alarms_unacked_2", "source_bin", "active_bin",
)
BIN_CODES = ("A", "B", "C")  # source_bin / active_bin: 1 + index; active_bin 0 = none
UNKNOWN = 0xFFFF  # a reason/state this table doesn't know -- published rather than guessed


def encode(line) -> list[int]:
    """A LineController's status, as the register values in REGISTER_NAMES order."""
    active = unacked = 0
    first_out = 0
    for alarm in line.alarms.all_alarms:
        bit = 1 << _ALARM_INDEX[alarm.id]
        if alarm.active:
            active |= bit
        if not alarm.acknowledged:
            unacked |= bit
        if alarm.first_out:
            first_out = _ALARM_INDEX[alarm.id] + 1
    state = LINE_STATES.index(line.state) if line.state in LINE_STATES else UNKNOWN
    reason = FAULT_REASONS.index(line.fault_reason) if line.fault_reason in FAULT_REASONS else UNKNOWN
    mode = MODES.index(line.mode) if line.mode in MODES else UNKNOWN
    source = 1 + BIN_CODES.index(line.source_bin)
    active_bin = 1 + BIN_CODES.index(line.active_bin) if line.active_bin else 0
    return [state, reason, active & 0xFFFF, unacked & 0xFFFF, first_out, int(line.start_inhibit), mode,
            active >> 16, unacked >> 16, source, active_bin]


@dataclass
class ControllerStatus:
    state: LineState | None  # None: a code this table doesn't know
    fault_reason: str | None
    alarms: list[Alarm]
    start_inhibit: StartInhibit = StartInhibit.NONE
    mode: LineMode | None = LineMode.AUTO  # None: a code this table doesn't know
    source_bin: str = "A"
    active_bin: str | None = None

    @property
    def latched_alarms(self) -> list[Alarm]:
        return [a for a in self.alarms if a.latched]

    def any_unacknowledged_trip(self) -> bool:
        return any(not a.acknowledged for a in self.alarms if not a.is_warning)


def decode(registers: list[int]) -> ControllerStatus:
    (state_code, reason_code, active_lo, unacked_lo, first_out, inhibit, mode_code,
     active_hi, unacked_hi, source_code, active_code) = registers
    active = active_lo | active_hi << 16
    unacked = unacked_lo | unacked_hi << 16
    state = LINE_STATES[state_code] if state_code < len(LINE_STATES) else None
    reason = FAULT_REASONS[reason_code] if reason_code < len(FAULT_REASONS) else f"unknown reason code {reason_code}"
    alarms = [
        Alarm(
            id=alarm_id,
            description=description,
            is_warning=is_warning,
            active=bool(active >> i & 1),
            acknowledged=not (unacked >> i & 1),
            first_out=first_out == i + 1,
        )
        for i, (alarm_id, description, is_warning) in enumerate(ALARMS)
    ]
    # Unknown bits are dropped rather than guessed, like an unknown reason code.
    known = StartInhibit(0)
    for member in StartInhibit:
        if member and inhibit & member:
            known |= member
    mode = MODES[mode_code] if mode_code < len(MODES) else None
    source = BIN_CODES[source_code - 1] if 1 <= source_code <= len(BIN_CODES) else "A"
    active_bin = BIN_CODES[active_code - 1] if 1 <= active_code <= len(BIN_CODES) else None
    return ControllerStatus(state, reason, alarms, known, mode, source, active_bin)


def render_markdown() -> str:
    """The code tables, for the register-map document."""
    lines = ["### `line_state` codes", "", "| Code | State |", "|---:|---|"]
    lines += [f"| {i} | {s.name} |" for i, s in enumerate(LINE_STATES)]
    lines += ["", "### `mode` codes", "", "| Code | Mode |", "|---:|---|"]
    lines += [f"| {i} | {m.name} |" for i, m in enumerate(MODES)]
    lines += ["", "### `fault_reason` codes", "", "| Code | Reason |", "|---:|---|"]
    lines += [f"| {i} | {r or '(none)'} |" for i, r in enumerate(FAULT_REASONS)]
    lines += ["", "### Alarm bits (`alarms_active`, `alarms_unacked`; `first_out` = bit + 1)", "",
              "| Bit | Alarm | Description | Class |", "|---:|---|---|---|"]
    lines += [f"| {i} | `{a}` | {d} | {'warning' if w else 'trip'} |" for i, (a, d, w) in enumerate(ALARMS)]
    lines += ["", "### `start_inhibit` bits (why the most recent start or mode request was refused; 0 = NONE)", "",
              "| Bit value | Reason |", "|---:|---|"]
    lines += [f"| {int(m)} | {m.name} |" for m in StartInhibit if m]
    lines += ["", "Set only when a start (line or Manual device) or a mode change is evaluated: NONE after an "
              "accepted one, unchanged when none is requested -- so it proves the request was actually issued.", ""]
    lines += ["", f"A value this table doesn't know is published as {UNKNOWN} rather than guessed.", ""]
    return "\n".join(lines)
