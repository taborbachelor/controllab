#!/usr/bin/env python
"""Writes the line's Modbus register map as a commissioning document
(docs/CONTROL-LAB.md §10, Phase 7 step 2):

    python scripts/register_map.py                 # print
    python scripts/register_map.py --out docs/MODBUS-MAP.md

Generated from the same RegisterMap the server uses
(services/protocols/line_map.py), and
tests/unit/test_register_map.py fails if the committed
docs/MODBUS-MAP.md no longer matches it -- the document can't drift.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from services.protocols import controller_status
from services.protocols.line_map import LINE_REGISTER_MAP
from services.protocols.register_map import render_markdown
from services.simulation.engine.plant_io import build_line_io_image

TITLE = "ControlLab — Modbus Register Map (bulk-material line)"


def render() -> str:
    io = build_line_io_image()
    LINE_REGISTER_MAP.validate(io)
    return render_markdown(LINE_REGISTER_MAP, io, TITLE, status_notes=controller_status.render_markdown())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    text = render()
    if args.out is None:
        print(text)
    else:
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
