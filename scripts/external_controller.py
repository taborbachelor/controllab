#!/usr/bin/env python
"""Runs ControlLab's own LineController as an EXTERNAL controller
(docs/CONTROL-LAB.md §10, Phase 7 step 3): a separate program that reaches
the plant only over Modbus TCP, the way a PLC would.

    python scripts/dashboard.py --external            # terminal 1: the plant, no controller
    python scripts/external_controller.py             # terminal 2: the controller

Then press Start on the dashboard. --speed must match the dashboard's,
the same way a real PLC's scan time is set for the process it controls.
All the logic lives in services/protocols/external_controller.py.
"""
from __future__ import annotations

import argparse
import signal
import sys
import threading

from services.protocols.external_controller import run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5020)
    parser.add_argument("--speed", type=float, default=1.0, help="must match the plant (dashboard --speed)")
    args = parser.parse_args()

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
    print(f"External controller -> modbus://{args.host}:{args.port} at {args.speed}x (Ctrl+C to stop)", flush=True)
    try:
        run(args.host, args.port, args.speed, stop)
    except (ConnectionError, OSError) as e:
        print(f"lost connection to the plant: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
