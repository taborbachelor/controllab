# ControlLab

Virtual commissioning and control-system test environment for industrial automation.

ControlLab simulates a small industrial plant — material bin → gate →
feeder → conveyor → hopper — so deterministic control logic can be run
against it and tested: startup, shutdown, interlocks, fault injection, and
recovery, before any physical equipment exists.

**Status:** early development (Phase 1 — simulation core, complete). No
control layer, UI, or protocol support yet — see the roadmap below.

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

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| 0 | Foundation | done |
| 1 | Simulation core | done |
| 2 | Control (states, sequences, interlocks) | not started |
| 3 | Testing / commissioning scenarios | not started |
| 4 | Fault injection, alarms | not started |
| 5 | Telemetry | not started |
| 6 | Visualization | not started |
| 7 | Protocols (Modbus, OPC UA, MQTT) | not started |
| 8 | AI engineering assistance | not started |
| 9 | Virtual commissioning | not started |

Full detail: `docs/CONTROL-LAB.md` §10.

## License

MIT (planned — not yet added).
