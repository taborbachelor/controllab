"""The Modbus register map for the bulk-material line (docs/CONTROL-LAB.md
§5.3's 17 tags; Phase 7 step 2). Written out address by address on
purpose, not derived from tag order: once a PLC program is written
against these addresses they're a contract, and adding a tag later must
never silently shift the ones already in use.

Each table starts at 0, in §5.3 order. HMI command coils sit in their own
block at 100, so field outputs can grow without ever colliding with them.
Scales give 0.01 % resolution on percentages and 0.1 kg on the hopper
weight, and every full-scale value fits in 16 bits (checked by
RegisterMap.validate()). The generated document is docs/MODBUS-MAP.md.
"""
from __future__ import annotations

from services.protocols.register_map import (
    COIL,
    DISCRETE_INPUT,
    HOLDING_REGISTER,
    INPUT_REGISTER,
    HmiCoil,
    Point,
    RegisterMap,
)

LINE_REGISTER_MAP = RegisterMap(
    points=(
        # Discrete inputs -- field sensors (DI)
        Point("LSL-101", DISCRETE_INPUT, 0),
        Point("ZSO-102", DISCRETE_INPUT, 1),
        Point("ZSC-102", DISCRETE_INPUT, 2),
        Point("M-103.RUNNING", DISCRETE_INPUT, 3),
        Point("M-103.FAULT", DISCRETE_INPUT, 4),
        Point("M-104.RUNNING", DISCRETE_INPUT, 5),
        Point("M-104.OL", DISCRETE_INPUT, 6),
        Point("ZSS-104", DISCRETE_INPUT, 7),
        Point("LSH-105", DISCRETE_INPUT, 8),
        Point("LSHH-105", DISCRETE_INPUT, 9),
        Point("ES-001", DISCRETE_INPUT, 10),
        # Input registers -- analog sensors (AI)
        Point("LT-101", INPUT_REGISTER, 0, scale=100, full_scale=100.0),
        # WT-105 range = the hopper's 2,000 kg capacity -- the transmitter's
        # calibrated span is a design constant of the map, like on a real loop sheet.
        Point("WT-105", INPUT_REGISTER, 1, scale=10, full_scale=2000.0),
        # Coils -- field outputs (DO)
        Point("XV-102.CMD_OPEN", COIL, 0),
        Point("M-103.RUN", COIL, 1),
        Point("M-104.RUN", COIL, 2),
        # Holding registers -- analog outputs (AO)
        Point("SC-103", HOLDING_REGISTER, 0, scale=100, full_scale=100.0),
    ),
    hmi_coils=(
        HmiCoil("start", 100, "Start the line (Auto sequence, §6.2)"),
        HmiCoil("stop", 101, "Normal stop -- upstream first, then purge"),
        HmiCoil("reset", 102, "Reset a FAULTED/ESTOPPED line once the cause is cleared"),
        HmiCoil("acknowledge", 103, "Acknowledge all latched alarms"),
    ),
)
