"""The Modbus register map for the bulk-material line (docs/CONTROL-LAB.md
§5.3's 17 tags; Phase 7 step 2). Written out address by address on
purpose, not derived from tag order: once a PLC program is written
against these addresses they're a contract, and adding a tag later must
never silently shift the ones already in use.

Each table starts at 0, in §5.3 order. Revised in Phase 7 step 4 so the
controller's view is five contiguous ranges a standard PLC master can
poll (see register_map.py): holding registers 0-6 are everything the
controller writes -- SC-103, the five status registers, the HMI ack word
-- and holding register 100 is the one it reads, the HMI request word.
The SCADA pushbutton coils keep their own block at 100, outside the
controller view, so field outputs can grow without colliding with them.
Scales give 0.01 % resolution on percentages and 0.1 kg on the hopper
weight, and every full-scale value fits in 16 bits (checked by
RegisterMap.validate()). The generated document is docs/MODBUS-MAP.md.
"""
from __future__ import annotations

import dataclasses

from services.protocols.register_map import (
    COIL,
    DISCRETE_INPUT,
    HOLDING_REGISTER,
    INPUT_REGISTER,
    HmiCoil,
    Point,
    RegisterMap,
    StatusRegister,
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
        # Appended (Phase 4 completion): never shift an address in use.
        Point("LSH-103", DISCRETE_INPUT, 11),
        Point("WT-105.FLT", DISCRETE_INPUT, 12),
        # Input registers -- analog sensors (AI)
        Point("LT-101", INPUT_REGISTER, 0, scale=100, full_scale=100.0),
        # WT-105 range = the hopper's 2,000 kg capacity -- the transmitter's
        # calibrated span is a design constant of the map, like on a real loop sheet.
        Point("WT-105", INPUT_REGISTER, 1, scale=10, full_scale=2000.0),
        # Appended (master specification, item 5): conveyor motor current,
        # 0.01 A over a 100 A range (starting inrush included), and the belt
        # scale's flow, 0.01 kg/s over 10 kg/s.
        Point("IT-104", INPUT_REGISTER, 2, scale=100, full_scale=100.0),
        Point("FT-104", INPUT_REGISTER, 3, scale=100, full_scale=10.0),
        # Coils -- field outputs (DO)
        Point("XV-102.CMD_OPEN", COIL, 0),
        Point("M-103.RUN", COIL, 1),
        Point("M-104.RUN", COIL, 2),
        # Holding registers -- analog outputs (AO); 1-6 follow below
        Point("SC-103", HOLDING_REGISTER, 0, scale=100, full_scale=100.0),
    ),
    hmi_coils=(
        HmiCoil("start", 100, "Start the line (Auto sequence, §6.2)"),
        HmiCoil("stop", 101, "Normal stop -- upstream first, then purge"),
        HmiCoil("reset", 102, "Reset a FAULTED/ESTOPPED line once the cause is cleared"),
        HmiCoil("acknowledge", 103, "Acknowledge all latched alarms"),
        # Manual mode (completing Phase 2): appended, request bits 4-11.
        HmiCoil("select_auto", 104, "Select Auto mode (accepted only at rest)"),
        HmiCoil("select_manual", 105, "Select Manual mode (accepted only at rest)"),
        HmiCoil("start_conveyor", 106, "Manual: start the conveyor"),
        HmiCoil("stop_conveyor", 107, "Manual: stop the conveyor (the feeder stops with it)"),
        HmiCoil("open_gate", 108, "Manual: open the gate"),
        HmiCoil("close_gate", 109, "Manual: close the gate"),
        HmiCoil("start_feeder", 110, "Manual: start the feeder (needs the conveyor proven running)"),
        HmiCoil("stop_feeder", 111, "Manual: stop the feeder"),
    ),
    # Controller status (Phase 7 step 3b; moved from 200-204 in step 4 so
    # it sits in the controller's single write range). Codes in
    # controller_status.py.
    status_registers=(
        StatusRegister("line_state", 1, "Line state code"),
        StatusRegister("fault_reason", 2, "Fault reason code (0 = none)"),
        StatusRegister("alarms_active", 3, "Bit per alarm: condition active"),
        StatusRegister("alarms_unacked", 4, "Bit per alarm: not yet acknowledged (latched = active or unacked)"),
        StatusRegister("first_out", 5, "1 + bit number of the first-out alarm (0 = none)"),
    ),
    hmi_ack=6,
    hmi_request=100,
)
# Phase 8: the start-inhibit status register, APPENDED at 7 -- after the HMI
# ack word, so no address a PLC program already uses moved.
LINE_REGISTER_MAP = dataclasses.replace(
    LINE_REGISTER_MAP,
    status_registers=LINE_REGISTER_MAP.status_registers
    + (StatusRegister("start_inhibit", 7, "Why the most recent start or mode request was refused (bits; 0 = none)"),),
)
# Manual mode (completing Phase 2): the mode register, APPENDED at 8 for the
# same reason; the controller write range grows to 0-8.
LINE_REGISTER_MAP = dataclasses.replace(
    LINE_REGISTER_MAP,
    status_registers=LINE_REGISTER_MAP.status_registers
    + (StatusRegister("mode", 8, "Operator-selected mode (0 = AUTO, 1 = MANUAL)"),),
)
