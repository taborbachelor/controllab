"""The line's modes, states and start-sequence sub-steps (docs/CONTROL-LAB.md
§6.1-6.2). Kept in their own module, separate from LineController, so tests
and any future consumer (a status display, Phase 6) can import just the
vocabulary without pulling in the state machine itself.
"""
from __future__ import annotations

from enum import Enum, IntFlag, auto


class LineMode(Enum):
    """The operator-selected mode (docs/CONTROL-LAB.md §6.1), kept separate
    from LineState: the mode says who drives the devices, the state says
    where the line is. It only changes at rest, and it outlives FAULTED and
    ESTOPPED -- a reset returns the line to its mode's rest state."""

    AUTO = auto()
    MANUAL = auto()


class LineState(Enum):
    IDLE = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    FAULTED = auto()
    ESTOPPED = auto()
    # Manual mode's one state: the operator commands each device, every
    # protection still enforced. Appended: state codes are published.
    MANUAL = auto()


class StartStep(Enum):
    """Sub-steps of the downstream-first start sequence
    (docs/CONTROL-LAB.md §6.2). Only meaningful while state == STARTING."""

    CONVEYOR = auto()
    GATE = auto()
    FEEDER = auto()


class StartInhibit(IntFlag):
    """Why the most recent start request was refused -- a line start, a
    Manual device start, or a mode change (Phase 8 prerequisite;
    docs/CONTROL-LAB.md §10). A flag, not a single code, because a start
    can be refused for several reasons at once -- a hopper at high-high
    also latches its own unacknowledged alarm.

    Deliberately the *outcome of the last start request*, not a live "why
    can't it start right now" status: it's set only when a start command
    is evaluated, so it proves a start was actually issued and refused. A
    live status would read the same whether or not anyone pressed Start,
    which is exactly what made the original start-blocked scenarios
    unable to tell a refused start from no start at all.

    NONE after an accepted start; unchanged when no start is requested.
    Values are append-only -- they're published over Modbus
    (services/protocols/controller_status.py)."""

    NONE = 0
    BIN_LOW = 1
    HOPPER_HIGH_HIGH = 2
    UNACKNOWLEDGED_ALARM = 4
    ESTOP_ACTIVE = 8
    LINE_FAULTED = 16  # start pressed while FAULTED: refused until reset
    SENSOR_FAILED = 32  # Phase 4 completion: the hopper weight signal (WT-105.FLT) has failed
    # Manual mode (completing Phase 2):
    CONVEYOR_NOT_RUNNING = 64  # Manual feeder start without the conveyor proven running
    HOPPER_HIGH = 128  # Manual feeder start at LSH-105 (Manual has no level control; the switch stands in)
    WRONG_MODE = 256  # a device command in Auto, or the line Start in Manual
    LINE_NOT_IDLE = 512  # a mode change away from rest (Auto not IDLE, or a Manual device still on)


def inhibit_names(inhibit: StartInhibit) -> list[str]:
    """Sorted reason names, ["NONE"] when there are none -- the readable
    form the scenario vocabulary compares against."""
    names = sorted(m.name for m in StartInhibit if m and m in inhibit)
    return names or ["NONE"]
