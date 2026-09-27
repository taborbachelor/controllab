# Writing and running your own scenarios

A scenario is a YAML file that states what the control logic must do in one
situation: the starting conditions, what happens (an operator action, a
fault, a process change), what must follow, and how fast. The runner plays it
against the simulated line and checks every expectation on every scan. This
page is the complete reference: every key a scenario can use, the values it
can expect, and the rules that keep a scenario honest.

The 65 scenarios in [`scenarios/`](../scenarios/) are working examples of
everything here.

## A first scenario

```yaml
name: E-stop from running
description: "Pressing the E-stop with the line running takes every motor off at once."

given:
  line_state: running          # drive the line to RUNNING first

when:
  estop: tripped               # the stimulus

expect:
  line_state: estopped
  conveyor_run_commanded: false
  feeder_run_commanded: false
  first_out: ES-001.TRIP

within:
  seconds: 0.5                 # every expectation must hold within 0.5 s
```

Save it anywhere (outside `scenarios/`) and run it:

```bash
controllab test my_scenarios/estop.yaml       # one file
controllab test my_scenarios/                 # every .yaml file under a directory
controllab test my_scenarios/ -v              # the full result for each, passed or not
controllab test my_scenarios/ --runtime modbus     # the same controller, over Modbus TCP
controllab test my_scenarios/ --runtime openplc    # OpenPLC in real time (examples/openplc set up first)
```

The result shows each stage, every check as **MATCH** or **MISMATCH** with the
actual value, the response time against the limit, the first-out alarm and,
on a failure, the first point where the run left the scenario. The exit
status is 1 if anything failed, so it drops into CI as it is.

Before you trust a new scenario, put it through the review gate:

```bash
python scripts/review_candidates.py my_scenarios/
```

It checks that the file loads, uses only the vocabulary below, is
deterministic, agrees across Modbus, and is **not vacuous**: it re-runs the
scenario with its stimulus removed (and with each later stage's actions
removed) and rejects it if it still passes. A scenario that passes whether or
not the fault happens proves nothing. Keep files you're reviewing outside
`scenarios/`; the gate refuses files already inside it.

## The file

| Key | Required | What it is |
|---|---|---|
| `name` | yes | The scenario's name, as results show it. |
| `description` | no | One line: what the scenario proves. For people; the runner ignores it. |
| `given` | no | Preconditions, applied and settled before anything else (below). |
| `when` | no | The stimulus: actions applied once `given` has settled. |
| `trigger` | no | The `when` key(s) that *are* the stimulus, as opposed to setup riding along in the same `when`. The review gate removes exactly these to prove the scenario depends on them. A string or a list. |
| `expect` | yes | Fields and the values they must reach. |
| `within` | yes | The time limit for `expect`: `{seconds: 1.0}` or `{milliseconds: 500}`. |
| `title` | no | The first stage's purpose, in words. |
| `then` | no | Further stages, in order: each a mapping of `when` (optional), `expect`, `within` and `title` (optional). |
| `interlock` | no | The row of the interlock table ([`CONTROL-LAB.md`](CONTROL-LAB.md) §6.3) this scenario covers, **verbatim**, for the coverage matrix in the commissioning report. |

An unknown key, in the file or in `given`/`when`/`expect`, is an error, not
ignored: a typo fails loudly instead of producing a scenario that checks
nothing.

## How a scenario runs

1. **`given`** is applied. `line_state` is reached by actually operating the
   line (pressing Start and waiting for RUNNING, or selecting a mode); every
   other key is applied directly. The result is then settled for two scans,
   published through the I/O and seen by the controller, before anything
   else happens.
2. **`when`** is applied, and the runner checks **`expect`** on every scan
   until every expectation holds at once. If they don't all hold by the
   `within` limit, the stage fails, with each check's actual value.
3. Each stage in **`then`** applies its `when` the scan after the previous
   stage's expectations held, the way an operator acts on what the HMI shows,
   and gets its own `within`.
4. On **every scan** of every scenario the runner also checks the physical
   invariants: mass is conserved, the feeder never runs onto a belt not
   proven running (beyond one scan), and no motor is energized while the
   E-stop is tripped. Breaking one fails the scenario whatever it expects.

