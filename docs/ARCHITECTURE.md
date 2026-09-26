# ControlLab — Architecture

*Technical companion to [`CONTROL-LAB.md`](CONTROL-LAB.md), which covers the
why. This document covers the how: repository layout, module boundaries,
and the technology stack, as they actually exist — not the aspiration.
Update it whenever the real structure changes.*

## The validation workflow, and how the runtimes relate

The whole system exists to answer one question about a control program:
does it still do what the machine requires? Everything below is arranged
around that loop:

```
 scenarios/*.yaml  ──►  services/testing/runner.py  ──►  ScenarioResult  ──►  services/testing/verdict.py
 (setup, actions,        execute(rig, scenario,           (per-stage timing,     RunSummary: every check
  faults, expected        step, invariants, telemetry)    failed stage,          MATCH / MISMATCH with the
  behavior, limits,       invariants checked every        expected vs actual,    actual value, first-out,
  recovery stages)        tick                            events, tag history)   first divergence
                                   │
                    step() is the only thing that differs per runtime
        ┌──────────────────────────┼──────────────────────────────────┐
        ▼                          ▼                                  ▼
 in-process lockstep        external lockstep                   real time
 run_scenario()             run_scenario(external=True)         realtime.run_realtime()
 LineController scans,      the same LineController in          the plant paced on the wall clock,
 then the plant steps       another thread/process, reached     served as Modbus remote I/O; the
                            only through the Modbus register    controller (OpenPLC, or the reference
                            map (services/testing/external.py)  one) free-runs and polls it
        └──────────────────────────┼──────────────────────────────────┘
                                   ▼
                  the same Plant, the same I/O image, the same invariants
```

- **One runner, three runtimes.** `runner.execute()` is shared. Each
  runtime passes a different `step()`, so a scenario file never changes
  between them. Lockstep runs are deterministic, and two of them (in-process
  vs over Modbus) are compared event for event. A real-time run is judged in
  plant time with a stated I/O latency allowance, and compared by verdict and
  checks.
- **Faults go to the plant, never the controller.**
  `services/testing/vocabulary.py` applies stimuli to `Plant` objects. The
  controller must notice them through its I/O.
- **Regressions are fixtures.** `services/testing/regressions.py` holds
  deliberately broken `LineController` subclasses, built only when asked for
  by name (`run_scenario(..., line_cls=)`). `services/control/` is never
  modified to demonstrate a failure.
- **Front ends only present.**
  - `controllab test` (`services/cli.py`) and the dashboard
    (`services/visualization/verify.py`) call the runner through the paths
    above and render its `RunSummary`.
  - The dashboard's Python-runtime verification runs `execute()` on the live
    session's own line (`LiveSession.run_live`), and is tested to record the
    same events as the suite's run.
- **AI sits outside the loop.** `services/ai/` reads a finished result
  (starting from the same first divergence) and writes files for an
  engineer. Nothing in the loop above imports it.

## Layers and their boundaries

Full reasoning in `CONTROL-LAB.md` §3. In short:

- **Simulation** (`services/simulation/`) models the physical plant.
- **Control** (`services/control/`) operates it through states,
  sequences, and interlocks — Auto (the sequences) and Manual (device by
  device, every protection kept).
- **Testing** (`tests/` for hand-written pytest; `services/testing/` +
  `scenarios/` for declarative commissioning scenarios) verifies behavior.
