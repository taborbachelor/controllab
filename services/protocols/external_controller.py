"""The reference external controller (docs/CONTROL-LAB.md §10, Phase 7
step 3): ControlLab's own LineController, unmodified, running in a
*separate* program and reaching the plant only over Modbus TCP.

This is the end-to-end test of §3.2's central claim -- "the I/O image is
the contract." LineController has only ever touched an IOImage. Here that
IOImage is a local mirror, kept in step with the plant's over the wire by
ModbusIOSync, so the exact controller every scenario runs can drive the
plant without sharing a single Python object with it. If anything in
Control had quietly reached past the I/O image, this is where it would
break. Nothing in services/control/ changed for this step.

Each scan, in PLC order: read the field inputs and the HMI request word,
act on any new request, run the controller's scan, then write the outputs
together with the controller status block (step 3b) and the HMI ack word
-- five Modbus requests, shaped exactly as a standard PLC master polls
(step 4), so this is also the compatibility model for a real PLC.
`scan_once()` does exactly one, so tests can interleave plant and
controller deterministically; `run()` paces scans in real time, on
the controller's own clock, like a PLC with a fixed scan time
(free-running, the timing model chosen at Phase 7 scoping).

The controller is built by services/testing/rig.py's
build_line_controller(), the same stack and the same (test-speed) proof
windows every scenario uses, so external-mode results are comparable
with built-in-mode results.
"""
from __future__ import annotations

import threading
import time

from services.control.line_controller import LineController
from services.protocols import controller_status
from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.modbus import ModbusClient
from services.protocols.register_map import ModbusIOSync
from services.simulation.engine.plant_io import build_line_io_image
from services.testing.rig import DEFAULT_PLANT_CONFIG, DT, build_line_controller

COMMANDS = {
    "start": LineController.start,
    "stop": LineController.stop,
    "reset": LineController.reset,
    "acknowledge": LineController.acknowledge,
}


class ExternalController:
    def __init__(self, client, line_overrides: dict | None = None) -> None:
        self.io = build_line_io_image()
        self.line = build_line_controller(self.io, DEFAULT_PLANT_CONFIG["hopper_capacity_kg"], line_overrides)
        self.sync = ModbusIOSync(client, LINE_REGISTER_MAP, self.io)
        # The first scan must see the plant's real state, not the mirror's
        # defaults -- the same rule plant_io.scan() documents for a local rig.
        self.sync.pull_inputs()
        self.scans = 0

    def scan_once(self, dt: float = DT) -> None:
        self.sync.pull_inputs()
        for command in self.sync.take_commands():
            COMMANDS[command](self.line)
        self.line.scan(dt)
        self.sync.push_outputs(status=controller_status.encode(self.line))
        self.scans += 1


def run(
    host: str, port: int, speed: float = 1.0, stop: threading.Event | None = None, scan_s: float = DT
) -> None:
    """Scan every scan_s/speed wall-clock seconds until `stop` is set or the
    connection drops. `speed` must match the plant's, the same way a real
    PLC's scan time is set for the process it controls. `scan_s` is the
    task cycle (default one plant tick); a longer one models a slower PLC
    task, and with it real I/O latency (Phase 9's real-time tests)."""
    stop = stop or threading.Event()
    with ModbusClient(host, port) as client:
        controller = ExternalController(client)
        next_at = time.monotonic()
        while not stop.is_set():
            controller.scan_once(scan_s)
            next_at += scan_s / speed
            if time.monotonic() - next_at > 1.0:
                next_at = time.monotonic()  # resync after a stall rather than bursting
            stop.wait(max(0.0, next_at - time.monotonic()))
