# ControlLab — Architecture

*Technical companion to [`CONTROL-LAB.md`](CONTROL-LAB.md), which covers the
why. This document covers the how: repository layout, module boundaries,
and the technology stack, as they actually exist — not the aspiration.
Update it whenever the real structure changes.*

## Layers and their boundaries

Full reasoning in `CONTROL-LAB.md` §3. In short:

- **Simulation** (`services/simulation/`) models the physical plant.
- **Control** (not yet built) will operate it through states, sequences,
  and interlocks.
- **Testing** (`tests/`, plus declarative scenarios once they exist) verifies
  behavior.
- **Telemetry** and **Visualization** come later (Phases 5–6).

Control must only ever observe and command Simulation through a shared I/O
tag table (the "I/O image") — never by reaching into simulation objects
directly. **That module doesn't exist yet.** Building it now, with only one
side of the contract in existence, would mean guessing at a shape Control
hasn't actually demanded yet — it's the first thing built in Phase 2.

## Current repository layout

```
ControlLab/
├── CLAUDE.md                       master project context
├── docs/
│   ├── CONTROL-LAB.md               project specification
│   └── ARCHITECTURE.md              this file
├── services/
│   └── simulation/
│       ├── engine/
│       │   └── clock.py             SimClock — fixed-step simulated time
│       └── equipment/
│           ├── motor.py             Motor + MotorState (shared by feeder/conveyor)
│           ├── gate.py              Gate + GateState (travel time, timeout fault)
│           ├── vessel.py            MaterialBin, Hopper (passive mass accumulators)
│           ├── feeder.py            Feeder (Motor + rate output)
│           ├── conveyor.py          Conveyor (Motor + transport-delay belt queue)
│           ├── estop.py             EStop (plant-wide safety trip)
│           └── plant.py             Plant — wires the line together
├── tests/
│   ├── unit/                        one test module per equipment class
│   └── integration/                 full-line scenarios (test_plant.py)
├── pyproject.toml
└── README.md
```

This is deliberately smaller than the target layout in `CLAUDE.md` §17 and
the initial layout sketched in the original project brief.
`services/control/`, `services/testing/`, `scenarios/`, and `examples/`
aren't created yet because they'd be empty — CLAUDE.md §17 itself says not
to pre-create directories just to make the repository look larger than it
is. They get added in the phase that gives them real content (see the
roadmap below).

## Module responsibilities (Phase 1)

- **`SimClock`** — the only source of simulated time. Nothing reads the
  wall clock; `tick_count * dt_s` avoids float drift from repeated
  addition over long runs.
- **`Motor`** — the shared state machine (`STOPPED → STARTING → RUNNING →
  STOPPING`, plus `FAULT` and `ESTOP`) behind both `Feeder` and
  `Conveyor`. Built once here rather than duplicated, because a screw
  feeder and a belt conveyor really are "a motor plus something
  downstream of it."
- **`Gate`** — its own state machine (`CLOSED/OPENING/OPEN/CLOSING/FAULT`),
  because travel time and a timeout-to-fault are meaningfully different
  from a motor's start/stop delay.
- **`MaterialBin` / `Hopper`** — plain mass accumulators, deliberately
  *not* state machines. A vessel's only behavior is its level; giving it
  STARTING/STOPPING states would be state for its own sake.
- **`EStop`** — lives in Simulation, not Control, because a real E-stop
  removes power at the hardware level regardless of what any controller
  commands. `Plant.step()` enforces this directly on the motors, ahead of
  any device logic, every tick.
- **`Plant`** — wires the five devices into the line and moves material
  between them each tick: bin → (gate-gated) feeder discharge → conveyor
  belt (transport delay) → hopper. Tracks `spilled_kg` explicitly, so
  conservation (`accounted_mass_kg() == starting total`) is assertable in
  tests, not just implied by the arithmetic.

Scan-cycle order inside `Plant.step()`: feeder/gate command state from the
*start* of the tick decides how much material is offered to the belt, gate
and motors then advance, and only then does the belt move and the hopper
draw. That mirrors reading inputs before executing logic in a real PLC
scan (`CONTROL-LAB.md` §3.3) — it's a one-tick lag, not a bug.

## Reconciliation notes

Two places this implementation deliberately diverges from the original
project brief pasted into this repo, and why — per the brief's own rule
(`CLAUDE.md` §22: "if you discover a better architecture... explain the
issue and propose the change"):

1. **No `services/simulation/sensors/` or `services/simulation/actuators/`
   split.** The brief's target architecture (`CLAUDE.md` §17) separates
   equipment, sensors, and actuators into parallel module groups. For
   Phase 1, `Motor` models the actuator side (`run_command`) and the
   sensor side (`running`, `fault`) as one object, because that's what
   the real device is — a motor starter doesn't split those concerns
   either. Splitting into separate class hierarchies now would be
   abstraction without a second consumer to justify it (`CLAUDE.md` §6:
   "every layer must earn its existence"). Revisit if/when sensor-noise
   modeling (Phase 4) needs a sensor object independent of the equipment
   it's attached to.
2. **Telemetry moved out of Phase 1.** An earlier draft of
   `CONTROL-LAB.md` scoped a JSONL event log and CSV tag history into its
   first version. The project brief phases telemetry later (Phase 5,
   after Control, Testing, and Fault Injection), and on reflection that's
   right — nothing in Phase 1 needs a structured telemetry subsystem; the
   tests in `tests/` assert on equipment state directly. `CONTROL-LAB.md`
   §10 has been updated to match this document's phase numbering.

## Roadmap (current phase status)

| Phase | Focus | Status |
|---|---|---|
| 0 | Foundation | done — this session |
| 1 | Simulation core | done — this session |
| 2 | Control | not started |
| 3 | Testing / commissioning scenarios | not started |
| 4 | Fault injection, alarms | not started |
| 5 | Telemetry | not started |
| 6 | Visualization | not started |
| 7 | Protocols | not started |
| 8 | AI engineering assistance | not started |
| 9 | Virtual commissioning | not started |

Full detail and "done when" criteria per phase: `CONTROL-LAB.md` §10.

## Technology stack

- **Python 3.12+**, no framework. `pytest` for testing.
- No database, API server, or frontend yet — those are later phases per
  the roadmap above. FastAPI and React+TypeScript are the current intent
  for when that work starts, not a commitment made now.
