#!/usr/bin/env python
"""Starts the live dashboard (docs/CONTROL-LAB.md §10, Phase 6 step 3):
the simulated line running in real time, served on localhost.

    python scripts/dashboard.py              # http://127.0.0.1:8000
    python scripts/dashboard.py --port 8080 --speed 2

Localhost only, no authentication -- a local engineering tool, not a
network service. All the logic lives in services/visualization/live.py.
"""
from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer

from services.visualization.live import SPEEDS, LiveSession, Pacer, make_handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--speed", type=float, default=1.0, choices=SPEEDS, help="simulated seconds per real second")
    args = parser.parse_args()

    session = LiveSession()
    pacer = Pacer(session, speed=args.speed)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(session, pacer))
    pacer.start()
    print(f"ControlLab live dashboard: http://127.0.0.1:{server.server_port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        pacer.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
