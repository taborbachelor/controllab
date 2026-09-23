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
format, 14 scenarios covering all 8 interlocks, and an interlock
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
event/alarm sequence. No UI or protocol support yet.

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

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| 0 | Foundation | done |
| 1 | Simulation core | done |
| 2 | Control (states, sequences, interlocks) | done |
| 3 | Testing / commissioning scenarios | done |
| 4 | Fault injection, alarms | done (feeder jam / sensor failure hooks deferred) |
| 5 | Telemetry | done |
| 6 | Visualization | not started |
| 7 | Protocols (Modbus, OPC UA, MQTT) | not started |
| 8 | AI engineering assistance | not started |
| 9 | Virtual commissioning | not started |

Full detail: `docs/CONTROL-LAB.md` §10.

## License

MIT (planned — not yet added).
