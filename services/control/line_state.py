"""The line's states and start-sequence sub-steps (docs/CONTROL-LAB.md
§6.2). Kept in their own module, separate from LineController, so tests
and any future consumer (a status display, Phase 6) can import just the
vocabulary without pulling in the state machine itself.
"""
from __future__ import annotations

from enum import Enum, auto


class LineState(Enum):
    IDLE = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    FAULTED = auto()
    ESTOPPED = auto()


class StartStep(Enum):
    """Sub-steps of the downstream-first start sequence
    (docs/CONTROL-LAB.md §6.2). Only meaningful while state == STARTING."""

    CONVEYOR = auto()
    GATE = auto()
    FEEDER = auto()