A stage passes the moment its expectations first hold. That is the most
important thing to know when writing one; see *Writing a scenario that proves
something* below.

### The test rig

Scenarios run on the test rig (`services/testing/rig.py`), not on the
full-size line: the same equipment and logic with short timers, so the whole
suite runs in about a minute. Limits in a scenario are written against these
values:

| | Test rig | Full-size default |
|---|---|---|
| Scan | 0.1 s | 0.1 s |
| Bins A, B, C | 10,000 kg each, starting at 20 %; low switch at 10 % | same |
| Gate travel | 1 s (travel fault at 2 s) | 2 s (5 s) |
| Feeder | 5 kg/s at full speed | same |
| Belt transit | 2 s (4 m at 2 m/s) | 10 s (20 m) |
| Motor proof windows | 1 s | 3 s |
| Stop purge | 2 s | 15 s |
| Hopper | 2,000 kg; high switch 80 %, high-high 95 %, feed restarts below 60 % | same |
| Downstream draw | 3 kg/s | same |
| No flow on the belt (warning; a trip in a batch) | 4 s | 15 s |
| Batch: preact / empty / tolerance / discharge timeout | 10 kg / 2 kg / 5 kg / 600 s | 50 kg / 5 kg / 10 kg / 900 s |

Against a free-running controller (`--runtime openplc`, or
`scenario_report.py --realtime`) the plant runs in real time and each limit
gets an I/O latency allowance of 0.5 s; a pass that needed it is marked
`PASS~` so it is never mistaken for a clean one.

## Actions: `given` and `when`

`true` presses a pushbutton or injects a fault; for a fault, `false` removes
it again (the physical cause is gone). A controller's own latched alarm still
needs acknowledging and a reset, exactly as on a real line.

**Starting state** (`given` only)

| Key | Value |
|---|---|
| `line_state` | `idle` (the default), `running` (Auto, started and running), `manual` (Manual mode selected, at rest) or `batch` (Batch mode selected, at rest) |

**Operator commands**

| Key | Value | What it does |
|---|---|---|
| `start` | `true` | Start (Auto: the start sequence; Batch: one batch) |
| `stop` | `true` | Stop (the stop sequence; in Manual, every device off) |
| `reset` | `true` | Reset a FAULTED or ESTOPPED line |
| `acknowledge` | `true` | Acknowledge the alarms |
| `select_auto`, `select_manual`, `select_batch` | `true` | Change mode (only at rest) |

**Manual-mode pushbuttons**

| Key | Value | What it does |
|---|---|---|
| `start_conveyor`, `stop_conveyor` | `true` | The conveyor |
| `open_gate`, `close_gate` | `true` | The source bin's gate |
| `start_feeder`, `stop_feeder` | `true` | The feeder |
| `open_outlet`, `close_outlet` | `true` | The hopper outlet gate |

**HMI setpoints**

| Key | Value | What it does |
|---|---|---|
| `source_bin` | `A`, `B` or `C` | The bin the next start draws from |
| `recipe` | `{A: kg, B: kg, C: kg}` (a bin left out is 0) | The batch recipe |
| `hold_s` | seconds, ≥ 0 | The batch hold time |

**Equipment faults** (`true` injects, `false` removes)

| Key | The fault |
|---|---|
| `conveyor_trip` | The conveyor motor's overload trips (`M-104.OL`) |
| `feeder_trip` | The feeder's drive faults (`M-103.FAULT`) |
| `conveyor_fail_to_start` | The conveyor is commanded but never runs |
| `feeder_fail_to_start` | The feeder is commanded but never runs |
| `belt_slip` | The conveyor motor runs but the belt doesn't move (`ZSS-104` stays off) |
| `conveyor_jam` | The belt stops and holds its load; the motor strains at about 2.5 × full-load current until its overload trips |
| `feeder_jam` | The feeder runs but nothing flows; the discharge-chute plug switch `LSH-103` makes after 0.5 s (2 s full-size) |
| `bin_bridged` | Bin A reads full but nothing discharges |
| `gate_stuck`, `gate_b_stuck`, `gate_c_stuck` | The bin gate's travel never completes |
| `outlet_stuck` | The hopper outlet gate's travel never completes |
| `outlet_plugged` | The outlet is open but nothing leaves the hopper |

