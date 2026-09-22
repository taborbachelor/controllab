# ControlLab

Virtual commissioning and control-system test environment for industrial automation.

ControlLab simulates a small industrial plant — material bin → gate →
feeder → conveyor → hopper — so deterministic control logic can be run
against it and tested: startup, shutdown, interlocks, fault injection, and
recovery, before any physical equipment exists.

**Status:** early development. Phases 0-3 complete: simulation core;
Control (the I/O image, device control modules, and the full
`IDLE/STARTING/RUNNING/STOPPING/FAULTED/ESTOPPED` line state machine, all
in Auto mode); and Testing — a declarative `given`/`when`/`expect`
scenario format, 13 scenarios covering 7 of 8 interlocks (the 8th needs
the alarm system, Phase 4), and an interlock coverage matrix
(`python scripts/scenario_report.py`). No telemetry, UI, or protocol
support yet — see the roadmap below.

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
For the interlock coverage matrix specifically:

```bash
python scripts/scenario_report.py            # print
python scripts/scenario_report.py --out coverage_report.md
```

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| 0 | Foundation | done |
| 1 | Simulation core | done |
| 2 | Control (states, sequences, interlocks) | done |
| 3 | Testing / commissioning scenarios | done |
| 4 | Fault injection, alarms | not started |
| 5 | Telemetry | not started |
| 6 | Visualization | not started |
| 7 | Protocols (Modbus, OPC UA, MQTT) | not started |
| 8 | AI engineering assistance | not started |
| 9 | Virtual commissioning | not started |

Full detail: `docs/CONTROL-LAB.md` §10.

## License

MIT (planned — not yet added).
