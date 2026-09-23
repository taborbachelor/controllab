# ControlLab + OpenPLC — virtual commissioning of real PLC logic

This example runs a **real PLC runtime** — [OpenPLC v3](https://github.com/thiagoralves/OpenPLC_v3),
in Docker — against the ControlLab plant over Modbus TCP. ControlLab plays the plant and its
remote I/O; OpenPLC runs [`controllab_line.st`](controllab_line.st), an IEC 61131-3 Structured
Text port of ControlLab's own line controller. Nothing is shared between the two except the
register map in [`docs/MODBUS-MAP.md`](../../docs/MODBUS-MAP.md).

It is a manual, documented demo (docs/CONTROL-LAB.md §10, Phase 7 step 4) — OpenPLC is not
a dependency of the automated test suite. What *is* in the suite:
`tests/unit/test_openplc_program.py` checks every located variable in the `.st` file against
the register map, so the program's I/O addresses can't drift from what ControlLab serves.

```
 ┌──────────── Docker ────────────┐          ┌─────────────── host ────────────────┐
 │ OpenPLC Runtime                │  Modbus  │ ControlLab                          │
 │  controllab_line.st, 100 ms    │   TCP    │  scripts/dashboard.py --external    │
 │  Modbus master, polls 5 ranges ├─────────►│  plant, no built-in controller      │
 │  web UI :8080 (localhost only) │          │  Modbus server :5020 (localhost)    │
 └────────────────────────────────┘          │  dashboard :8000 (localhost)        │
                                             └─────────────────────────────────────┘
```

## Run it

Prerequisites: Docker, Python 3.12+, this repository installed (`pip install -e ".[dev]"`).

**1. Build the OpenPLC image** from OpenPLC's own repository and Dockerfile:

```bash
git clone --depth 1 https://github.com/thiagoralves/OpenPLC_v3.git
cd OpenPLC_v3
git config core.autocrlf false   # Windows: keep the Linux build's line endings intact
docker build -t openplc:v3 .
```

**2. Start the plant** — no built-in controller, outputs owned over Modbus, 1× real time
(the PLC's task is a real 100 ms, so the plant must run at 1× too):

```bash
python scripts/dashboard.py --external --port 8000 --modbus-port 5020 --speed 1
```

**3. Start OpenPLC**, web UI published on localhost only. `--privileged` from OpenPLC's
README is only needed for serial/hardware devices — not for this TCP-only demo:

```bash
docker run -d --name controllab-openplc -p 127.0.0.1:8080:8080 openplc:v3
```

**4. Configure it** — upload and compile the program, add ControlLab as a Modbus slave
device, start the PLC:

```bash
python examples/openplc/setup_openplc.py --container controllab-openplc --controllab-host host.docker.internal
```

Or by hand at http://127.0.0.1:8080 (login `openplc` / `openplc`):
*Programs → Upload Program* → `controllab_line.st`; then *Slave Devices → Add new device*:
protocol *Generic Modbus TCP Device*, IP = `host.docker.internal` **resolved to an IP
inside the container** (see findings), port 5020, and the five ranges from the map's
*Controller view* table:

| Field | Start | Size | PLC addresses |
|---|---:|---:|---|
| Discrete Inputs (%IX100.0) | 0 | 11 | `%IX100.0`–`%IX101.2` |
| Coils (%QX100.0) | 0 | 3 | `%QX100.0`–`%QX100.2` |
| Input Registers (%IW100) | 0 | 2 | `%IW100`–`%IW101` |
| Holding Registers - Read (%IW100) | 100 | 1 | `%IW102` (after the input registers) |
| Holding Registers - Write (%QW100) | 0 | 8 | `%QW100`–`%QW107` |

Then *Dashboard → Start PLC*.

**5. Run the commissioning checks** — or just press buttons on the dashboard at
http://127.0.0.1:8000 and watch the PLC run the line:

```bash
python examples/openplc/run_demo.py --dashboard http://127.0.0.1:8000
```

`run_demo.py` drives the plant through the dashboard's API (operator commands, fault
injection) and reads the PLC's decisions back from the status registers it publishes —
the same observation path the scenario suite uses in external mode, but against a real
PLC runtime free-running on its own clock, so each check waits with a real-time tolerance.
[`TRANSCRIPT.txt`](TRANSCRIPT.txt) is a recorded run.

## What it checks

Power-up · normal start (downstream first) · material reaching the hopper · feeder trip →
FAULTED with reason and first-out · reset refused while the drive is still faulted · field
recovery (clear cause, reset the drive, acknowledge, reset, start) · E-stop → ESTOPPED ·
release, acknowledge, reset · normal stop (upstream first, then the belt purge).

Recorded, three consecutive runs, all passing:

| Response | OpenPLC, real time | Reference controller, simulated lockstep |
|---|---:|---:|
| Start → RUNNING | 1.96–2.00 s | 1.50 s |
| Feeder trip → FAULTED | 0.19–0.29 s | 0.20 s |
| Stop → IDLE (purge) | 1.87–2.02 s | 2.10 s |

The start sequence is slower in real time because each of its three hand-offs (conveyor
proven → gate open → feeder running) waits for a Modbus poll and a PLC scan on each side —
real I/O latency the lockstep simulation deliberately doesn't have.

## Findings from running it

Each was found by running this against the real runtime, not anticipated:

- **The step-2/3 register map wasn't pollable by a PLC master.** OpenPLC polls one contiguous
  range per table, never reads coils, and has separate holding read/write ranges; the map
  had HMI requests on coils and the status block unreachable from the analog-output write
  range. Fixed before any OpenPLC code ran (Phase 7 step 4a): the controller view is now
  five contiguous ranges, enforced by `RegisterMap.validate()`.
- **IEC 61131-3 is stricter than it looks.** A `VAR` block holds located (`AT %…`) or
  ordinary variables, never both; and identifiers are case-insensitive, so a Python-style
  `PURGE_SCANS` constant collides with a `purge_scans` variable. MatIEC rejected the first
  draft on both; `test_openplc_program.py` now guards the second.
- **OpenPLC's Modbus master needs an IP address, not a hostname.** libmodbus's
  `modbus_new_tcp()` fails on `host.docker.internal` with "Invalid argument" and retries
  forever. `setup_openplc.py` resolves the name inside the container.
- **The PLC powers up ESTOPPED — correctly.** Its first scans run before its first I/O poll
  completes, so every input reads 0, and `ES-001` is fail-safe (1 = healthy): no data reads
  as a pressed E-stop, and `ES-001.TRIP` latches as first-out. That is exactly what a real
  PLC does when it boots before its remote I/O rack answers; the operator acknowledges and
  resets. ControlLab's Python reference controller never showed this only because it reads
  its inputs once before its first scan.
- **Reaching ControlLab from the container needed no network exposure.** Docker Desktop
  forwards `host.docker.internal` to the host's loopback, so the plant's Modbus server stays
  bound to 127.0.0.1.

## Security note

Modbus has no authentication, and OpenPLC ships with default credentials. Everything here
binds to localhost; don't publish either port on a network.
