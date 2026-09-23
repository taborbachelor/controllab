# ControlLab

Virtual commissioning and control-system test environment for industrial automation.

ControlLab simulates a small industrial plant — material bin → gate →
feeder → conveyor → hopper — so deterministic control logic can be run
against it and tested: startup, shutdown, interlocks, fault injection, and
recovery, before any physical equipment exists.

**Status:** early development. Phases 0-4 complete: simulation core;
Control (the I/O image, device control modules, and the full
`IDLE/STARTING/RUNNING/STOPPING/FAULTED/ESTOPPED` line state machine, all
in Auto mode); Testing — a declarative `given`/`when`/`expect` scenario
format, 15 scenarios covering all 8 interlocks, and an interlock
coverage matrix (`python scripts/scenario_report.py`) reporting 8/8, 0
gaps; and alarm management — latching, first-out, and acknowledge, wired
into `LineController` so a start is refused while any trip-class alarm
is latched and unacknowledged, independent of `reset()`. Two additional
fault hooks from the original spec (feeder jam, sensor failure) are
deliberately deferred — see the roadmap below. Phase 5 (Telemetry)
complete: a generic, IOImage-only sampled tag-value recorder
(`TagHistory` + `write_csv()`), a state/alarm diffing event log
(`EventLog` + `write_jsonl()`), operator-command capture through an
optional sink on `LineController`, and a generated Markdown
commissioning report — pass/fail, response time vs. each scenario's
limit, the interlock coverage matrix, and every scenario's recorded
event/alarm sequence. Phase 6 (Visualization) complete: a
self-contained HTML replay viewer for any scenario run (line mimic,
alarm board, event log, and I/O tags, scrubbable tick by tick) and a
live localhost dashboard: the line running in real time, operator
commands, a separate fault-injection panel, and one-click download of
the session as a replay. Phase 7 (Protocols) complete: a
stdlib Modbus TCP server, tested against the Modbus spec's own examples
and against `pymodbus`'s client, serving the line's I/O over a documented
register map ([`docs/MODBUS-MAP.md`](docs/MODBUS-MAP.md)), and an
external-controller mode where the plant runs with no built-in controller
and ControlLab's own controller, unmodified, drives it from a separate
process over Modbus, with a comm-loss watchdog that stops the plant if
the controller dies. The full scenario suite passes against that external
controller (`python scripts/scenario_report.py --external`), observing it
only through status registers it publishes, with event logs identical to
the built-in run. And a real PLC runtime drives it too: OpenPLC in Docker,
running a Structured Text port of the controller, passes a real-time
commissioning check over Modbus ([`examples/openplc/`](examples/openplc/README.md)).

## Documentation

- [`docs/CONTROL-LAB.md`](docs/CONTROL-LAB.md) — full project specification:
  purpose, architecture, initial equipment, operating modes, testing
  philosophy, non-goals, roadmap.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — repository layout,
  module responsibilities, technology stack.
- [`CLAUDE.md`](CLAUDE.md) — master project context for AI-assisted
  development on this repository.

## Development

Requires Python 3.12+.

```bash
pip install -e ".[dev]"
pytest
```

`pytest` runs everything, including every scenario under `scenarios/`.
For the interlock coverage matrix and the commissioning report:

```bash
python scripts/scenario_report.py            # print
python scripts/scenario_report.py --out coverage_report.txt
python scripts/scenario_report.py --markdown commissioning_report.md
```

The Markdown commissioning report is deterministic: the same code
produces a byte-identical file every run.

To watch a scenario play back on a line mimic:

```bash
python scripts/replay.py scenarios/safety/estop_from_running.yaml   # writes estop_from_running.replay.html
```

Open the file in any browser. It needs no server and no network.

To run the line live:

```bash
python scripts/dashboard.py        # then open http://127.0.0.1:8000
```

Start it, inject a fault, and walk through the recovery (clear the
fault, reset the device at the field, acknowledge, reset, start) the
way a commissioning engineer would. Localhost only, no dependencies
beyond the standard library. Add `--modbus-port 5020` to also expose the
line to any Modbus TCP client (a SCADA package, Modbus Poll, a PLC):
sensors and outputs readable, operator commands on HMI coils 100-103.

To run the controller as a separate program that only talks Modbus:

```bash
python scripts/dashboard.py --external        # terminal 1: the plant, no controller
python scripts/external_controller.py         # terminal 2: the controller, over Modbus TCP
```

Press Start on the dashboard; kill the controller mid-run and the
watchdog stops the plant within a second.

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| 0 | Foundation | done |
| 1 | Simulation core | done |
| 2 | Control (states, sequences, interlocks) | done |
| 3 | Testing / commissioning scenarios | done |
| 4 | Fault injection, alarms | done (feeder jam / sensor failure hooks deferred) |
| 5 | Telemetry | done |
| 6 | Visualization | done |
| 7 | Protocols (Modbus + external controller mode) | done |
| 8 | AI engineering assistance | in progress (step 1: a deterministic review gate for candidate scenarios) |
| 9 | Virtual commissioning | not started |

Full detail: `docs/CONTROL-LAB.md` §10.

## License

MIT (planned — not yet added).
