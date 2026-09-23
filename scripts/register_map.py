#!/usr/bin/env python
"""Writes the line's Modbus register map as a commissioning document
(docs/CONTROL-LAB.md §10, Phase 7 step 2):

    python scripts/register_map.py                 # print
    python scripts/register_map.py --out docs/MODBUS-MAP.md
    python scripts/register_map.py --map configs/io/relocated.yaml --out relocated-map.md

--map renders a user-supplied I/O map file (Phase 9 step 4,
services/protocols/map_file.py) instead of the line's built-in map, after
validating it: the same document, including the PLC master configuration.

Generated from the same RegisterMap the server uses
(services/protocols/line_map.py), and
tests/unit/test_register_map.py fails if the committed
docs/MODBUS-MAP.md no longer matches it -- the document can't drift.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from services.protocols import controller_status
from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.register_map import render_markdown
from services.simulation.engine.plant_io import build_line_io_image

TITLE = "ControlLab — Modbus Register Map (bulk-material line)"


def render(map_path: Path | None = None) -> str:
    io = build_line_io_image()
    if map_path is None:
        LINE_REGISTER_MAP.validate(io)
        return render_markdown(LINE_REGISTER_MAP, io, TITLE, status_notes=controller_status.render_markdown())
    from services.protocols.map_file import load_map

    register_map, name = load_map(map_path, io)
    notes = controller_status.render_markdown() if register_map.status_registers else ""
    return render_markdown(register_map, io, f"ControlLab — Modbus Register Map ({name or map_path.name})",
                           status_notes=notes, source=f"`{map_path.as_posix()}`")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--map", type=Path, default=None, help="a map file to render instead of the built-in map")
    args = parser.parse_args()
    try:
        text = render(args.map)
    except ValueError as e:  # MapFileError: every problem, listed
        print(e)
        return 2
    if args.out is None:
        # The document is UTF-8 Markdown (→, ×, —); a Windows console or pipe
        # defaults to cp1252 and would crash printing it.
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    else:
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
