#!/usr/bin/env python
"""Configures a running OpenPLC Runtime container for the ControlLab demo
(docs/CONTROL-LAB.md §10, Phase 7 step 4) through its own web forms --
the same fields a person fills in by hand, so this is just the manual
walkthrough in examples/openplc/README.md, scripted:

  1. log in (OpenPLC's default openplc / openplc)
  2. upload controllab_line.st, register it, compile it
  3. add ControlLab as a "Generic Modbus TCP Device" with the five
     controller ranges from docs/MODBUS-MAP.md
  4. start the PLC

    python examples/openplc/setup_openplc.py --plc http://127.0.0.1:8080 \\
        --container controllab-openplc --controllab-host host.docker.internal

OpenPLC's Modbus master connects with libmodbus's modbus_new_tcp(), which
takes a dotted IPv4 address only -- a hostname fails with "Invalid
argument" and retries forever (found running this demo). So a hostname is
resolved *inside the PLC container* (`--container`, via `docker exec ...
getent`), which is where the name has to mean something.

Stdlib only. The ranges come from LINE_REGISTER_MAP.controller_ranges(),
not a copy, so this can't drift from the map ControlLab serves.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import ipaddress
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from services.protocols.line_map import LINE_REGISTER_MAP  # noqa: E402

ST_FILE = Path(__file__).with_name("controllab_line.st")


class Plc:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(self, path: str) -> str:
        with self.opener.open(self.base + path, timeout=30) as r:
            return r.read().decode("utf-8", "replace")

    def post(self, path: str, fields: dict[str, str]) -> str:
        data = urllib.parse.urlencode(fields).encode()
        with self.opener.open(self.base + path, data=data, timeout=30) as r:
            return r.read().decode("utf-8", "replace")

    def upload(self, path: str, filename: str, content: bytes) -> str:
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            self.base + path, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        with self.opener.open(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")


def wait_for_webserver(plc: Plc, timeout_s: float = 60) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            plc.get("/login")
            return
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


def resolve_in_container(container: str | None, host: str) -> str:
    try:
        return str(ipaddress.IPv4Address(host))
    except ValueError:
        pass
    if container is None:
        raise SystemExit(
            f"{host!r} is a hostname, but OpenPLC's Modbus master (libmodbus modbus_new_tcp) needs an IPv4 "
            "address. Pass --container NAME to resolve it inside the PLC container, or give an IP."
        )
    out = subprocess.run(["docker", "exec", container, "getent", "ahostsv4", host],
                         capture_output=True, text=True, check=True).stdout.split()
    if not out:
        raise SystemExit(f"{host!r} doesn't resolve inside container {container!r}")
    return out[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plc", default="http://127.0.0.1:8080", help="OpenPLC web UI")
    ap.add_argument("--user", default="openplc")
    ap.add_argument("--password", default="openplc")
    ap.add_argument("--controllab-host", default="host.docker.internal", help="ControlLab's address as seen from the PLC")
    ap.add_argument("--controllab-port", default="5020")
    ap.add_argument("--container", default=None, help="the OpenPLC container, to resolve --controllab-host inside it")
    args = ap.parse_args()
    controllab_ip = resolve_in_container(args.container, args.controllab_host)

    plc = Plc(args.plc)
    wait_for_webserver(plc)

    page = plc.post("/login", {"username": args.user, "password": args.password})
    if "Bad credentials" in page or "Dashboard" not in page:
        print("login failed", file=sys.stderr)
        return 1
    print("logged in")

    page = plc.upload("/upload-program", ST_FILE.name, ST_FILE.read_bytes())
    match = re.search(r"name=['\"]prog_file['\"][^>]*value=['\"]([^'\"]+)['\"]", page) or re.search(
        r"value=['\"](\d+\.st)['\"]", page
    )
    if not match:
        print("upload failed: couldn't find the saved file name", file=sys.stderr)
        return 1
    st_name = match.group(1)
    plc.post("/upload-program-action", {
        "prog_name": "ControlLab line", "prog_descr": "ControlLab section 6.2 sequence (examples/openplc)",
        "prog_file": st_name, "epoch_time": str(int(time.time())),
    })
    plc.get(f"/compile-program?file={st_name}")
    print(f"uploaded as {st_name}; compiling...")

    deadline = time.monotonic() + 300
    while True:
        logs = plc.get("/compilation-logs")
        if "Compilation finished successfully" in logs:
            print("compiled")
            break
        if "Compilation finished with errors" in logs:
            print(logs[-3000:], file=sys.stderr)
            return 1
        if time.monotonic() > deadline:
            print("compilation timed out", file=sys.stderr)
            return 1
        time.sleep(2)

    r = LINE_REGISTER_MAP.controller_ranges()
    plc.post("/add-modbus-device", {
        "device_name": "ControlLab", "device_protocol": "TCP", "device_id": "1",
        "device_ip": controllab_ip, "device_port": str(args.controllab_port),
        "device_cport": "", "device_baud": "115200", "device_parity": "None", "device_data": "8",
        "device_stop": "1", "device_pause": "0",
        "di_start": str(r.discrete_inputs[0]), "di_size": str(r.discrete_inputs[1]),
        "do_start": str(r.coils[0]), "do_size": str(r.coils[1]),
        "ai_start": str(r.input_registers[0]), "ai_size": str(r.input_registers[1]),
        "aor_start": str(r.holding_read[0]), "aor_size": str(r.holding_read[1]),
        "aow_start": str(r.holding_write[0]), "aow_size": str(r.holding_write[1]),
    })
    print(f"added ControlLab at {controllab_ip}:{args.controllab_port} ({args.controllab_host}) with ranges {r}")

    plc.get("/start_plc")
    print("PLC started")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
