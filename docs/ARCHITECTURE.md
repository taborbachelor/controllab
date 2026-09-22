# ControlLab — Architecture

*Technical companion to [`CONTROL-LAB.md`](CONTROL-LAB.md), which covers the
why. This document covers the how: repository layout, module boundaries,
and the technology stack, as they actually exist — not the aspiration.
Update it whenever the real structure changes.*

## Layers and their boundaries

Full reasoning in `CONTROL-LAB.md` §3. In short:

- **Simulation** (`services/simulation/`) models the physical plant.
- **Control** (`services/control/`) operates it through states,
  sequences, and interlocks — Auto mode only so far.
- **Testing** (`tests/` for hand-written pytest; `services/testing/` +
  `scenarios/` for declarative commissioning scenarios) verifies behavior.
- **Telemetry** and **Visualization** come later (Phases 5–6).

Control must only ever observe and command Simulation through a shared I/O
tag table (the "I/O image") — never by reaching into simulation objects
directly. That table lives at `services/simulation/engine/io_image.py`
(Phase 2 step 1). The write direction each tag allows is enforced in
code: `write_input()` only accepts DI/AI tags (Simulation's to set),
`write_output()` only accepts DO/AO tags (Control's to set), and `read()`
works for either side on any tag — the same asymmetry a real I/O table
has. `Plant` still has zero knowledge of this module; `plant_io.py` is
the only thing that bridges the two (see Module responsibilities below).

`services/control/`'s adherence to this boundary is mechanically
enforced, not just conventional: `tests/unit/test_control_boundary.py`
scans every file in that directory for a reference to
`services.simulation.equipment` and fails if it finds one — verified to
actually catch a violation, not just assumed to, by temporarily adding a
forbidden import, watching the test fail, then reverting it.

**Testing is different from Control here on purpose**: `CONTROL-LAB.md`
§3.3's scan-cycle diagram has Testing apply stimuli (operator commands,
fault injections) directly — so `services/testing/vocabulary.py`
legitimately reaches into `Plant` objects (`plant.conveyor.motor.
trip_now = True`, and so on) the same way a real commissioning test bench
has hooks into the plant it's testing. That's not a boundary violation;
it's a different, and differently-scoped, relationship with Simulation
than Control has.

## Current repository layout

```
ControlLab/
├── CLAUDE.md                       master project context
├── docs/
│   ├── CONTROL-LAB.md               project specification
│   └── ARCHITECTURE.md              this file
├── services/
│   ├── control/
│   │   ├── errors.py                 ControlError + tag-binding validation
│   │   ├── motor_control.py          MotorControl (run/speed command, start-proof)
│   │   ├── gate_control.py           GateControl (open/close command, travel-timeout)
│   │   ├── interlocks.py             Interlocks — the §6.3 table as a query object
│   │   ├── hopper_hysteresis.py      HopperHysteresis — §6.2's on/off feed cycle
│   │   ├── line_state.py             LineState, StartStep enums
│   │   └── line_controller.py        LineController — the whole state machine
│   ├── simulation/
│   │   ├── engine/
│   │   │   ├── clock.py             SimClock — fixed-step simulated time
│   │   │   ├── io_image.py          IOImage — the generic I/O tag table
│   │   │   └── plant_io.py          the line's tags + Plant<->IOImage glue
│   │   └── equipment/
│   │       ├── motor.py             Motor + MotorState (shared by feeder/conveyor)
│   │       ├── gate.py              Gate + GateState (travel time, timeout fault)
│   │       ├── vessel.py            MaterialBin, Hopper (passive mass accumulators)
│   │       ├── feeder.py            Feeder (Motor + rate output)
│   │       ├── conveyor.py          Conveyor (Motor + transport-delay belt queue)
│   │       ├── estop.py             EStop (plant-wide safety trip)
│   │       └── plant.py             Plant — wires the line together
│   └── testing/
│       ├── rig.py                    build_rig()/tick()/run() -- the canonical
│       │                             Control-driven rig, shared by pytest and
│       │                             the scenario runner
│       ├── invariants.py             Invariants -- §7 item 6, checked every scan
│       ├── vocabulary.py             the closed given/when/expect field set
│       ├── scenario.py               Scenario -- YAML loader
│       └── runner.py                 run_scenario() -- executes one Scenario
├── scenarios/
│   ├── startup/normal_start.yaml
│   ├── shutdown/normal_stop.yaml
│   ├── safety/estop_from_running.yaml    (CLAUDE.md §10's own example, made real)
│   └── faults/gate_travel_timeout.yaml
├── tests/
│   ├── unit/                        one test module per equipment/engine/control/
│   │                                 testing class, plus test_control_boundary.py
│   └── integration/                 full-line scenarios (test_plant.py,
│                                     test_plant_io.py, test_device_control.py,
│                                     test_line_controller.py, test_scenarios.py
│                                     -- discovers and runs everything under
│                                     scenarios/)
├── pyproject.toml
└── README.md
```

This is deliberately smaller than the target layout in `CLAUDE.md` §17 and
the initial layout sketched in the original project brief. Alarms
(Phase 4), `scripts/` (the interlock coverage report, Phase 3 step 3),
and `examples/` aren't created yet because they'd be empty — CLAUDE.md
§17 itself says not to pre-create directories just to make the
repository look larger than it is. They get
added in the phase that gives them real content (see the roadmap below).

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

## Module responsibilities (Phase 2 step 1)

- **`IOImage`** (`engine/io_image.py`) — generic, reusable, knows nothing
  about the bulk-material line specifically. `Tag` (name, `TagType`,
  units, description, value) is the record; `TagType` (`DI`/`DO`/`AI`/`AO`)
  carries the write-direction rule as a property (`is_input`), not a
  separate flag, so the enforcement can't drift out of sync with the type
  itself. Every tag must be `define()`d before it can be read or written —
  an undefined-tag access is an `IOImageError`, the same as a wrong-
  direction write or a wrong-type value (bool vs. float, including the
  Python gotcha that `bool` is an `int` subclass — rejected explicitly).
- **`plant_io.py`** — the only module that imports both `Plant` and
  `IOImage`. `build_line_io_image()` defines the 17 tags from
  `CONTROL-LAB.md` §5.3 (a unit test asserts the two stay identical);
  `publish_plant_inputs()`/`apply_plant_commands()` are the one-directional
  halves of the bridge, and `scan()` composes them around one
  `plant.step()` call in the correct order — commands applied before the
  step, inputs published after, so nothing sees stale data one tick early
  or late. `apply_plant_commands()` goes through each device's own
  `command()` method (e.g. `Feeder.command()`'s 0–100 clamp) rather than
  setting internal attributes directly, so the I/O boundary can't bypass
  validation the device itself already enforces.

## Module responsibilities (Phase 2 step 2)

- **`MotorControl` / `GateControl`** (`services/control/`) — the
  Control-side counterparts to `Motor`/`Gate`, but they know nothing
  about those classes; they only read/write tags on the `IOImage` they're
  given. Each takes tag names in its constructor (not hardcoded to this
  line's actual tags — the unit tests build them against a bare two-
  tag/three-tag `IOImage` to prove that), and validates each bound tag's
  type immediately via `errors.require_tag_type()`, so a wiring mistake
  fails at construction, not partway through a scenario.
- Each supervises exactly one thing its device can't report about
  itself, by timing: `MotorControl.start_proof_fault` (commanded to run,
  `RUNNING` never confirms) and `GateControl.travel_fault` (commanded to
  a position, the matching limit switch never makes) — both default to
  the 3s/5s windows `CONTROL-LAB.md` §6.2 already specifies. Both also
  pass through a fault the device *does* report itself
  (`MotorControl.faulted`) with no timing involved.
- Both fault flags **latch** until the command changes or `clear_fault()`
  is called — deliberately not auto-cleared just because the device
  eventually confirms/arrives late while still commanded. Tested
  explicitly in both directions (`test_dropping_the_run_command_clears_
  the_fault` vs. `test_late_confirmation_does_not_clear_an_already_
  raised_fault`), since it's an easy behavior to get backwards silently.
- Detecting a fault is these modules' whole job. Deciding what to do
  about one — stop the line, go to FAULTED — belongs to line control
  (Phase 2 step 3), kept out of these modules on purpose.

## Module responsibilities (Phase 2 step 3 — Control complete)

- **`Interlocks`** (`services/control/interlocks.py`) — a query object,
  not a state machine: no memory, no opinion about what to do with a
  trip. Reads the six field-I/O tags device-control doesn't cover
  (`ES-001`, `LSL-101`, `LSH-105`, `LSHH-105`, `WT-105`, `ZSS-104`)
  directly, and combines `MotorControl.running` with `ZSS-104` into
  `conveyor_confirmed_running` — the one check that specifically catches
  a belt slip (`CONTROL-LAB.md` §5.4), which `MotorControl` alone can't
  see since the motor genuinely is energized. `hopper_level_pct` is
  computed from `WT-105` (raw weight) and a configured `hopper_capacity_kg`
  constant, the same way a real control program is commissioned with a
  vessel's known engineering capacity rather than reading it off a tag.
- **`HopperHysteresis`** (`hopper_hysteresis.py`) — pure logic, zero I/O
  dependency: floats and bools in, a bool out. The whole "controller" for
  now is on/off with two setpoints; `CONTROL-LAB.md` §6.2 is explicit that
  a real rate controller is a later refinement, not an oversight.
- **`LineController`** (`line_controller.py`) — owns the three
  device-control objects and an `Interlocks`/`HopperHysteresis` pair, and
  is the only thing a driver needs to call once per tick
  (`line.scan(dt)`, which itself scans the three device-control modules
  first). Every state handler continuously re-asserts its own safe output
  set every scan (all-off in `IDLE`/`FAULTED`/`ESTOPPED`, not just once on
  entry) — cheap, and it means a stray write from anywhere else can't
  survive a tick undetected.
- **The two-tier fault-clearing rule in `reset()`** is the most
  deliberate decision in this module: a *pass-through* condition (hopper
  high-high, a motor's own fault tag) blocks `reset()` until it's
  genuinely no longer true, because Control can check it directly. A
  *latched timing diagnostic* (`MotorControl.start_proof_fault`,
  `GateControl.travel_fault`) has no such independent signal — Control
  can only re-test it by trying again — so `reset()` clears those
  unconditionally and lets the next start attempt fail on its own if the
  real problem is still there. Tested explicitly in both directions, plus
  a dedicated "reset succeeds, retry re-faults" test proving the second
  half isn't a loophole.
- **`stop()` mid-`STARTING`** aborts the sequence rather than being
  silently dropped — a real gap found writing tests for this, not
  designed in from the start. The fix reuses `_begin_stop_sequence()`
  unchanged: it already drops feeder/gate unconditionally (a no-op if
  they were never commanded) and purges with the conveyor, so it's safe
  to call from any start step.

## Retroactive Phase 1 fix (found building Phase 2 step 3)

`LineController.ESTOPPED` needs to hold every command at `False` while an
E-stop is active — straightforward. But bringing a motor's *state* back
from `ESTOP` to `STOPPED` once the E-stop physically releases turned out
to have nowhere correct to live: `Motor.estop_reset()` is a raw
simulation-object call, and Control may only ever touch Simulation
through the I/O image (`CONTROL-LAB.md` §3.2) — so `LineController`
architecturally *cannot* call it, no matter how the state machine is
written.

The fix belongs in `Plant.step()`: a real E-stop's safety relay re-arms
the motor starters automatically the instant the button releases,
independent of whatever a PLC program does or doesn't do. `Plant.step()`
now calls `estop_reset()` on both motors unconditionally whenever
`estop.healthy` — it's a no-op if a motor isn't in `ESTOP`, and it never
restarts anything (`estop_reset()` only ever leaves `ESTOP` for
`STOPPED`; a run command is still required separately). This is the
correct split of responsibility, not a workaround: Simulation handles the
hardware-realistic "available again," Control handles the
operator-realistic "not running again without being asked."

Two Phase 1/step-1 tests previously did this by hand
(`plant.<device>.motor.estop_reset()`, standing in for "Testing" since no
Control layer existed yet to do it properly). Both calls were removed and
the tests re-verified to produce identical outcomes — the auto-reset
doesn't change behavior, it just moves who's responsible for it to where
it actually belongs.

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

## Module responsibilities (Phase 3 step 1)

- **`services/testing/rig.py`** — the single canonical Control-driven
  rig builder. `tests/integration/test_line_controller.py` and the
  scenario runner both use it now; before this step, the former had its
  own inline copy of the same config, which is exactly the kind of thing
  that quietly drifts.
- **`services/testing/vocabulary.py`** — the closed field vocabulary.
  Every `given`/`when` key maps to a real, direct action on the rig
  (mirroring the exact fault-injection hooks already proven throughout
  `tests/`); every `expect` key maps to a real observation. An unknown
  key is a hard `ScenarioError` — this module has no silent fallback.
- **`services/testing/invariants.py`** — continuous checks, distinct in
  kind from a scenario's own `expect`: a tripped invariant means the
  system did something actively wrong, not just "not yet right," so it
  fails the run immediately rather than waiting out the timeout.
  Deliberately covers only 3 of §7 item 6's 4 invariants — see the file's
  own docstring for why "no spillage during normal start/stop" belongs
  in a scenario's `expect` instead of here.
- **`services/testing/runner.py`** — the one subtlety worth remembering:
  every check (invariants and `expect` alike) happens *after* a tick,
  never before. `CONTROL-LAB.md` §3.3's scan cycle has Testing's stimulus
  and Simulation's reaction happen within the same tick; checking first
  observes a moment that exists only in this function's call order, not
  one the real system passes through. Found by the first scenario ever
  run against this code, not designed in up front.

## Roadmap (current phase status)

| Phase | Focus | Status |
|---|---|---|
| 0 | Foundation | done |
| 1 | Simulation core | done |
| 2 | Control | done |
| 3 | Testing / commissioning scenarios | in progress — step 1/3 done (scenario format, runner, invariants) |
| 4 | Fault injection, alarms | not started |
| 5 | Telemetry | not started |
| 6 | Visualization | not started |
| 7 | Protocols | not started |
| 8 | AI engineering assistance | not started |
| 9 | Virtual commissioning | not started |

Full detail and "done when" criteria per phase: `CONTROL-LAB.md` §10.

## Technology stack

- **Python 3.12+**, no framework. `pytest` for testing.
- **`pyyaml`** (Phase 3 step 1) — the first real dependency beyond
  pytest. Justified, not reflexive: it matches `CLAUDE.md` §10's own
  illustrative scenario format, and is meaningfully more readable than
  JSON for hand-authored commissioning-style test files (comments,
  less punctuation noise). "Minimal dependencies" (`CONTROL-LAB.md`
  §3.4) means justified, not zero.
- No database, API server, or frontend yet — those are later phases per
  the roadmap above. FastAPI and React+TypeScript are the current intent
  for when that work starts, not a commitment made now.