**Field repairs** (`true` performs it; there is no I/O for these, as on a real
line where someone walks to the equipment)

| Key | The repair |
|---|---|
| `feeder_drive_reset` | Reset the feeder's drive fault at the drive |
| `conveyor_overload_reset` | Reset the conveyor's overload relay |
| `gate_reset`, `gate_b_reset`, `gate_c_reset` | Reset the bin gate's actuator |
| `outlet_reset` | Reset the outlet gate's actuator |

**Instrument faults**: the value names an input tag (any of
[`CONTROL-LAB.md`](CONTROL-LAB.md) §5.3's `AI` and `DI` tags)

| Key | Value | The fault |
|---|---|---|
| `sensor_stuck` | a tag | Keeps its last reading. Nothing in the signal says it's wrong |
| `sensor_failed` | a tag | Signal lost: an analog input reads bottom of range (`WT-105` also sets its channel diagnostic `WT-105.FLT`); a switch reads 0, which a fail-safe switch reports as tripped |
| `sensor_noise` | `{tag: WT-105, amplitude: 30}` | Reads within ± the amplitude of the truth (seeded, so reproducible) |
| `sensor_drift` | `{tag: WT-105, rate_per_s: -10}` | An error that grows at the rate per second |
| `sensor_slow` | `{tag: ZSS-104, seconds: 1.5}` | Reports what was true that many seconds ago |
| `sensor_restored` | a tag | Repaired: reads the truth again |

**Process conditions**

| Key | Value | What it sets |
|---|---|---|
| `bin_level_pct`, `bin_b_level_pct`, `bin_c_level_pct` | % of capacity | A bin's contents |
| `hopper_level_pct` | % of capacity | The hopper's contents |
| `downstream_stopped` | `true` / `false` | The downstream consumer (`DS-107`) stops taking material, or resumes |
| `estop` | `tripped` / `healthy` | The E-stop is pressed, or released |

## Expectations: `expect`

Numbers match within 1 part in a million; everything else must be equal.

**From the controller's status.** An external controller that doesn't publish
ControlLab's status block (see [`MODBUS-MAP.md`](MODBUS-MAP.md)) can't be
asked for these: against it, an expectation on one of them is reported as
*not observed*, never as passed or failed.

| Field | Value |
|---|---|
| `line_state` | One of the line states below |
| `mode` | `auto`, `manual` or `batch` |
| `fault_reason` | The trip reason, one of the strings below, or `null` |
| `first_out` | The id of the alarm that started this episode, or `null` |
| `latched_alarm_ids` | The latched alarms' ids, sorted: a list, `[]` for none |
| `any_unacknowledged_trip` | `true` if any trip-class alarm is unacknowledged |
| `start_inhibit` | Why the most recent start, reset, mode change or device start was refused: the reason names below, sorted, or `["NONE"]` if it was accepted |
| `source_bin` | `A`, `B` or `C`: the bin the next start draws from |
| `active_bin` | `A`, `B`, `C`, or `none` at rest: the bin in use |
| `batch_loaded_kg` | This (or the last) batch's weigh-in, kg |
| `batches_completed` | Batches completed |

**The controller's outputs**: what it is commanding the field to do, readable
from any controller.

| Field | The output |
|---|---|
| `conveyor_run_commanded` | `M-104.RUN` |
| `feeder_run_commanded` | `M-103.RUN` |
| `gate_open_commanded`, `gate_b_open_commanded`, `gate_c_open_commanded` | `XV-102/112/122.CMD_OPEN` |
| `outlet_open_commanded` | `XV-106.CMD_OPEN` |

**The field**: what the equipment is actually doing.

| Field | Value |
|---|---|
| `conveyor_running`, `feeder_running` | The motor is running |
| `feeder_flowing` | Material is actually leaving the feeder (a jammed feeder runs without flowing) |
| `gate_open`, `gate_b_open`, `gate_c_open`, `outlet_open` | The gate is fully open |
| `gates_closed` | Every bin gate and the outlet at its closed limit switch (what Start waits for) |
| `downstream_ready` | `DS-107.READY` as the line sees it |
| `discharging` | Material is leaving the hopper for the downstream |
| `estop_healthy` | The E-stop is released |
| `belt_empty` | Nothing left on the conveyor |
| `spilled`, `spilled_kg` | Any material spilled; how much, kg |
| `hopper_level_kg` | The hopper's true contents, kg |
| `hopper_weight_agrees` | `WT-105` reads within 5 kg of the truth (false when it is stuck, failed or drifting) |

### Values

**Line states** (`line_state`): `idle`, `starting`, `running`, `stopping`,
`faulted`, `estopped`, `manual`, and the batch states `loading`,
`processing`, `discharging`, `cleaning`.

**Refusal reasons** (`start_inhibit`):

| Name | Refused because |
|---|---|
| `BIN_LOW` | The source bin (or a recipe bin) is at its low switch |
| `HOPPER_HIGH_HIGH` | The hopper is at high-high |
| `HOPPER_HIGH` | Manual feeder start with the hopper at its high switch |
| `UNACKNOWLEDGED_ALARM` | A trip alarm is not yet acknowledged |
| `ESTOP_ACTIVE` | The E-stop is pressed |
| `LINE_FAULTED` | Start while FAULTED: reset first |
| `SENSOR_FAILED` | The hopper weight signal has failed (`WT-105.FLT`) |
| `CONVEYOR_NOT_RUNNING` | Manual feeder start without the conveyor proven running |
| `WRONG_MODE` | A device pushbutton outside Manual, or the line Start in Manual |
| `LINE_NOT_IDLE` | A mode change away from rest, or Start while the line is already starting, running, stopping or mid-batch |
| `RECIPE_EMPTY` | A batch start with nothing in the recipe |
| `RECIPE_TOO_LARGE` | The recipe wouldn't fit under the hopper's high switch |
| `HOPPER_NOT_EMPTY` | A batch starts only from an empty hopper |
| `GATE_NOT_CLOSED` | A bin gate or the outlet is not proven closed |
| `DOWNSTREAM_NOT_READY` | Manual outlet open with the downstream not ready |
| `CAUSE_STANDING` | Reset while the trip's cause is still present |

**Trip reasons** (`fault_reason`): `e-stop`, `hopper high-high`,
`feeder trip`, `conveyor trip`, `feeder failed to prove running`,
`conveyor failed to prove running`, `gate failed to prove open`,
`conveyor lost confirmation`, `gate travel fault`, `feeder jam`,
`hopper weight signal failed`, `conveyor jam`, `outlet travel fault`,
`discharge timeout`, `batch feed stalled`.

**Alarm ids** (`first_out`, `latched_alarm_ids`). A *warning* never blocks a
start; a *trip* alarm must be acknowledged before one.

| Id | Alarm | Class |
|---|---|---|
| `ES-001.TRIP` | E-stop tripped | trip |
| `LSL-101.LOW` | Bin A low | warning |
| `LSL-111.LOW` | Bin B low | warning |
| `LSL-121.LOW` | Bin C low | warning |
| `XV-102.TRAVEL_FAULT` | Bin A gate travel fault | trip |
| `XV-112.TRAVEL_FAULT` | Bin B gate travel fault | trip |
| `XV-122.TRAVEL_FAULT` | Bin C gate travel fault | trip |
| `M-103.FAULT` | Feeder trip (VFD fault/overload) | trip |
| `M-103.START_PROOF` | Feeder failed to prove running | trip |
| `LSH-103.JAM` | Feeder jam (discharge chute plugged) | trip |
| `M-104.OL` | Conveyor trip (overload) | trip |
| `M-104.START_PROOF` | Conveyor failed to prove running | trip |
| `ZSS-104.LOST` | Conveyor motion loss (belt slip) | trip |
| `IT-104.HIGH` | Conveyor motor overcurrent (jam) | trip |
| `FT-104.NO_FLOW` | No flow on the belt while feeding | warning |
| `WT-105.HIGH_HIGH` | Hopper high-high | trip |
| `WT-105.FAIL` | Hopper weight transmitter failed | trip |
| `LSH-105.DISAGREE` | Hopper high switch disagrees with WT-105 | warning |
| `LSHH-105.DISAGREE` | Hopper high-high switch disagrees with WT-105 | trip |
| `XV-106.TRAVEL_FAULT` | Hopper outlet gate travel fault | trip |
| `HOP-105.NOT_EMPTYING` | Batch discharge didn't empty the hopper | trip |
| `BATCH.TOLERANCE` | Batch weighed in out of tolerance | warning |

## Writing a scenario that proves something

A stage passes the moment its expectations first hold, so the easy mistake is
a scenario that passes without the behavior it claims to test. These rules
come from mistakes made and caught while writing the suite.

- **Preconditions go in `given`, the stimulus in `when`.** `given` settles
  before anything is checked; `when` doesn't. A level that is already high
  before the operator acts belongs in `given`; a level change the controller
  must react to belongs in `when`.
- **A refusal must expect something only the refusal produces.** "The line
  is still faulted" is already true before the reset is even read, so it
  can't show the reset was refused. Expect `start_inhibit` (the refusal's
  reason) as well.
