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
commissioning check over Modbus ([`examples/openplc/`](examples/openplc/README.md)). Phase 9
(Virtual commissioning) complete: the same scenario suite runs against a
free-running external controller in real time, limits in plant time with
a stated I/O latency tolerance, and repeat passes reporting the spread;
against OpenPLC it passes 45/45 runs over 3 passes. A controller that
doesn't publish ControlLab's status block gets *not observable* instead
of a guess, and an I/O map file lets the plant be served at the addresses
an existing PLC program already uses.

### Optional AI assistance (Phase 8)

Not needed for anything above. With `pip install -e ".[ai]"` and
`ANTHROPIC_API_KEY` set:

```bash
python scripts/ai_generate.py "cover gate faults during shutdown" --count 3
python scripts/ai_analyze.py path/to/failing_scenario.yaml
```

Generated scenarios are *proposals*: they land in `candidates/` and every
one goes through a deterministic review gate (`scripts/review_candidates.py`)
that rejects broken, duplicate, non-deterministic, and vacuous tests. A
candidate becomes a test only when an engineer moves it into `scenarios/`.
Run analysis sends a bounded digest of a failed run, never the full
telemetry, and returns hypotheses marked unverified. The API key is read
from the environment per call and never stored.

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

To run the whole scenario suite against a free-running controller in
real time, the way you would against a PLC (Phase 9):

```bash
python scripts/scenario_report.py --realtime reference --speed 4       # our controller, free-running
python scripts/scenario_report.py --realtime openplc --repeat 3        # a real PLC runtime, see examples/openplc
```

Limits are still checked in plant time, with a stated I/O latency
tolerance; a result met only inside it is reported as such, and repeat
passes report the response-time spread. For a controller that doesn't
publish ControlLab's status block, `--no-status` reports expectations on
its internal state as *not observable* rather than reading registers
nobody wrote.

To commission a PLC program whose I/O configuration already exists,
describe its addresses in an I/O map file instead of changing the
program: see [`configs/io/`](configs/io/) (`line.yaml` is the built-in
map, `relocated.yaml` the same line at remote-I/O offsets). `--map FILE`
on `scenario_report.py --realtime`, `scripts/register_map.py` (the map
document and PLC master configuration), and
`examples/openplc/setup_openplc.py`. A map without a status block
declares a controller without one. Against OpenPLC running a
Structured Text port of the controller, all 15 scenarios pass in all 3
passes: [`examples/openplc/COMMISSIONING-REPORT.md`](examples/openplc/COMMISSIONING-REPORT.md).

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
| 8 | AI engineering assistance | done (optional) |
| 9 | Virtual commissioning | done |

Full detail: `docs/CONTROL-LAB.md` §10.

## License

MIT (planned — not yet added).
