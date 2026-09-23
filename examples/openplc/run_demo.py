#!/usr/bin/env python
"""A real-time commissioning check of the OpenPLC program against the
ControlLab plant (docs/CONTROL-LAB.md §10, Phase 7 step 4).

Prerequisites (see examples/openplc/README.md):
    python scripts/dashboard.py --external --port 8000 --modbus-port 5020
    OpenPLC running controllab_line.st, configured by setup_openplc.py

This drives the *plant* through the dashboard's own API (operator
commands, fault injection) and reads the *controller's* decisions back
from the status registers it publishes over Modbus -- the same
observation path the scenario suite uses in external mode, but against a
real PLC runtime, free-running on its own 100 ms task. So every check
waits with a real-time tolerance rather than counting ticks.

Prints a transcript; exits non-zero on the first failed check.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from services.protocols import controller_status  # noqa: E402
from services.protocols.line_map import LINE_REGISTER_MAP  # noqa: E402
from services.protocols.modbus import ModbusClient  # noqa: E402
from services.protocols.register_map import ModbusIOSync  # noqa: E402
from services.simulation.engine.plant_io import build_line_io_image  # noqa: E402


class Demo:
    def __init__(self, dashboard: str, modbus_port: int, tolerance_s: float) -> None:
        self.dashboard = dashboard.rstrip("/")
        self.tolerance_s = tolerance_s
        self.observer = ModbusIOSync(ModbusClient(port=modbus_port), LINE_REGISTER_MAP, build_line_io_image())
        self.t0 = time.monotonic()
        self.lines: list[str] = []

    def log(self, text: str) -> None:
        line = f"[{time.monotonic() - self.t0:6.2f}s] {text}"
        self.lines.append(line)
        print(line, flush=True)

    def _post(self, path: str, body: dict) -> None:
        req = urllib.request.Request(self.dashboard + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()

    def command(self, name: str) -> None:
        self.log(f"operator: {name}")
        self._post("/api/command", {"name": name})

    def stimulus(self, key: str, value) -> None:
        self.log(f"stimulus: {key} = {value}")
        self._post("/api/stimulus", {"key": key, "value": value})

    def plant(self) -> dict:
        with urllib.request.urlopen(self.dashboard + "/api/state?since=999999", timeout=5) as r:
            return json.load(r)["values"]

    def status(self) -> controller_status.ControllerStatus:
        return controller_status.decode(self.observer.read_status())

    def expect(self, description: str, check, timeout_s: float | None = None) -> None:
        deadline = time.monotonic() + (timeout_s or self.tolerance_s)
        start = time.monotonic()
        while True:
            status, plant = self.status(), self.plant()
            if check(status, plant):
                self.log(f"  ok  {description}  ({time.monotonic() - start:.2f}s)")
                return
            if time.monotonic() > deadline:
                latched = [a.id for a in status.latched_alarms]
                self.log(f"  FAIL {description} -- PLC state {status.state}, reason {status.fault_reason!r}, alarms {latched}")
                raise SystemExit(1)
            time.sleep(0.05)


def running(s, p):
    return s.state is not None and s.state.name == "RUNNING" and p["M-104.RUNNING"] and p["M-103.RUNNING"] and p["ZSO-102"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dashboard", default="http://127.0.0.1:8000")
    ap.add_argument("--modbus-port", type=int, default=5020)
    ap.add_argument("--tolerance", type=float, default=5.0, help="seconds each check may take (real time)")
    ap.add_argument("--transcript", type=Path, default=None, help="also write the transcript here")
    args = ap.parse_args()
    d = Demo(args.dashboard, args.modbus_port, args.tolerance)

    d.log("waiting for the PLC to publish status ...")
    d.expect("PLC is scanning", lambda s, p: s.state is not None and (s.state.name != "IDLE" or s.fault_reason is None), 30)
    first = d.status()
    if first.state.name == "ESTOPPED":
        # Fail-safe power-up: the PLC's first scans ran before its first Modbus
        # poll, so ES-001 (1 = healthy) read 0 -- "no data" looks like a pressed
        # E-stop, which is exactly what a fail-safe input is for. A real PLC
        # booting before its remote I/O rack answers does the same; the
        # operator acknowledges and resets.
        d.log("-- power-up: PLC started before its first I/O poll, so fail-safe ES-001 read 0 -> ESTOPPED")
        d.expect("ES-001.TRIP latched as first-out", lambda s, p: [(a.id, a.first_out) for a in s.latched_alarms] == [("ES-001.TRIP", True)])
        d.command("acknowledge")
        d.command("reset")
    d.expect("PLC reports IDLE, no latched alarms", lambda s, p: s.state.name == "IDLE" and not s.latched_alarms)

    d.log("-- normal start (downstream first: conveyor, prove, gate, feeder)")
    d.command("start")
    d.expect("line RUNNING, conveyor + gate + feeder energized", running)
    d.expect("material reaching the hopper", lambda s, p: p["WT-105"] > 0)

    d.log("-- feeder trip while running")
    d.stimulus("feeder_trip", True)
    d.expect("FAULTED, reason 'feeder trip', M-103.FAULT first-out and unacknowledged",
             lambda s, p: s.state.name == "FAULTED" and s.fault_reason == "feeder trip"
             and [(a.id, a.first_out, a.acknowledged) for a in s.latched_alarms] == [("M-103.FAULT", True, False)])
    d.expect("every output de-energized", lambda s, p: not (p["M-103.RUN"] or p["M-104.RUN"] or p["XV-102.CMD_OPEN"]))

    d.log("-- reset refused while the drive itself is still faulted")
    d.command("reset")
    time.sleep(1.0)
    d.expect("reset refused: the drive is still faulted", lambda s, p: s.state.name == "FAULTED")

    d.log("-- recovery: clear the cause, reset the drive at the field, acknowledge, reset, start")
    d.stimulus("feeder_trip", False)
    d.stimulus("feeder_drive_reset", True)
    d.command("acknowledge")
    d.expect("alarm acknowledged and cleared", lambda s, p: not s.latched_alarms)
    d.command("reset")
    d.expect("back to IDLE, no fault reason", lambda s, p: s.state.name == "IDLE" and s.fault_reason is None)
    d.command("start")
    d.expect("RUNNING again", running)

    d.log("-- E-stop")
    d.stimulus("estop", "tripped")
    d.expect("ESTOPPED, reason 'e-stop', motors off",
             lambda s, p: s.state.name == "ESTOPPED" and s.fault_reason == "e-stop" and not p["M-104.RUNNING"])
    d.stimulus("estop", "healthy")
    time.sleep(0.5)
    d.command("acknowledge")
    d.command("reset")
    d.expect("IDLE after release, acknowledge, reset", lambda s, p: s.state.name == "IDLE" and not s.latched_alarms)

    d.log("-- normal stop (upstream first, then purge)")
    d.command("start")
    d.expect("RUNNING", running)
    d.command("stop")
    d.expect("STOPPING: feeder off and gate closing, conveyor still purging",
             lambda s, p: s.state.name == "STOPPING" and not p["M-103.RUN"] and p["M-104.RUN"])
    d.expect("IDLE after the purge, conveyor off", lambda s, p: s.state.name == "IDLE" and not p["M-104.RUN"])

    d.log("ALL CHECKS PASSED")
    if args.transcript:
        args.transcript.write_text("\n".join(d.lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