- **Don't race the field.** An action and the field change it depends on
  can't share a stage: the controller scans before the plant publishes, so
  the action is judged on the old reading. Release the E-stop in one stage
  and reset in the next; after a trip, wait for `gates_closed: true` before
  pressing Start (the gates need their travel time to close).
- **Say what's true about the process.** In Auto the hopper drains to the
  downstream while the line runs; a scenario about level protection that
  needs the hopper to hold sets `downstream_stopped: true` in `given`.
- **Never widen a limit to fit a measurement.** A limit is the requirement.
  If it has to change because the requirement changed, say why in a comment.
- **Prove it fails without the stimulus.** Declare `trigger:` and run the
  review gate. Better still, break the controller on purpose and watch the
  scenario catch it: `controllab test --list-regressions` shows the
  deliberately broken builds the suite is proven against.

## A multi-stage scenario: a trip and its recovery

```yaml
name: Feeder trip -- reset refused until the drive is reset
description: "A feeder drive fault trips the line; reset is refused while the drive is still faulted; resetting the drive, then the line, returns it to IDLE."
title: "The drive fault trips the line"

given:
  line_state: running

when:
  feeder_trip: true

trigger: feeder_trip

expect:
  line_state: faulted
  fault_reason: "feeder trip"
  feeder_run_commanded: false
  first_out: M-103.FAULT

within:
  seconds: 1.0

then:
  - title: "Reset is refused while the drive is still faulted"
    when:
      acknowledge: true
      reset: true
    expect:
      line_state: faulted
      start_inhibit: ["CAUSE_STANDING"]
    within:
      seconds: 1.0
  - title: "The cause is removed and the drive reset at the drive"
    when:
      feeder_trip: false
      feeder_drive_reset: true
    expect:
      latched_alarm_ids: []
    within:
      seconds: 3.0
  - title: "Reset is accepted"
    when:
      reset: true
    expect:
      line_state: idle
      start_inhibit: ["NONE"]
    within:
      seconds: 1.0

interlock: "Any motor fail-to-start / trip"
```

## A refused start

```yaml
name: Start refused with the source bin low
description: "With bin A at 5 %, below its low switch, Start is refused and says why; nothing moves."

given:
  bin_level_pct: 5

when:
  start: true

trigger: start

expect:
  line_state: idle
  start_inhibit: ["BIN_LOW"]
  conveyor_run_commanded: false

within:
  seconds: 0.5

interlock: "Bin not low"
```

## Where to go from here

- [`CONTROL-LAB.md`](CONTROL-LAB.md) §5 (the equipment, I/O and faults) and
  §6 (modes, states and the interlock table) are the behavior the scenarios
  check.
- `python scripts/scenario_report.py --markdown report.md` runs the whole
  suite into a commissioning report with the interlock coverage matrix.
