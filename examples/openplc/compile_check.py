#!/usr/bin/env python
"""Uploads controllab_line.st to a running OpenPLC and compiles it,
printing the compiler's errors -- a quick syntax check against OpenPLC's
real IEC 61131-3 compiler (MatIEC) without touching the device config.

    python examples/openplc/compile_check.py --plc http://127.0.0.1:8080
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from setup_openplc import ST_FILE  # noqa: E402

from services.protocols.openplc import OpenPLCWeb  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plc", default="http://127.0.0.1:8080")
    args = ap.parse_args()
    plc = OpenPLCWeb(args.plc)
    plc.login("openplc", "openplc")
    page = plc.upload("/upload-program", ST_FILE.name, ST_FILE.read_bytes())
    name = re.search(r"value=['\"](\d+\.st)['\"]", page).group(1)
    plc.post("/upload-program-action", {"prog_name": "compile check", "prog_descr": "", "prog_file": name,
                                         "epoch_time": str(int(time.time()))})
    plc.get(f"/compile-program?file={name}")
    for _ in range(150):
        logs = plc.get("/compilation-logs")
        if "Compilation finished" in logs:
            break
        time.sleep(2)
    errors = [line for line in logs.splitlines() if "error" in line.lower()]
    print("\n".join(errors[:20]) or "no errors")
    ok = "Compilation finished successfully" in logs
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