- **Telemetry** (`services/telemetry/`, Phase 5, done) observes
  Simulation and Control from outside, pull/diff, the same non-invasive
  relationship Testing already has. **Visualization** (`services/visualization/`,
  Phase 6, done) replays recorded telemetry (reads Telemetry only) and
  serves the live dashboard (drives the rig through Testing's vocabulary).

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
│   ├── ARCHITECTURE.md              this file
│   └── AI.md                        the optional AI engineering assistance (Phase 8)
├── services/
│   ├── control/
│   │   ├── errors.py                 ControlError + tag-binding validation
│   │   ├── motor_control.py          MotorControl (run/speed command, start-proof)
│   │   ├── gate_control.py           GateControl (open/close command, travel-timeout)
│   │   ├── interlocks.py             Interlocks — the §6.3 table as a query object
│   │   ├── hopper_hysteresis.py      HopperHysteresis — §6.2's on/off feed cycle
│   │   ├── line_state.py             LineMode, LineState, StartStep, StartInhibit
│   │   ├── line_controller.py        LineController — the whole state machine, both modes
│   │   └── alarms.py                 Alarm, AlarmManager — latch/first-out/ack (Phase 4 step 1)
│   ├── simulation/
│   │   ├── engine/
│   │   │   ├── clock.py             SimClock — fixed-step simulated time
│   │   │   ├── io_image.py          IOImage — the generic I/O tag table
│   │   │   └── plant_io.py          the line's tags + Plant<->IOImage glue
│   │   └── equipment/
│   │       ├── motor.py             Motor + MotorState (shared by feeder/conveyor)
│   │       ├── instruments.py       Instruments -- stuck / failed sensors (Phase 4)
│   │       ├── gate.py              Gate + GateState (travel time, timeout fault)
│   │       ├── vessel.py            MaterialBin, Hopper (passive mass accumulators)
│   │       ├── feeder.py            Feeder (Motor + rate output)
│   │       ├── conveyor.py          Conveyor (Motor + transport-delay belt queue,
│   │       │                          advancing only while the belt moves)
│   │       ├── estop.py             EStop (plant-wide safety trip)
│   │       └── plant.py             Plant — wires the line together
│   ├── testing/
│   │   ├── rig.py                    build_rig()/tick()/run() -- the canonical
│   │   │                             Control-driven rig, shared by pytest and
│   │   │                             the scenario runner
│   │   ├── invariants.py             Invariants -- §7 item 6, checked every scan
│   │   ├── vocabulary.py             the closed given/when/expect field set
│   │   ├── scenario.py               Scenario -- YAML loader
│   │   ├── runner.py                 run_scenario() -- executes one Scenario,
│   │   │                             always recording its telemetry events
│   │   ├── report.py                 the interlock coverage matrix (pure logic)
│   │   ├── candidates.py             review(): the gate every candidate scenario
│   │   │                             passes before an engineer sees it (Phase 8 step 1)
│   │   ├── external.py               ObservedLine / RemoteLine + build_external_rig():
│   │   │                             the suite against the external controller (Phase 7 step 3b)
│   │   ├── realtime.py               RealtimePlant + run_realtime(): the suite against a
│   │   │                             FREE-RUNNING external controller, plant paced in
│   │   │                             real time (Phase 9 step 1)
│   │   ├── commissioning_report.py   render_markdown() -- the Markdown
│   │   │                             commissioning report (pure logic, Phase 5 step 4)
│   │   └── report_export.py          report_dict() / render_html() -- the same report as
│   │                                 JSON and print-ready HTML; build_info() stamp
│   └── telemetry/
│       ├── tag_history.py            TagHistory -- generic IOImage tag-value sampler
│       │                             (Phase 5 step 1); write_csv() exports it
│   │   └── events.py                 EventLog -- state/alarm diffing observer
│   │                                  (Phase 5 step 2) + command capture (step 3);
│   │                                  write_jsonl() exports it
│   ├── ai/                           OPTIONAL (Phase 8; the [ai] extra): nothing else imports it
│   │   ├── provider.py               Provider protocol + AnthropicProvider (lazy SDK import,
│   │   │                              key only from ANTHROPIC_API_KEY, per call)
│   │   ├── limits.py                 every hard limit, as constants
│   │   ├── context.py                bounded, deterministic line description for generation
│   │   ├── generate.py               proposals -> candidates/ -> the review gate
│   │   └── analyze.py                bounded run digest -> unverified hypotheses
│   ├── protocols/
│   │   ├── modbus.py                 stdlib Modbus TCP server: DataStore interface,
│   │   │                              pure PDU/ADU handling, ModbusServer (Phase 7 step 1)
│   │   ├── register_map.py           generic: Point/HmiCoil/RegisterMap.validate(),
│   │   │                              IOImageDataStore, render_markdown() (step 2)
│   │   ├── line_map.py               this line's hand-written addresses (step 2)
│   │   ├── external_controller.py    the reference external controller: our LineController
│   │   │                              over ModbusIOSync (step 3a)
│   │   ├── controller_status.py      status block codec + code tables (step 3b)
│   │   ├── openplc.py                OpenPLC web client + OpenPLCController (cold
│   │   │                              restart between scenarios, Phase 9 step 2)
│   │   ├── map_file.py               load_map(): a YAML I/O map file -> a validated
│   │   │                              RegisterMap (Phase 9 step 4)
│   │   ├── mqtt.py                   stdlib MQTT 3.1.1 client + TelemetryPublisher
│   │   │                              (by exception, retained, last will)
│   │   └── opcua_server.py           OPC UA server over asyncua (optional extra):
│   │                                  tags, controller state, command methods, setpoints
│   └── visualization/
│       ├── replay.py                 build_frames()/build_replay()/render_html() --
│       │                             replay reconstructed from telemetry (Phase 6 step 2)
│       ├── replay_template.html      the replay viewer page
│       ├── live.py                   LiveSession / Pacer / make_handler() -- the live
│       │                             dashboard (Phase 6 step 3)
│       ├── live_template.html        the live dashboard page
│       ├── page.py                   assemble(): inlines the shared pieces below
│       ├── hmi.css, hmi.js           shared styles + mimic/alarm/tag renderers
│       └── mimic.svg.html            the shared line mimic (inline SVG)
├── examples/
│   ├── ai_assist/                    the whole AI loop end to end: run_flow.py, a labelled
│   │                                  scripted stand-in provider, canned/ answers (Phase 8)
│   └── openplc/                      a real PLC runtime (OpenPLC, Docker) running a
│                                      Structured Text port of the controller against
│                                      the plant: controllab_line.st, setup_openplc.py,
│                                      run_demo.py, README.md, TRANSCRIPT.txt, and
│                                      COMMISSIONING-REPORT.md (the suite against it,
│                                      Phase 9 step 2)
├── configs/
│   └── io/                           I/O map files (Phase 9 step 4): line.yaml (the
│                                      built-in map, tested identical to line_map.py)
│                                      and relocated.yaml (the line at remote-I/O offsets)
├── scenarios/
│   ├── startup/normal_start.yaml
│   ├── shutdown/normal_stop.yaml
│   ├── safety/                       estop_from_running.yaml (CLAUDE.md §10's
│   │                                  own example, made real), estop_blocks_start.yaml
│   └── faults/                       11 files -- one or more per §6.3 interlock row
│                                      (gate_travel_timeout.yaml, hopper_high_high_
│                                      blocks_start.yaml, bin_low_blocks_start.yaml,
│                                      bin_low_while_running_warns_only.yaml,
│                                      belt_slip_stops_feeder.yaml, hopper_high_high_
│                                      trips_running.yaml, conveyor_fail_to_start.yaml,
│                                      feeder_fail_to_start.yaml, conveyor_trip_while_
│                                      running.yaml, feeder_trip_while_running.yaml,
│                                      unacknowledged_alarm_blocks_start.yaml)
├── scripts/
│   ├── scenario_report.py            thin CLI: runs every scenario, prints
│   │                                  report.py's coverage matrix, --out FILE,
│   │                                  --markdown FILE.md, --json FILE, --html FILE
│   ├── replay.py                     runs one scenario, writes a self-contained
│   │                                  HTML replay of it (--regression NAME)
│   ├── build_site.py                 the public demo: real runs as linked replays
│   │                                  (.github/workflows/pages.yml deploys it)
│   ├── dashboard.py                  starts the live dashboard on 127.0.0.1
│   │                                  (--modbus-port also serves the I/O image)
│   ├── register_map.py               writes docs/MODBUS-MAP.md from line_map.py
│   ├── review_candidates.py          reviews candidate scenario files (Phase 8 step 1)
│   ├── ai_generate.py                AI-proposed candidates, reviewed (optional)
│   ├── ai_analyze.py                 AI hypotheses about a failed run (optional)
│   └── external_controller.py        runs the reference external controller against
│                                      dashboard.py --external
├── tests/
│   ├── unit/                        one test module per equipment/engine/control/
│   │                                 testing/telemetry class, plus test_control_boundary.py
│   └── integration/                 full-line scenarios (test_plant.py,
│                                     test_plant_io.py, test_device_control.py,
│                                     test_line_controller.py, test_scenarios.py
│                                     -- discovers and runs everything under
│                                     scenarios/ -- test_event_log.py, and
                                     test_commissioning_report.py)
├── pyproject.toml
└── README.md
```

This is deliberately smaller than the target layout in `CLAUDE.md` §17 and
the initial layout sketched in the original project brief. `examples/`
was only created once it had real content (Phase 7 step 4, the OpenPLC
demo) — CLAUDE.md §17 itself says not to pre-create directories just to
make the repository look larger than it is. Alarms (Phase 4) no longer belongs on this list —
`services/control/alarms.py` landed in step 1; see below.

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

## Module responsibilities (Phase 3, complete)

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
  run against this code, not designed in up front. The second subtlety,
  found by the first Phase 3 *step 2* scenario: `given` gets settle
  ticks before `when` is applied (one originally, two since the Phase 5
  fix below: `runner.SETTLE_TICKS`); `when` doesn't get one before the
  polling loop starts. A precondition belongs in `given` for exactly
  this reason — see `scenario.py`'s docstring for the full given-vs-when
  contract, and `Invariants.rebaseline()` for the matching conservation
  fix (a deliberate level-preset in either phase is setup, not a
  violation, but only once the baseline is reset to account for it).
- **`services/testing/report.py`** — pure logic (no I/O), so the
  coverage-matrix categorization is unit-tested directly rather than only
  exercised incidentally through the CLI. Four states per §6.3 row, not
  two: `not_covered` and `not_applicable` are different findings (a real
  gap vs. a row nothing can test yet) and collapsing them would hide
  which one actually needs work. `covered_but_failing` is its own state
  too — a row whose only scenario currently fails is not "covered."
- **`scripts/scenario_report.py`** — the thin CLI wrapper. Verified to
  actually catch problems, not just demonstrated passing: a deliberately
  failing scenario and a typo'd `interlock:` tag were both added,
  confirmed to surface correctly (including the non-zero exit code), then
  removed.

## Module responsibilities (Phase 4 step 1)

- **`Alarm` / `AlarmManager`** (`services/control/alarms.py`) — a small
  generic engine (`register`/`scan`/`acknowledge`), unlike `Interlocks`'
  stateless properties, because an alarm genuinely needs memory across
  scans: it has to stay latched after its condition clears, which a
  computed property can't do. The *set* of alarms is still hardcoded for
  this exact line in `__init__`, the same way `Interlocks` and
  `plant_io.py` are — nine `_register()` calls sitting directly on
  `Interlocks`' already-computed conditions (`estop_healthy`,
  `hopper_high_high`, `bin_low`, `conveyor_motion_confirmed`) and the
  three device-control modules' own fault flags. No new detection logic
  was needed — every condition already existed somewhere in Control; this
  phase is purely about giving them latch/first-out/acknowledge behavior
  a scenario or a future panel can observe.
- **`latched` is computed, not stored**: `active or not acknowledged`.
  That single expression gets the full behavior for free — an alarm
  self-clears the instant it's both acknowledged and back to inactive, no
  separate manual "clear" action, and acknowledging one that's still
  physically active correctly leaves it latched (still a live problem)
  without a second flag that could drift out of sync with `active`.
- **First-out** is sticky per episode, not per scan: whichever alarm's
  rising edge is observed first claims it and keeps it — even after that
  alarm's own condition clears — until every alarm on the board is
  inactive and acknowledged, so a diagnosing operator can still tell
  which condition started a cascade after the symptoms are gone. The nine
  alarms have a fixed registration-order tie-break (E-stop first, then
  upstream-to-downstream) for the edge case of two conditions going
  active on the exact same `scan()` call; any other case is decided by
  whichever rising edge is actually observed first.
- **Trip vs. warning**: `Alarm.is_warning` exists solely so
  `any_unacknowledged_trip()` — what step 2 will wire into the "No active
  latched alarms" start permissive — excludes bin-low. Bin-low already
  has its own direct permissive row (`Interlocks.bin_low`) and
  `CONTROL-LAB.md` §6.3 is explicit it's "warning only while running,"
  not a hard block; latching it as a trip-class alarm too would silently
  turn a warning into exactly the block the spec says it isn't.
## Module responsibilities (Phase 4 step 2)

- **`LineController` owns an `AlarmManager`**, built internally right
  after `self.interlocks` (`self.alarms = AlarmManager(self.interlocks)`
  — not injected, same reasoning as `self.hysteresis`: the alarm set is
  hardcoded for this line, not something a caller configures), and scans
  it every tick immediately after the three device-control modules, so
  every condition it evaluates reads that tick's fresh fault flags.
- **`acknowledge()`** is a fourth one-shot operator command
  (`start()`/`stop()`/`reset()`'s existing shape) that acks every
  currently latched alarm. Deliberately independent of line state and of
  `reset()`, ISA-18.2-style: an operator acknowledging an alarm means
  they've seen it, not that whatever tripped it is fixed — `reset()`
  keeps deciding whether the line itself can leave `FAULTED`, on its own
  existing two-tier rule, untouched by this step.
- **The "no active latched alarms" permissive lives in
  `LineController._scan_idle()`**, combined with `Interlocks.
  start_permissives_ok()`'s existing reasons — not inside `Interlocks`
  itself, which is what that method's own docstring assumed before
  `AlarmManager` existed. Since `AlarmManager` is built on top of
  `Interlocks`, having `Interlocks` check back into it would be circular;
  `LineController` is already the one place every other permissive/trip
  decision gets combined, so it's the natural home once the real
  dependency shape was clear. `Interlocks`' docstring was corrected to
  point here instead of describing a stub that was never going to be
  filled in the place it originally said.
- **`fault_reason` was deliberately left alone**, not merged into the
  alarm system. It stays the short, already-tested, per-transition
  reason string every existing test and scenario already keys off;
  `AlarmManager` is a richer, latched, acknowledgeable view sitting
  alongside it. The two stay consistent because both read the same
  tick's underlying conditions (`AlarmManager.scan()` runs before the
  state dispatch that sets `fault_reason`), not because either is
  derived from the other — a deliberate choice to add the new system
  without touching or risking the old one (`CLAUDE.md`'s own "don't
  rewrite working systems unnecessarily").
- **A real behavior change, not just new code**: three existing tests'
  fault→reset→start-again sequences needed an explicit `acknowledge()`
  added, because a bare `reset()` no longer being sufficient to restart
  is exactly the point of this step — previously nothing stopped a
  restart without an operator having seen what tripped it.

## Module responsibilities (Phase 4 step 3)

- **`services/testing/vocabulary.py`** gained one new `given`/`when`
  action (`acknowledge`, mirroring `start`/`stop`/`reset`) and two new
  `expect` read fields: `any_unacknowledged_trip` (bool) and
  `latched_alarm_ids` (a sorted list of alarm ids, comparable directly
  against a YAML list literal).
- **One new scenario**, `scenarios/faults/unacknowledged_alarm_blocks_
  start.yaml`, closes §6.3's 8th interlock row. It's deliberately
  single-stage (hopper high-high, the same shape as every other
  scenario) rather than attempting the full "trip → reset →
  retry-refused → acknowledge → retry-allowed" lifecycle: `given`/`when`
  are each one setup phase with one settle tick apiece, not an arbitrary
  sequence of stages, and forcing a multi-stage story through them would
  reproduce the exact stale-reading class of bug Phase 3 already found
  twice (`scenario.py`'s given-vs-when docstring, `runner.py`'s
  tick-before-check fix). The row's coverage `note` instead points at the
  three pytest tests from step 2 for the full lifecycle proof — the same
  split already established for the "Conveyor proven running" row, not a
  new pattern invented for this one.
- **`services/testing/report.py`**'s "No active latched alarms" row
  flipped from a permanent `applicable=False` stub to the default
  `applicable=True`, now that the mechanism it describes actually exists.
  Two existing tests in `test_report.py` had baked in `len(INTERLOCKS) -
  1` arithmetic assuming exactly one not-applicable row would always
  exist — replaced with a synthetic `CoverageReport`/`RowCoverage`
  fixture built directly, decoupled from the real table's current
  contents, so a future table change can't silently break an aggregate-
  count test the way this one did.
- **Coverage matrix now reports 8/8**, 0 not-applicable, 0 real gaps —
  `scripts/scenario_report.py` output confirms it.

## Module responsibilities (Phase 5 step 1)

- **`TagHistory`** (`services/telemetry/tag_history.py`) — the sampled
  "CSV tag history" half of Phase 5. Deliberately as generic as `IOImage`
  itself: the constructor takes only an `IOImage`, `record(t)` calls only
  `names()`/`read()`, and nothing here knows this line's tag names or
  even that a `Plant` exists. Proven by the same test pattern already
  established for `MotorControl`/`GateControl` (build a bare 2-tag
  `IOImage`, not `build_line_io_image()`) — see `tests/unit/
  test_tag_history.py`.
- **Pull, not push, confirmed as the Phase 5 architecture**: nothing in
  `services/simulation/` or `services/control/` calls into this or knows
  it exists. A caller — a test, the scenario runner, a future
  telemetry-enabled driver — calls `record(t)` once per tick, the same
  tick boundary `services/testing/rig.py`'s `tick()` already uses. Zero
  lines changed in any Phase 2-4 file for this step.
- **`t` (the timestamp) is supplied by the caller**, not tracked
  internally — `TagHistory` stays ignorant of `SimClock`/`dt` the same
  way `IOImage` itself is ignorant of simulated time. Whatever drives the
  tick loop already has that number; duplicating a clock here would be
  exactly the "second thing that could drift" pattern this codebase
  keeps deliberately avoiding elsewhere (`rig.py`, `plant_io.py`).
- **File output is a separate, standalone function** (`write_csv()`),
  not a method — `TagHistory` itself never imports `csv` or `pathlib`.
  Mirrors the `services/testing/report.py` (pure logic) /
  `scripts/scenario_report.py` (the thing that writes a file) split.
  Nothing calls `write_csv()` during a normal `pytest` run; no file is
  written as a side effect of anything in this step.
- **Columns are the union of every tag ever recorded**, not `IOImage`'s
  tag list at export time — so `write_csv()` doesn't need a live
  `IOImage` reference, and a tag defined partway through a run gets its
  own column (blank for samples before it existed) instead of either
  crashing or silently vanishing.
- **Fixed `services/control/__init__.py`** while in the area: `Alarm`/
  `AlarmManager` were never added to its `__all__` re-exports when Phase
  4 built them, unlike every other Control module. Real gap, not
  intentional — every other package's `__init__.py` (`testing`, and now
  `telemetry`) re-exports its public symbols this way; `control`'s had
  quietly fallen behind.

## Module responsibilities (Phase 5 step 2)

- **`EventLog`** (`services/telemetry/events.py`) — unlike `TagHistory`,
  this is inherently line-specific (it reads `LineController.state`/
  `fault_reason` and `AlarmManager`'s alarm set, both already
  line-specific themselves), so its tests use the real rig, the same
  tier `test_line_controller.py` already established, not a bare
  fixture the way `test_tag_history.py` does.
- **Exactly two diffable primitives per alarm — `active` and
  `acknowledged`** — not `latched`/`first_out`. `latched` is itself
  only ever a function of those two (`services/control/alarms.py`:
  `latched = active or not acknowledged`), so any transition in it
  always coincides with one already captured by `alarm_activated`/
  `alarm_cleared`/`alarm_acknowledged`; recording it separately would be
  the same fact a third time, not new information. `first_out` only
  ever changes at the same moment `active` does (the rising edge that
  claims it) or the same moment an episode fully resets (already
  captured by whichever event closes it out), so it rides along as a
  field on `alarm_activated` instead of needing its own event type.
- **A real, non-obvious finding from writing the tests**, not a
  contrived edge case: the first scenario tried for "clear then
  acknowledge" used a stuck gate (`plant.gate.stuck = True`, same fault
  as several Phase 4 tests) and produced *two* activate/clear pairs for
  `XV-102.TRAVEL_FAULT` before `acknowledge()` was ever called. Real
  behavior, not a bug: `FAULTED` continuously re-commands the gate
  closed; the moment that command changes, `GateControl.scan()`'s own
  "latches until the command changes" rule (Phase 2 step 2) resets
  `travel_fault` to `False` — but the gate is still physically `stuck`,
  so it can never reach `CLOSED` either, and `GateControl`'s own
  2-second timeout starts accumulating again from zero and re-fires on
  its own, with no new command and no new line-state transition. Phase
  4's own tests never hit this because they only ever asserted
  `Alarm.latched` (correctly true throughout, since `acknowledged`
  never became true), never the raw `active` flag's path getting there.
  Fixed by choosing hopper high-high (a pure level condition, no
  Control-driven fault-latching involved) for that specific test instead
  of redesigning `GateControl` — nothing in Phase 2-4 needed to change,
  this is `EventLog` correctly observing a real, already-existing
  interaction between two independent timing mechanisms.
- **Confirms the Phase 5 architecture decision**: zero lines changed in
  `line_controller.py` or `alarms.py` for this step. `EventLog` only
  ever reads already-public attributes, at the same tick boundary
  `TagHistory` and `rig.py`'s own `tick()` already use.
- **File output** (`write_jsonl()`) is again a standalone function, not
  a method, for the same reason `write_csv()` is — mirrors
  `services/testing/report.py`/`scripts/scenario_report.py`'s split.

## Module responsibilities (Phase 5 step 3)

- **`LineController.command_sink`** (`services/control/line_controller.py`)
  — the one Phase 5 touch to Control, as scoped: an optional
  `Callable[[str], None]`, `None` by default. `start()`/`stop()`/
  `reset()`/`acknowledge()` each call it with their own name. It's a
  plain callable, not a telemetry type, so Control imports nothing from
  `services/telemetry/`. `test_control_boundary.py` now enforces that
  with a second guard, which checks import lines only because Control's
  docstrings legitimately describe the relationship in prose.
- **`EventLog.record_command`** (`services/telemetry/events.py`) — the
  intended sink target, wired explicitly by the caller
  (`line.command_sink = event_log.record_command`). It only queues. The
  next `sample(t)` emits each queued command as a `command_issued` event
  stamped with that tick's `t` and ordered *before* the tick's
  state/alarm diffs. Why that stamp: the sink fires between ticks, where
  there's no time to read unless Control is handed a clock. The command
  is a one-shot request consumed by the next `scan()`, so that tick is
  when it actually took effect. The ordering keeps cause before effect
  within a tick. Queued commands are emitted even on the baseline-only
  first `sample()`, because a command is a recorded fact, not a diff.

## Module responsibilities (Phase 5 step 4)

- **`run_scenario()`** (`services/testing/runner.py`) now always records
  telemetry. It attaches an `EventLog` plus the command sink before
  `given`, samples after every tick it drives, and returns `events` and
  `when_applied_t` on `ScenarioResult`. Always on, not opt-in: it's
  in-memory, cheap, and proven to leave Control's behavior unchanged.
  That means the report reads the run's own record, not a second
  collection path. Testing → Telemetry is a permitted dependency
  direction (`CONTROL-LAB.md` §3.1: Testing "observes through I/O and
  telemetry"). Control → Telemetry is not, and is still guarded.
- **`render_markdown()`** (`services/testing/commissioning_report.py`)
  is pure and returns a string. `scripts/scenario_report.py --markdown
  FILE` is the only writer, and one suite run feeds both the console
  output and the document. Output is **byte-identical across runs**:
  no generation timestamp, scenario paths relative to `scenarios/`,
  simulated time only. A committed report therefore diffs as a record
  of behavior change, and the git commit is its provenance.
  Events are labeled *setup* (at or before `when_applied_t`) or
  *response* (after it).
- **`runner.SETTLE_TICKS = 2`** — fixed after the report exposed it.
  Inside `tick()`, Control scans *before* the plant publishes inputs.
  So a `given` precondition written into the plant is published to the
  I/O image on settle tick 1, and Control scans it on tick 2. With one
  settle tick, `given` was settled in the I/O image but not in
  Control's own state, and precondition alarms first activated on the
  scan that consumed `when`, which put them in the report as
  *response* events. Two ticks is derived from that scan order, not
  tuned. Response times are unchanged because they're measured from
  `when`. Pinned by
  `test_a_given_precondition_is_seen_by_control_before_when_is_applied`.

## Module responsibilities (Phase 6 steps 1-2)

- **`run_scenario()`** also records a `TagHistory`, paired with the
  `EventLog` in a small explicit `_Telemetry` dataclass so both are
  sampled on exactly the same ticks. `ScenarioResult.tags` holds it.
- **`services/visualization/replay.py`** — `build_frames()` turns
  events + a `TagHistory` into one frame per sample: tag values, the line
  state in effect, the latched alarm board (latched = active or
  unacknowledged, first-out sticky until the alarm leaves the board,
  both matching `alarms.py`), and which events fired that tick. It's
  **reconstructed from telemetry, never re-simulated or read from a live
  `LineController`.** That's what makes it a replay, and an end-to-end
  test checks the reconstruction agrees with where the real controller
  ended. `render_html()` embeds the data (with `</` escaped) into
  `replay_template.html`. It writes no files; `scripts/replay.py` does.
  It depends on Telemetry only, per §3.1's Visualization row.
- **`replay_template.html`** — high-performance-HMI conventions: gray
  equipment, dark = running/open, hollow = stopped/closed, red = trip,
  amber = warning or **command/feedback disagreement** (dashed outline:
  commanded to run but unproven, or a gate still travelling). Hopper
  kg→% and setpoint lines come from the plant constants the caller
  passes in (`scripts/replay.py` uses `rig.DEFAULT_PLANT_CONFIG`, which
  is what every scenario run uses).
- **`Plant.time_s`** is now rounded per step like `SimClock`. It had
  drifted (found through the replay data), and every telemetry
  timestamp comes from it.

## Module responsibilities (Phase 6 step 3)

- **`LiveSession`** (`services/visualization/live.py`) — the
  dashboard's deterministic core. A rig from `build_rig()`, the same
  `EventLog` + command sink + `TagHistory` the runner records, and
  `Invariants`. `command()`/`stimulus()` validate immediately and
  *queue*; `step()` applies the queue at the tick boundary, ticks once,
  samples telemetry, and checks invariants. A violation is kept and
  shown, not raised. Level stimuli rebaseline conservation, exactly as
  the runner does. `snapshot(since)` returns the replay-frame shape plus
  only the new events. `replay_html()` renders the session through the
  step-2 viewer. It has no wall clock, so its tests are as
  deterministic as scenario runs.
- **`Pacer`** — the only real-time code: a daemon thread stepping the
  session every DT/speed seconds. It resyncs after a stall of more than
  1 s instead of bursting catch-up ticks.
- **`make_handler()`** — stdlib HTTP routes: `/` (the assembled page),
  `/api/state?since=N`, `/api/replay` (attachment), and POSTs for
  `command`/`stimulus`/`run`/`restart`. POSTs must be
  `application/json` and the Host header must be localhost. That's the
  cheap CSRF + DNS-rebinding defense for an unauthenticated localhost
  server, and both are tested.
- **Stimuli go through `vocabulary.apply_field`**, the same closed set
  scenario files use, plus three new **field resets**
  (`feeder_drive_reset`, `conveyor_overload_reset`, `gate_reset`) that
  clear a device's own latched fault. Without them a tripped motor could
  never be recovered live. They're deliberately separate from
  un-injecting the cause, because a real repair is two actions.
- **`page.py` + `hmi.css` / `mimic.svg.html` / `hmi.js`** — the line
  mimic and panel renderers, written once and inlined into both pages.
  `hmi.js` functions take values as arguments (no page globals), which
  is what lets a recorded frame and a live snapshot share them.
- **Dependency direction:** `live.py` depends on Testing (rig,
  vocabulary, invariants) because it *drives* the line, the runner's
  role; `replay.py` only observes and depends on Telemetry alone.

## Module responsibilities (Phase 7 step 1)

- **`services/protocols/modbus.py`** — a Modbus TCP server with zero
  runtime dependencies, in three layers. `DataStore` is the four tables
  as an interface, with no knowledge of ControlLab (`MemoryDataStore`
  is the reference implementation; step 2 binds one to `IOImage`).
  `handle_pdu()`/`handle_adu()` are pure and hold every protocol rule;
  a malformed request becomes an exception response, never a Python
  exception, and a store failure is `SERVER_DEVICE_FAILURE`, not blamed
  on the client. `ModbusServer` handles each request under a
  caller-supplied lock, so it can share the tick loop's lock and never
  serve a half-applied scan. Localhost by default, port 5020.
- **Why hand-rolled:** the needed subset is small (8 function codes),
  and `pymodbus`'s 3.x API has broken repeatedly. The condition for
  owning a protocol implementation is proving interoperability, so the
  tests use the spec's own example bytes and drive the server with
  `pymodbus`'s client, a **dev-only** dependency.

## Module responsibilities (Phase 7 step 2)

- **`register_map.py`** (generic) — `RegisterMap.validate(io)` runs
  before anything is served and reports every problem at once: each
  tag mapped exactly once, the table matches the tag type
  (DI→discrete input, DO→coil, AI→input register, AO→holding
  register), no address collisions (HMI block included), and analog
  full scale fits in 16 bits. `IOImageDataStore` implements the step-1
  `DataStore` over an `IOImage`. Reads scale and clamp. Writes are
  validated whole before applying. Unmapped spans are refused. Outputs
  are writable only when `outputs_writable` is set. HMI coils call
  `on_command` and always read 0. It takes a `get_io` callable, not an
  `IOImage`, so the owner can swap in a fresh image.
- **`line_map.py`** — the line's addresses, written out explicitly: each
  table from 0 in §5.3 order, HMI coils at 100-103, 0.01 % / 0.1 kg
  resolution. `scripts/register_map.py` renders `docs/MODBUS-MAP.md`
  from it; a test fails on drift.
- **Wiring** — `scripts/dashboard.py --modbus-port` serves the
  `LiveSession`'s I/O image under `session.lock`, now an `RLock`
  because an HMI coil write re-enters `session.command()` while the
  server already holds it.

## Module responsibilities (Phase 7 step 3a)

- **`build_rig(with_controller=False)`** — a plant-only rig
  (`rig.line is None`, so `tick()` only advances the plant).
  `build_line_controller()` was split out so the external controller
  builds *exactly* the stack every scenario uses.
- **`ModbusClient`** (`modbus.py`) — stdlib client for the same eight
  function codes; transaction IDs checked; exception responses raise
  `ModbusError`. Interop-tested against `pymodbus`'s server.
- **`HmiLatches` + `IOImageDataStore(hmi_latches=...)`** — latched HMI
  mode: request bits set by ControlLab, acknowledged (written 0) by the
  controller. `on_output_write` gives the plant a heartbeat.
- **`ModbusIOSync`** (`register_map.py`) — the controller side of the
  map: `pull_inputs()` (via `write_input`, so the mirror keeps
  `IOImage`'s direction rules), `take_commands()` (read + acknowledge),
  `push_outputs()`. Requests are grouped by `contiguous_runs()` and
  never span an unmapped hole.
- **`ExternalController`** (`external_controller.py`) — mirror
  `IOImage` + `build_line_controller()` + `ModbusIOSync`.
  `scan_once()` for deterministic lockstep tests; `run()` free-runs on
  its own clock.
- **`LiveSession(external=True)`** — no controller, latched HMI,
  directly recorded command/watchdog events, and the **comm-loss
  watchdog** (`WATCHDOG_S = 1.0`: no output write for 1 s of plant time
  while a discrete output is on → all outputs off).
- **`Invariants`** — the feeder-unconfirmed check reads
  `M-104.RUNNING`/`ZSS-104` from the I/O image instead of asking
  `rig.line.interlocks`. The semantics are identical, and it works with
  no controller.
- **`services/control/`: unchanged.** That's the point of the step.

## Module responsibilities (Phase 7 step 3b)

- **`controller_status.py`** — the controller's internal state as five
  holding registers (200-204): `encode(line)` / `decode(registers)`,
  plus code tables for states, fault reasons, and alarm bits.
  Active + unacknowledged masks (not one "latched" mask) let the far
  side rebuild the whole alarm board as real `Alarm` objects. Three
  drift tests tie the tables to Control.
- **`IOImageDataStore(status_source=...)`** — built-in mode computes
  the block on read (read-only); external mode stores what the
  controller writes. `ModbusIOSync.push_status()` / `read_status()`.
- **`RemoteLine` / `build_external_rig()`** (`services/testing/external.py`)
  — a `LineController`-shaped adapter whose commands are latched HMI
  requests and whose state comes from the status registers, read on
  an observer connection separate from the controller's. The runner,
  vocabulary, invariants, `EventLog`, and scenario files are untouched;
  `run_scenario(..., external=True)` selects it.

## Module responsibilities (Phase 7 step 4a)

- **`RegisterMap.controller_ranges()`** — the controller's view as the
  five (start, count) ranges a PLC master configures. `validate()`
  refuses a map where any of them has a hole. This is the rule the
  step-2/3 map broke without anyone noticing until it was checked
  against OpenPLC.
- **`HmiHandshake`** — the request/ack word pair (4-phase,
  exactly-once, holds a press made during a standing ack). Replaced
  step 3a's `HmiLatches`. `IOImageDataStore(handshake=...)` serves the
  words; the request word is read-only to clients.
- **`ModbusIOSync`** — polls in exactly the master shape: FC 2, FC 4,
  FC 3, then after the scan FC 15 and one FC 16 carrying the outputs,
  the status block (`push_outputs(status=...)`), and the ack word.

## Module responsibilities (Phase 8 step 1)

- **`services/testing/candidates.py`** — `review(path, existing)`
  returns a `Review` of findings (ok / warning / judgment / error) and
  a verdict. It reuses the runner (built-in, twice, and across Modbus),
  the vocabulary tables, and the §6.3 row list, so a candidate is
  judged by exactly the machinery the suite itself uses. The vacuity
  check reruns with `when` removed via `dataclasses.replace`. No AI, no
  network. Any future generator feeds this gate, never `scenarios/`.

## Module responsibilities (Phase 8 step 1b)

- **`StartInhibit`** (`services/control/line_state.py`) and
  **`LineController.start_inhibit`**: the machine-readable outcome of
  the most recent start request (NONE, BIN_LOW, HOPPER_HIGH_HIGH,
  UNACKNOWLEDGED_ALARM, ESTOP_ACTIVE, LINE_FAULTED; a flag, since
  reasons co-occur). It's reporting only and is set only when a start
  is evaluated, which is what lets a scenario prove START was issued.
  It flows through the vocabulary (`start_inhibit`), status register
  HR 7 (appended after the HMI ack word), `controller_status`,
  `RemoteLine`, and the OpenPLC program's `%QW107`.

## Module responsibilities (Phase 8 steps 2-3: optional AI)

- **The flow is fixed:** AI proposal → deterministic review gate →
  engineer approval → deterministic execution. `generate_candidates()`
  does the first two and stops; only an engineer moves a candidate
  into `scenarios/`. AI never runs control logic and never bypasses the
  gate, which runs on every candidate in the same call.
- **`provider.py`**: one interface, `complete_json(system, user,
  schema, max_tokens)`. A new provider is a class plus a registry
  entry, with no change to core layers. An import-line test keeps
  every core package free of `services.ai` and `anthropic`, and a
  subprocess test runs ControlLab with the SDK blocked.
- **`generate.py`**: the output schema's keys are an enum of the real
  vocabulary; limits (1-5 candidates, request ≤ 2,000 chars, 8,000
  output tokens) are checked in code, before and after the call.
- **`analyze.py`**: a bounded digest (events nearest the failure,
  discrete transitions in a window, analog summaries, a char cap, and
  omissions stated) in; unverified, evidence-cited hypotheses out, in
  one Markdown file. Nothing is changed.

## Module responsibilities (Phase 9 step 1)

- **`runner.execute()`** — the runner with its one mode-dependent
  piece passed in: `step()`, which advances exactly one DT and samples
  telemetry. `run_scenario()` passes the lockstep tick and is otherwise
  unchanged. `tolerance_s` (0 in lockstep) extends polling past
  `within`; a result met inside the extra window has
  `within_tolerance=True`.
- **`ObservedLine`** (`external.py`) — the LineController surface over
  Modbus with no controller behind it: commands → HMI handshake, state
  ← status registers. `RemoteLine` is now `ObservedLine` plus the
  in-process lockstep controller.
- **`RealtimePlant`** (`realtime.py`) — a plant-only rig served over
  Modbus on the port the controller polls; `fresh()` swaps the rig
  per scenario without dropping the controller's connection.
- **`ControllerUnderTest`** — the only handle ControlLab has on the
  controller: `restart()` (cold, like a power cycle) and `close()`.
  `ReferenceController` runs our own controller free in a thread;
  `scan_s` models a slower PLC task. Step 2 adds OpenPLC.
- **`run_realtime()`** — fresh plant, restarted controller, the
  power-up procedure (wait for its first full write, then acknowledge
  and reset until a clean IDLE, not recorded as part of the scenario),
  then `execute()` with a wall-clock `_Pacer`. The latency allowance
  (`LATENCY_S`, plant seconds) is the tolerance, the settle, and the
  feeder invariant's grace (`Invariants(feeder_grace_ticks=...)`).
  Controller silence aborts the run; plant lag beyond `MAX_LAG_S`
  invalidates it; `GivenUnreachable` (a `ScenarioLoadError` subclass)
  becomes a failed result about the controller.

## Module responsibilities (Phase 9 step 2)

- **`services/protocols/openplc.py`** — `OpenPLCWeb` (login, form
  posts, upload; shared with `setup_openplc.py` and `compile_check.py`)
  and `OpenPLCController`, a `ControllerUnderTest` whose `restart()` is
  `stop_plc` + `start_plc` (cold, probed). It only presses the
  runtime's own buttons; the logic is reached over Modbus alone.
- **`run_suite_realtime()` / `RepeatedRuns`** (`realtime.py`) — N
  independent passes; `combined()` is the one result the coverage
  matrix and report see (all passes must pass; the worst pass's record
  is carried), `responses` the per-pass spread.
- **`RealtimeConditions`** (`commissioning_report.py`) — optional:
  adds the real-time conditions section, the 🟡 within-tolerance mark,
  and the spread table. Without it the report is byte-for-byte the
  lockstep one.
- **`scripts/scenario_report.py --realtime {reference,openplc}`** with
  `--repeat`, `--latency`, `--speed` (reference only), `--modbus-port`,
  `--plc`.

## Module responsibilities (Phase 9 step 3)

- **`vocabulary.CONTROLLER_FIELDS` / `NotObservable`** — the read
  fields that come from the controller, and the exception a
  status-less controller raises for them. A test ties the set to
  `READ_FIELDS`.
- **`ObservedLine(status=False)`** — never reads the status registers;
  every state property raises `NotObservable`. Commands still use the
  HMI handshake.
- **`EventLog(controller_state=False)`** — commands only.
- **Runner** — `ScenarioResult.not_observed` (skipped expectations) and
  `not_observable` (none observable: neither pass nor fail);
  `_line_running()` judges `given: running` from field evidence when
  the controller's state can't be read.
- **`report.py`** — `RowCoverage.unobservable`, a `not_observable` row
  status, `failed_count` (excludes not observable), and `verdict`
  (PASS / PARTIAL / FAIL). Both renderers show the new marks.
- **`run_realtime(status=False)`** — blind power-up
  (`_blind_power_up`: acknowledge, reset, outputs quiet 0.5 s).

## Module responsibilities (Phase 9 step 4)

- **`map_file.load_map(path, io)`** — YAML → `RegisterMap` →
  `validate(io)`, returning (map, name) or raising `MapFileError`
  with every problem listed. Status block all-or-nothing; command and
  status descriptions borrowed from the line map. Strict about unknown
  keys and shapes.
- **Status follows the map** — `run_realtime(status=None)` means
  "publishes a status block iff the map has one".
- **`register_map.render_markdown(..., source=...)`** — names the map
  file it was generated from; says "no status block" when there is
  none.
- **`ExternalController` / `run()` / `ReferenceController`** take a
  `register_map` (default `LINE_REGISTER_MAP`).
- **CLIs** — `--map` on `scenario_report.py --realtime`,
  `register_map.py`, and `examples/openplc/setup_openplc.py`.

## Module responsibilities (Phase 4 completion, 4a: multi-stage scenarios)

- **`Scenario.then` / `Stage` / `Scenario.stages`** (`scenario.py`) —
  optional further `when`/`expect`/`within` stages; strict loading.
- **`runner.execute()`** — runs the stages in order (`_poll_stage`),
  each stage's `when` applied the tick after the previous stage's
  expectations held; `ScenarioResult.stage_elapsed`. Details of a
  failing later stage are prefixed `stage n/N:`.

## Module responsibilities (Phase 4 completion, 4b: feeder jam)

- **`Feeder.jammed` / `plugged` / `plug_detect_s`** (simulation) — the
  jam and the discharge-chute plug switch it trips; `LSH-103` published
  by `plant_io`.
- **`Interlocks.feeder_plugged`**, the "feeder jam" trip in
  `LineController`, and `_fault_cause_cleared()` refusing a reset while
  plugged; alarm `LSH-103.JAM` (registered last: append-only bits).
- **Vocabulary** — `feeder_jam`; read fields `feeder_flowing`,
  `first_out` (a controller field).

## Module responsibilities (Phase 4 completion, 4c: sensor failure)

- **`services/simulation/equipment/instruments.py`** — `Instruments`
  (`stick` / `fail` / `restore`, `report`, `channel_fault`), held by
  `Plant`; `plant_io.publish_plant_inputs` publishes every input through
  it and publishes `WT-105.FLT` from the channel diagnostic.
- **`Interlocks.hopper_weight_failed`** — start permissive
  (`StartInhibit.SENSOR_FAILED`), STARTING/RUNNING trip, reset gate;
  alarm `WT-105.FAIL`.
- **Vocabulary** — `sensor_stuck`, `sensor_failed`, `sensor_restored`
  (value: an input tag); read field `hopper_weight_agrees`.

## Module responsibilities (Phase 8 completion)

- **`Scenario.trigger`** + the gate's trigger check (`candidates.py`):
  re-run with exactly the trigger removed; must fail.
- **`generate.validate_candidate()` / `analyze.validate_analysis()`** —
  model output checked in code before anything is written.
- **`ScenarioResult.failed_stage` / `failed_stage_applied_t` / `unmet`**
  — the structured failure; `analyze.build_digest()` adds it plus a
  deterministic first divergence.
- **`examples/ai_assist/`** — `run_flow.py` (the whole loop) and
  `scripted_provider.py` (canned, labelled stand-in answers from
  `canned/`). Full description: `docs/AI.md`.

## Module responsibilities (field-observable expectations)

- **Read fields `feeder_run_commanded` / `conveyor_run_commanded` /
  `gate_open_commanded`** — the controller's output coils; field
  evidence, not controller state.
- **`vocabulary.StatusWithheld` + `run_scenario(status=False)`** — any
  scenario judged on field evidence alone, deterministically.
- **The review gate's `field` check** — field-observable share, and a
  warning if the candidate would pass vacuously without a status block.

## Module responsibilities (level switches: fail-safe polarity)

- **`LSH-105` / `LSHH-105`** — fail-safe: 1 = below the switch point.
  `plant_io` publishes the inverted contact; `Interlocks.hopper_high` /
  `hopper_high_high` are the only places the polarity is undone in Control
  (and `hopper_high` / `hopper_high_high` in the ST port).
- **`Instruments.fail()`** — also takes a switch (reads 0, no diagnostic);
  `channel_fault()` only on a channel that has a diagnostic.

## Module responsibilities (level switches: 1oo2 + cross-check)

- **`Interlocks.hopper_high_high`** — 1oo2: `hopper_high_high_switch`
  (LSHH-105 open) or `hopper_high_high_weight` (WT-105 ≥ the configured
  high-high setpoint, channel healthy).
- **`services/control/level_check.py`** — `LevelSwitchCheck` (one
  switch vs WT-105: deadband, delay, not judged while WT-105 has failed)
  and `HopperLevelChecks` (both switches), owned and scanned by
  `LineController` before the alarm scan; `AlarmManager` reads them for
  `LSH-105.DISAGREE` (warning) and `LSHH-105.DISAGREE` (trip-class).

## Module responsibilities (dashboard: instrument faults)

- **`LiveSession.stimulus()`** — `sensor_stuck` / `sensor_failed` /
  `sensor_restored` (value: an input tag), validated before queueing;
  `snapshot()["injected"]["instruments"]` lists every unhealthy one.
  The page offers WT-105, LSH-105 and LSHH-105.

## Module responsibilities (dashboard: plain-English narration)

- **`services/visualization/narrate.py`** — `narrate(snapshot)`: what the
  line is doing, why, and what to do next, in plain words, with a recovery
  checklist that ticks itself off. A pure function of the snapshot (plus
  the pacer's `running`); it explains, never decides. Every controller
  fault reason must have an explanation (tested).
- **`LiveSession.snapshot()`** — adds `start_step` and `pending` (inputs
  queued for the next tick, so a paused line never swallows a press
  silently); the server attaches `story`.

## Module responsibilities (dashboard: guided walkthroughs)

- **`services/visualization/walkthroughs.py`** — five walkthroughs (normal
  start/stop, a refused start, E-stop, a motor fault and recovery, overfill
  protection with a stuck switch). A step says what to do, names the
  control to highlight, can do it ("Do it for me"), and completes only
  when the live line reaches its condition, never on a click.
- **`LiveSession.start_tour()` / `tour_do()` / `exit_tour()`** — a
  walkthrough starts on a fresh line; actions go through the validated
  `command()` / `stimulus()` path; the step advances after each tick.
  `POST /api/tour`. Every walkthrough runs to completion in the suite, and
  no action step may complete before its action.

## Module responsibilities (Phase 10: validation workflow)

- **`services/testing/verdict.py`** — `summarize(scenario, result,
  runtime)`: the engineering result of one run (setup, each stage's
  actions classified as operator action / fault injected / field repair /
  process condition, every check as MATCH / MISMATCH / NOT REACHED / not
  run / not observed, first-out from the event log, invariants, the first
  divergence, times). Built only from the runner's own record.
  `render_text()` is the console form; `event_signature()` compares two
  runs' event logs.
- **`services/testing/regressions.py`** — named, deliberately broken
  `LineController` subclasses (testing fixtures only; production code is
  never modified). `run_scenario(..., line_cls=)` / `build_rig(line_cls=)`
  build one in-process.
- **`services/cli.py`** — `controllab test [patterns] [--runtime
  python|modbus|openplc] [--regression NAME]` (`[project.scripts]`;
  `python -m services.cli` without installing). Exit 1 on any failure,
  including a caught regression.
- **Scenario `description:` / stage `title:`** — optional, for people;
  printed beside the checks, never part of the verdict.
- **`services/visualization/verify.py`** — dashboard verification:
  `SHOWCASE` (the five scenarios the page leads with), `Verifier` (one job
  at a time on a background thread; OpenPLC detected by its web UI
  answering). Each runtime goes through the existing path: the Python
  controller through `LiveSession.run_live()` (runner.execute() on the
  dashboard's own line, so it's visible, and tested identical to the
  suite's run), Modbus through `run_scenario(external=True)`, OpenPLC
  through `run_realtime()`. Comparing runtimes states how each row was
  compared: lockstep runs event by event, real-time runs by verdict and
  checks. `POST /api/verify`, `GET /api/replay/latest`.

## Module responsibilities (completing Phase 2: Manual mode)

- **`LineMode`** (`line_state.py`) — AUTO / MANUAL, separate from
  `LineState`: the mode says who drives the devices, the state where the
  line is. Kept on `LineController.mode`; it survives FAULTED and
  ESTOPPED.
- **`LineState.MANUAL`** — the operator drives each device. State code 6
  (`controller_status.py`, appended).
- **`LineController` pushbuttons** — `select_auto()` / `select_manual()`,
  `start_conveyor()` / `stop_conveyor()`, `open_gate()` / `close_gate()`,
  `start_feeder()` / `stop_feeder()`: one-shot requests like `start()`,
  each reported to `command_sink` by name. `_change_mode()` accepts a mode
  change only at rest; `_refuse_device_starts()` reports a device start
  outside MANUAL (`WRONG_MODE`, or `ESTOP_ACTIVE` / `LINE_FAULTED` in
  Manual mode); `_scan_manual()` checks trips, applies stops before
  starts, checks each start's permissives (`_manual_conveyor_refusal()`,
  `_manual_feeder_refusal()`), and enforces the feeder rule every scan
  (proven belt, below LSH-105). `_supervise_manual_conveyor()` holds the
  conveyor's proof in Manual, where no start sequence proves it.
  `_enter_rest()` is the one place a reset or a mode change picks IDLE or
  MANUAL.
- **`StartInhibit`** — now the outcome of the most recent start *or mode*
  request; four bits appended (`CONVEYOR_NOT_RUNNING`, `HOPPER_HIGH`,
  `WRONG_MODE`, `LINE_NOT_IDLE`). `docs/MODBUS-MAP.md` regenerated.
- **`tests/integration/test_manual_mode.py`** — mode selection and
  refusals, wrong-mode commands, a manual cycle with the invariants on
  every tick, each permissive, each trip, E-stop, the audit trail, and
  the runner's `given.line_state: manual`.
- **Step 2 — Testing and Modbus.** `vocabulary.py`: the eight pushbuttons
  (`_pushbutton()`), the `mode` read field (in `CONTROLLER_FIELDS`;
  `StatusWithheld` withholds it). `runner._reach_manual()`: selects Manual
  and waits for the controller's word; not observable without a status
  block. `candidates.LINE_STATES` gains `manual`; `verdict.py` and
  `services/ai/context.py` describe every new key. `controller_status.py`:
  `MODES` and a seventh register, `mode`; `line_map.py`: HMI coils 104-111
  (request bits 4-11) and the `mode` register at HR 8, both appended;
  `configs/io/*.yaml` match. `ObservedLine`/`RemoteLine` and
  `external_controller.COMMANDS` carry the pushbuttons and the mode.
  `regressions.ManualFeederBeforeBelt`. `report.py`: `scenario_mode()`,
  `CoverageReport.mode_counts()`; the console and Markdown reports print
  *Operating modes validated*. Scenarios: `scenarios/manual/`.
- **Step 3 — the PLC.** `examples/openplc/controllab_line.st`: request
  bits 0-11, the mode request and wrong-mode refusal after the E-stop
  check, state `6` (MANUAL) mirroring `_scan_manual()`, rest-state resets,
  `ST_MODE` on `%QW108`. `tests/unit/test_openplc_program.py` ties the
  request `CASE` to `LINE_REGISTER_MAP.commands`.
- **Step 4 — the dashboard.** `live.py`: `COMMANDS = tuple(LINE_REGISTER_MAP
  .commands)`; the snapshot's `line_mode`. `live_template.html`: the Mode
  switch (`#mode-switch`), the device panel (`#devices`, `renderManual()`),
  disabled with a reason outside Manual. `narrate.py`: `_manual()`,
  `_refusal()`, and the Manual refusal phrases. `walkthroughs.py`: the
  `manual` walkthrough. `hmi.css`: `.state.manual`, `.seg`, `.devices`.

## Module responsibilities (completing the master specification)

- **`candidates._stages_check()`** (item 2) — the vacuity check for every
  later acting stage: the scenario re-run with that stage's `when`
  emptied must fail; reported as the `stages` finding.
- **`services/testing/report_export.py`** (item 3) — `report_dict()`: the
  report as plain data (schema `controllab.commissioning-report/1`: build,
  controller, overall, summary with warnings, critical failures, modes,
  interlocks, real-time conditions, and every scenario with its events).
  `render_html()` renders only from that data (so JSON and HTML agree):
  self-contained, no script, a print stylesheet for Save as PDF.
  `build_info()` stamps the package version and this checkout's commit
  (dirty flag), and nothing when the directory isn't its own checkout.
  `render_markdown(build=)` prints the same stamp.
- **Degraded instruments** (item 4) — `Instruments.add_noise()` / `drift()` /
  `lag()` (+ `ranges`, `seed`, `now`, set by `Plant.step()`); vocabulary
  `sensor_noise` / `sensor_drift` / `sensor_slow`; dashboard presets.
  `Interlocks.scan()` + `hopper_high_high_weight_vote`: the transmitter's
  high-high vote holds 0.5 s (`hh_weight_debounce_s`); `LineController.scan()`
  calls it after the device modules. The PLC mirrors it (`LIM_HH_DEBOUNCE`).
- **Motor current and belt scale** (item 5) — `Conveyor.current_a`, `.jammed`,
  `Motor.overload()`; `MaterialBin.bridged`; `Plant.belt_flow_kg_s` (FT-104)
  and `Plant.feed_flow_kg_s` (what really left the bin). `Interlocks`:
  `conveyor_current_high`, `conveyor_overcurrent` (1 s on-delay while proven
  running), `no_flow` (on-delay); `LineController._motion_loss_reason()` names a
  motion loss a jam or a slip from the current. Alarms `IT-104.HIGH`,
  `FT-104.NO_FLOW`; §6.3 rows 12-13 in `report.py`.
- **Three bins** (item 6) — `Plant.bins` {"A","B","C"} → (bin, gate);
  `LineController.gates`, `select_source()`, `source_bin`, `active_bin`,
  `_close_gates()`, `_active_gate`, `_gate_travel_fault`; `Interlocks.gates`,
  `bin_low_of()`. `register_map.HmiSetpoint` + `RegisterMap.hmi_setpoints` +
  `RegisterMap.handshake()`: HMI setpoints, carried by `HmiHandshake.setpoints`,
  read by `ModbusIOSync.take_commands()` with the request word, applied by the
  reference external controller; `IOImageDataStore(on_setpoint=, setpoint_source=)`
  for built-in mode. `controller_status`: 11 registers (two alarm words, the
  bins). Dashboard: `LiveSession.setpoint()`, `/api/setpoint`, the Source bin
  switch, the three-bin picture. `tests/unit/test_hmi_js.py` runs `hmi.js`
  in Node.
- **Batch mode** (item 7) — `Plant.outlet` (XV-106, a `Gate`) and
  `Plant.outlet_plugged`; the hopper draws only while the outlet is open.
  `LineMode.BATCH`, `LineState.LOADING/PROCESSING/DISCHARGING/CLEANING`,
  `BatchStep` (CONVEYOR, GATE, FEED, SETTLE). `LineController(outlet_ctrl=,
  batch_preact_kg=, batch_empty_kg=, batch_tolerance_kg=, discharge_timeout_s=)`;
  `set_recipe()`, `set_hold()`, `select_batch()`, `open_outlet()` /
  `close_outlet()`; `_request_batch()` (the permissives), `_batch_trip_reason()`,
  `_scan_loading/processing/discharging/cleaning()`; `_enter_rest()` returns to
  the mode's rest state. Setpoints HR 102-105; `controller_status`: 13 registers
  (`batch_loaded_kg`, `batches_completed`). `ExternalController.scan_once()`
  applies setpoints before commands. Dashboard: the Batch button, the recipe
  panel, the outlet in the picture. `scenarios/batch/`; the PLC port's batch
  limits are tied to the rig by `test_openplc_program.py`.
- **MQTT and OPC UA** (item 8) — both read the live session through
  `LiveSession.snapshot()` (which now carries `session`, a counter that tells
  a restarted session from the same one) and operate it through `command()` /
  `setpoint()`, exactly as the browser does; neither touches the controller.
  `mqtt.py`: packet functions (pure), `MqttClient` (blocking, one owner
  thread), `TelemetryPublisher.publish_changes()`, `run_publisher()` (the
  dashboard's retrying loop). `opcua_server.py`: `LineOpcUaServer.build()` /
  `update()` / `serve()`, `start_in_thread()`; a node is written only when its
  value changes, and a setpoint only when the session's value changes, so a
  client's write waits for the next tick instead of being undone. Tests:
  `tests/unit/test_mqtt.py`, `tests/integration/test_mqtt_broker.py`
  (`CONTROLLAB_MQTT_BROKER` / `CONTROLLAB_MQTT_CONTAINER`),
  `tests/integration/test_opcua_server.py` (skipped without the extra).

## Module responsibilities (hardening: the logic review's minors)

- **`services/control/hopper_hysteresis.py`** gains `rearm()`, called by
  `LineController._begin_start_sequence()`, so each run's level control
  starts out wanting to feed. **`LineController._scan_starting()`**'s
  gate step evaluates level control before starting the feeder: with
  `LSH-105` made it goes straight to RUNNING with the feed held. The ST
  port does the same (`feed_demand := TRUE` at Start; the hysteresis
  block in `start_step = 1`).
- **`LineController._stopping_trip_reason()`**: while the conveyor is
  commanded, a start-proof fault or (once `_stop_belt_proven`) a loss of
  belt motion trips STOPPING, so the purge can't count down on a belt that
  isn't moving. ST: `stop_belt_proven`, set on each entry to state 3.
- **`LineController._gates_not_closed()`**: the gates-closed start
  permissive (every bin gate and the outlet at `ZSC`), checked by
  `_scan_idle()` and `_request_batch()`, reported as
  `StartInhibit.GATE_NOT_CLOSED`. The vocabulary's `gates_closed` read
  field is the same four switches; `narrate.py` words the refusal and
  `walkthroughs.ready_to_start` makes the shared Reset step wait for it.
- **`services/testing/runner.py`** `_line_running()`: on field evidence
  (a status-less controller), a started line with the feed held at
  `LSH-105` counts as running.

## The self-explaining replay (readable cold)

A replay of a scenario run carries the run's summary
(`build_replay(..., summary=RunSummary.to_dict())`), and the page then
explains itself to someone who has never seen ControlLab: an intro saying
what they're looking at, a caption narrating the current moment, and the
test itself beside the line, each stage turning passed or failed when
playback reaches the time the runner recorded for it (a passed stage ends
at `applied_t + response_s`, the failed one at its deadline). The page
judges nothing; every status and time is the summary's. Playback starts
itself and pauses briefly on each stage outcome. `verdict.describe_action()`
and `describe_setup()` give each action and starting condition a plain
sentence (drift-tested against the vocabulary). `scripts/replay.py` and the
dashboard's *Watch this run* both produce this page; `scripts/replay.py
--regression NAME` records a run against a deliberate-regression build. A
live-session recording has no summary and gets the plain replay.

**The public demo** (`scripts/build_site.py`,
https://taborbachelor.github.io/controllab/) is four of these pages linked
as tabs: feeder jam recovery, the same test against the `reset-ignores-jam`
regression (it fails at stage 2), overfill protection with a stuck
high-high switch, and a normal start/stop. Each page is a real run made at
build time; the tab badges are those runs' verdicts. The build is
deterministic (tested byte-identical across rebuilds), and
`.github/workflows/pages.yml` rebuilds and deploys it from the current code
on every push to `main`, so it cannot drift from the repository.

**Continuous integration** (`.github/workflows/tests.yml`) runs the full
suite on every push and pull request, on Python 3.12 and 3.13 on Linux,
with only the `[dev]` extra installed: no AI SDK and no OpenPLC, so it also
proves neither is needed. The real-time tests (a free-running reference
controller at 4× against the wall clock) run there too.

## Roadmap (current phase status)

| Phase | Focus | Status |
|---|---|---|
| 0 | Foundation | done |
| 1 | Simulation core | done |
| 2 | Control | done — Auto and Manual modes (Manual completed 2026-09-23: controller, scenarios, Modbus, OpenPLC 38/38, dashboard), sequences, interlocks, E-stop, fault state |
| 3 | Testing / commissioning scenarios | done |
| 4 | Fault injection, alarms | done — alarm core (latch, first-out, acknowledge); every §5.4 fault injectable, including the feeder jam (plug switch) and sensor failure (stuck / failed with channel diagnostic); multi-stage scenarios; 10/10 interlocks; verified on OpenPLC |
| 5 | Telemetry | done — generic sampled tag history; state/alarm diffing observer; optional command sink; generated Markdown commissioning report |
| 6 | Visualization | done — tag history in every scenario run; HTML replay viewer; live localhost dashboard with operator commands, fault injection, and replay download |
| 7 | Protocols | done — Modbus server + client; register map (five PLC-master ranges); external-controller mode with the full scenario suite passing across Modbus; OpenPLC running a Structured Text port of the controller against the plant |
| 8 | AI engineering assistance | done — review gate (incl. declared-trigger causality); optional AI behind a provider abstraction; validated, gated scenario generation; bounded, validated failed-run analysis; end-to-end example (`docs/AI.md`). Live-model path built, deliberately not exercised (no API spend on this project) |
| 9 | Virtual commissioning | done — real-time runner (unchanged scenarios against a free-running external controller, latency tolerance, known starting state); the commissioning report against OpenPLC (45/45 runs, 3 passes); *not observable* for controllers without a status block; I/O map files, with the unchanged OpenPLC program passing against a relocated plant |
| 10 | Demonstration and validation workflow | done — run summaries (`verdict.py`), `controllab test`, deliberate-regression fixtures, dashboard scenarios with live verification, expected vs actual, runtime comparison (Python / Modbus / OpenPLC); `docs/DEMO.md` |

Full detail and "done when" criteria per phase: `CONTROL-LAB.md` §10.

## Technology stack

- **Python 3.12+**, no framework. `pytest` for testing.
- **`anthropic`** (Phase 8) — **optional** (`pip install -e ".[ai]"`),
  imported only inside an AI call. The core (simulation, control,
  testing, protocols, dashboard) never needs it or an API key.
- **`pymodbus`** (Phase 7 step 1) — **dev-only**, for interoperability
  tests against our own stdlib Modbus server. Never imported at runtime.
- **`pyyaml`** (Phase 3 step 1) — the first real dependency beyond
  pytest. Justified, not reflexive: it matches `CLAUDE.md` §10's own
  illustrative scenario format, and is meaningfully more readable than
  JSON for hand-authored commissioning-style test files (comments,
  less punctuation noise). "Minimal dependencies" (`CONTROL-LAB.md`
  §3.4) means justified, not zero.
- **Frontend: vanilla JS + inline SVG** (Phase 6), no build step, no
  node toolchain. The replay viewer is one template file. React only if
  UI complexity ever justifies it.
- **Live dashboard server (Phase 6 step 3): Python's stdlib
  `ThreadingHTTPServer`**, polled JSON + POSTed commands, zero new
  dependencies, bound to 127.0.0.1. This supersedes the earlier "FastAPI + React is the
  intent" note; FastAPI is the upgrade path if push or multiple clients
  become a real need. No database.
