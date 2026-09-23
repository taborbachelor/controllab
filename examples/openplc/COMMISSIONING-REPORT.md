# ControlLab — Commissioning Report

**Controller under test:** OpenPLC Runtime at http://127.0.0.1:8080, running examples/openplc/controllab_line.st

**Overall: PASS** — 25/25 scenarios passed; 11/11 interlocks covered (0 not yet applicable, 0 gap(s)).

All times are simulated seconds. Response time is measured from the moment the scenario's `when` stimulus is applied until every `expect` condition holds.

## Real-time conditions

The controller ran free on its own clock against the plant paced at real time (1×), reaching it only over Modbus TCP. Every scenario started from a fresh plant and a cold-restarted controller, brought to a clean IDLE by the operator procedure (acknowledge, reset), which is not part of the scenario's record.

- **Latency tolerance: 0.5 s** of plant time for the I/O round trip (a Modbus poll and a controller scan on each side of a hand-off). A result met after its limit but inside the tolerance is marked 🟡 *PASS within tolerance*, never counted as on time. The same allowance is the settle before `when` and the grace on the feeder-onto-an-unproven-conveyor invariant.
- **Passes: 3.** A scenario passes only if every pass passed; the result shown is the worst pass (the first failure, or else the slowest).
- Real-time results are not bit-exact: response times vary with where in the controller's scan a change lands. The lockstep report is the deterministic one.

## Scenario results

| Result | Scenario | Response | Limit | Margin | File |
|---|---|---:|---:|---:|---|
| ✅ PASS | Belt Slip Stops The Feeder And Faults The Line | 0.30 s | 0.50 s | 0.20 s | `faults/belt_slip_stops_feeder.yaml` |
| ✅ PASS | Start Refused When Bin Low | 0.20 s | 0.30 s | 0.10 s | `faults/bin_low_blocks_start.yaml` |
| ✅ PASS | Bin Low While Running Raises A Warning, Not A Trip | 0.30 s | 0.50 s | 0.20 s | `faults/bin_low_while_running_warns_only.yaml` |
| ✅ PASS | Conveyor Fails To Prove Running | 0.20 s | 0.50 s | 0.30 s | `faults/conveyor_fail_to_start.yaml` |
| ✅ PASS | Conveyor Trip While Running Faults The Line | 0.30 s | 0.50 s | 0.20 s | `faults/conveyor_trip_while_running.yaml` |
| ✅ PASS | Feeder Fails To Prove Running | 1.60 s | 3.00 s | 1.40 s | `faults/feeder_fail_to_start.yaml` |
| ✅ PASS | Feeder Jam Recovery -- Reset Refused Until The Jam Is Cleared | 0.80 s | 1.00 s | 0.20 s | `faults/feeder_jam_recovery.yaml` |
| ✅ PASS | Feeder Jam Is Detected By The Plug Switch And Faults The Line | 0.10 s | 0.20 s | 0.10 s | `faults/feeder_jam_trips_running.yaml` |
| ✅ PASS | Feeder Trip Recovery -- Reset Refused Until The Drive Is Reset | 0.40 s | 0.50 s | 0.10 s | `faults/feeder_trip_recovery.yaml` |
| ✅ PASS | Feeder Trip While Running Faults The Line | 0.30 s | 0.50 s | 0.20 s | `faults/feeder_trip_while_running.yaml` |
| ✅ PASS | Gate Fails To Prove Open | 0.50 s | 1.00 s | 0.50 s | `faults/gate_travel_timeout.yaml` |
| ✅ PASS | Start Refused When Hopper High-High | 0.20 s | 0.30 s | 0.10 s | `faults/hopper_high_high_blocks_start.yaml` |
| ✅ PASS | High-High Switch Stuck Healthy -- WT-105 Still Trips (1oo2) And The Disagreement Is Alarmed | 0.30 s | 0.50 s | 0.20 s | `faults/hopper_high_high_switch_stuck_weight_trips.yaml` |
| ✅ PASS | Broken High-High Switch Wire Trips The Line -- Fail-Safe Polarity | 0.30 s | 0.50 s | 0.20 s | `faults/hopper_high_high_switch_wire_break_trips.yaml` |
| ✅ PASS | Hopper High-High Faults The Line While Running | 0.30 s | 0.50 s | 0.20 s | `faults/hopper_high_high_trips_running.yaml` |
| ✅ PASS | Hopper High Switch Failed -- Feeding Stops And The Disagreement Warns | 0.30 s | 0.50 s | 0.20 s | `faults/hopper_high_switch_failed_disagreement_warns.yaml` |
| ✅ PASS | Start Refused While The Hopper Weight Signal Is Failed | 0.20 s | 0.30 s | 0.10 s | `faults/hopper_weight_failure_blocks_start.yaml` |
| ✅ PASS | Hopper Weight Failure Recovery -- Reset Refused Until The Signal Is Restored | 0.30 s | 0.50 s | 0.20 s | `faults/hopper_weight_failure_recovery.yaml` |
| ✅ PASS | Hopper Weight Transmitter Failure Trips A Running Line | 0.30 s | 0.50 s | 0.20 s | `faults/hopper_weight_failure_trips_running.yaml` |
| ✅ PASS | Stuck Hopper Weight Transmitter -- The Independent High-High Switch Still Trips | 0.30 s | 0.50 s | 0.20 s | `faults/hopper_weight_stuck_high_high_still_trips.yaml` |
| ✅ PASS | Start Refused While An Alarm Is Unacknowledged | 0.20 s | 0.30 s | 0.10 s | `faults/unacknowledged_alarm_blocks_start.yaml` |
| ✅ PASS | Start Blocked While E-stop Tripped | 0.20 s | 0.30 s | 0.10 s | `safety/estop_blocks_start.yaml` |
| ✅ PASS | Conveyor Emergency Stop | 0.30 s | 0.50 s | 0.20 s | `safety/estop_from_running.yaml` |
| ✅ PASS | Normal Stop Returns To Idle | 2.20 s | 3.00 s | 0.80 s | `shutdown/normal_stop.yaml` |
| ✅ PASS | Normal Start Reaches Running | 1.90 s | 3.00 s | 1.10 s | `startup/normal_start.yaml` |

## Response time across 3 passes

| Scenario | Passed | Min | Max | Each pass |
|---|---:|---:|---:|---|
| Belt Slip Stops The Feeder And Faults The Line | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Start Refused When Bin Low | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Bin Low While Running Raises A Warning, Not A Trip | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Conveyor Fails To Prove Running | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Conveyor Trip While Running Faults The Line | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Feeder Fails To Prove Running | 3/3 | 1.60 s | 1.60 s | 1.60, 1.60, 1.60 |
| Feeder Jam Recovery -- Reset Refused Until The Jam Is Cleared | 3/3 | 0.70 s | 0.80 s | 0.70, 0.70, 0.80 |
| Feeder Jam Is Detected By The Plug Switch And Faults The Line | 3/3 | 0.10 s | 0.10 s | 0.10, 0.10, 0.10 |
| Feeder Trip Recovery -- Reset Refused Until The Drive Is Reset | 3/3 | 0.30 s | 0.40 s | 0.40, 0.30, 0.30 |
| Feeder Trip While Running Faults The Line | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Gate Fails To Prove Open | 3/3 | 0.50 s | 0.50 s | 0.50, 0.50, 0.50 |
| Start Refused When Hopper High-High | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| High-High Switch Stuck Healthy -- WT-105 Still Trips (1oo2) And The Disagreement Is Alarmed | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Broken High-High Switch Wire Trips The Line -- Fail-Safe Polarity | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Hopper High-High Faults The Line While Running | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Hopper High Switch Failed -- Feeding Stops And The Disagreement Warns | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Start Refused While The Hopper Weight Signal Is Failed | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Hopper Weight Failure Recovery -- Reset Refused Until The Signal Is Restored | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Hopper Weight Transmitter Failure Trips A Running Line | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Stuck Hopper Weight Transmitter -- The Independent High-High Switch Still Trips | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Start Refused While An Alarm Is Unacknowledged | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Start Blocked While E-stop Tripped | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Conveyor Emergency Stop | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Normal Stop Returns To Idle | 3/3 | 2.20 s | 2.20 s | 2.20, 2.20, 2.20 |
| Normal Start Reaches Running | 3/3 | 1.90 s | 1.90 s | 1.90, 1.90, 1.90 |

## Interlock coverage (docs/CONTROL-LAB.md §6.3)

| Status | Interlock | Kind | Scenarios | Note |
|---|---|---|---|---|
| ✅ covered | E-stop healthy | Permissive + trip | Start Blocked While E-stop Tripped<br>Conveyor Emergency Stop | — |
| ✅ covered | No active latched alarms | Permissive | Start Refused While An Alarm Is Unacknowledged | the full latch/acknowledge lifecycle (blocked after reset, allowed once acknowledged, a recovered-but-unacknowledged warning never blocking) is proven at the pytest level, not by a single declarative scenario -- the given/when format has no way to express a multi-stage fault-then-reset-then-retry sequence without a settle tick smearing the stages together; see tests/integration/test_line_controller.py::test_start_is_refused_after_reset_until_the_alarm_is_acknowledged and the two tests immediately after it |
| ✅ covered | Hopper not high-high | Permissive | Start Refused When Hopper High-High | — |
| ✅ covered | Bin not low | Permissive | Start Refused When Bin Low<br>Bin Low While Running Raises A Warning, Not A Trip | the "warning only while running" half is proven by a scenario reaching the warning, and sustained over 10 s of running at the pytest level -- a declarative scenario passes the moment its expectations first hold, so it can't show the line never trips later; see tests/integration/test_line_controller.py::test_bin_low_while_running_stays_a_warning_for_the_whole_run |
| ✅ covered | Conveyor proven running | Permissive + trip for feeder | Belt Slip Stops The Feeder And Faults The Line | the permissive half (feeder cannot run onto a stopped belt) is proven structurally, not by a declarative scenario -- LineController's public API has no way to even attempt the wrong order; see tests/integration/test_line_controller.py::test_wrong_order_spillage_is_structurally_unreachable_through_control |
| ✅ covered | Hopper high-high | Trip | High-High Switch Stuck Healthy -- WT-105 Still Trips (1oo2) And The Disagreement Is Alarmed<br>Broken High-High Switch Wire Trips The Line -- Fail-Safe Polarity<br>Hopper High-High Faults The Line While Running<br>Stuck Hopper Weight Transmitter -- The Independent High-High Switch Still Trips | — |
| ✅ covered | Hopper level instruments agree | Alarm | Hopper High Switch Failed -- Feeding Stops And The Disagreement Warns | — |
| ✅ covered | Any motor fail-to-start / trip | Trip | Conveyor Fails To Prove Running<br>Conveyor Trip While Running Faults The Line<br>Feeder Fails To Prove Running<br>Feeder Trip Recovery -- Reset Refused Until The Drive Is Reset<br>Feeder Trip While Running Faults The Line | — |
| ✅ covered | Gate travel timeout | Trip | Gate Fails To Prove Open | — |
| ✅ covered | Feeder jam | Trip | Feeder Jam Recovery -- Reset Refused Until The Jam Is Cleared<br>Feeder Jam Is Detected By The Plug Switch And Faults The Line | — |
| ✅ covered | Hopper weight signal healthy | Permissive + trip | Start Refused While The Hopper Weight Signal Is Failed<br>Hopper Weight Failure Recovery -- Reset Refused Until The Signal Is Restored<br>Hopper Weight Transmitter Failure Trips A Running Line | — |

## Event sequences

What each scenario actually did, from its telemetry record. **setup** events come from reaching the scenario's `given` preconditions; **response** events are the system reacting to `when`.

### Belt Slip Stops The Feeder And Faults The Line — PASS

`faults/belt_slip_stops_feeder.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.00 | response | Line state running → **faulted** (conveyor lost confirmation) |
| 4.00 | response | Alarm **ZSS-104.LOST** active — Conveyor motion loss (belt slip) · **first-out** |

### Start Refused When Bin Low — PASS

`faults/bin_low_blocks_start.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.60 | setup | Warning **LSL-101.LOW** active — Bin low · **first-out** |
| 1.90 | response | Operator command: **start** |

### Bin Low While Running Raises A Warning, Not A Trip — PASS

`faults/bin_low_while_running_warns_only.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 4.10 | response | Warning **LSL-101.LOW** active — Bin low · **first-out** |

### Conveyor Fails To Prove Running — PASS

`faults/conveyor_fail_to_start.yaml`

Stages: 1: 0.20 s / 0.50 s · 2: 1.00 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 3.00 | response | Line state starting → **faulted** (conveyor failed to prove running) |
| 3.00 | response | Alarm **M-104.START_PROOF** active — Conveyor failed to prove running · **first-out** |

### Conveyor Trip While Running Faults The Line — PASS

`faults/conveyor_trip_while_running.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 4.10 | response | Line state running → **faulted** (conveyor trip) |
| 4.10 | response | Alarm **M-104.OL** active — Conveyor trip (overload) · **first-out** |

### Feeder Fails To Prove Running — PASS

`faults/feeder_fail_to_start.yaml`

Stages: 1: 1.60 s / 3.00 s · 2: 1.00 s / 5.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 4.40 | response | Line state starting → **faulted** (feeder failed to prove running) |
| 4.40 | response | Alarm **M-103.START_PROOF** active — Feeder failed to prove running · **first-out** |

### Feeder Jam Recovery -- Reset Refused Until The Jam Is Cleared — PASS

`faults/feeder_jam_recovery.yaml`

Stages: 1: 0.80 s / 1.00 s · 2: 0.20 s / 1.00 s · 3: 0.30 s / 1.00 s · 4: 0.20 s / 1.00 s · 5: 1.90 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.50 | response | Line state running → **faulted** (feeder jam) |
| 4.50 | response | Alarm **LSH-103.JAM** active — Feeder jam (discharge chute plugged) · **first-out** |
| 4.60 | response | Operator command: **acknowledge** |
| 4.60 | response | Operator command: **reset** |
| 4.70 | response | Alarm LSH-103.JAM acknowledged |
| 5.00 | response | Alarm LSH-103.JAM cleared |
| 5.10 | response | Operator command: **reset** |
| 5.20 | response | Line state faulted → **idle** |
| 5.30 | response | Operator command: **start** |
| 5.40 | response | Line state idle → **starting** |
| 7.10 | response | Line state starting → **running** |

### Feeder Jam Is Detected By The Plug Switch And Faults The Line — PASS

`faults/feeder_jam_trips_running.yaml`

Stages: 1: 0.10 s / 0.20 s · 2: 0.60 s / 1.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.40 | response | Line state running → **faulted** (feeder jam) |
| 4.40 | response | Alarm **LSH-103.JAM** active — Feeder jam (discharge chute plugged) · **first-out** |

### Feeder Trip Recovery -- Reset Refused Until The Drive Is Reset — PASS

`faults/feeder_trip_recovery.yaml`

Stages: 1: 0.40 s / 0.50 s · 2: 0.20 s / 1.00 s · 3: 0.30 s / 1.00 s · 4: 0.20 s / 1.00 s · 5: 2.00 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 4.20 | response | Line state running → **faulted** (feeder trip) |
| 4.20 | response | Alarm **M-103.FAULT** active — Feeder trip (VFD fault/overload) · **first-out** |
| 4.30 | response | Operator command: **acknowledge** |
| 4.30 | response | Operator command: **reset** |
| 4.40 | response | Alarm M-103.FAULT acknowledged |
| 4.70 | response | Alarm M-103.FAULT cleared |
| 4.80 | response | Operator command: **reset** |
| 4.90 | response | Line state faulted → **idle** |
| 5.00 | response | Operator command: **start** |
| 5.10 | response | Line state idle → **starting** |
| 6.90 | response | Line state starting → **running** |

### Feeder Trip While Running Faults The Line — PASS

`faults/feeder_trip_while_running.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 4.10 | response | Line state running → **faulted** (feeder trip) |
| 4.10 | response | Alarm **M-103.FAULT** active — Feeder trip (VFD fault/overload) · **first-out** |

### Gate Fails To Prove Open — PASS

`faults/gate_travel_timeout.yaml`

Stages: 1: 0.50 s / 1.00 s · 2: 2.00 s / 5.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 4.30 | response | Line state starting → **faulted** (gate failed to prove open) |
| 4.30 | response | Alarm **XV-102.TRAVEL_FAULT** active — Gate travel fault · **first-out** |

### Start Refused When Hopper High-High — PASS

`faults/hopper_high_high_blocks_start.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.60 | setup | Alarm **WT-105.HIGH_HIGH** active — Hopper high-high · **first-out** |
| 1.90 | response | Operator command: **start** |

### High-High Switch Stuck Healthy -- WT-105 Still Trips (1oo2) And The Disagreement Is Alarmed — PASS

`faults/hopper_high_high_switch_stuck_weight_trips.yaml`

Stages: 1: 0.30 s / 0.50 s · 2: 0.90 s / 1.50 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 4.10 | response | Line state running → **faulted** (hopper high-high) |
| 4.10 | response | Alarm **WT-105.HIGH_HIGH** active — Hopper high-high · **first-out** |
| 5.00 | response | Alarm **LSHH-105.DISAGREE** active — Hopper high-high switch disagrees with WT-105 |

### Broken High-High Switch Wire Trips The Line -- Fail-Safe Polarity — PASS

`faults/hopper_high_high_switch_wire_break_trips.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.00 | response | Line state running → **faulted** (hopper high-high) |
| 4.00 | response | Alarm **WT-105.HIGH_HIGH** active — Hopper high-high · **first-out** |

### Hopper High-High Faults The Line While Running — PASS

`faults/hopper_high_high_trips_running.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.00 | response | Line state running → **faulted** (hopper high-high) |
| 4.00 | response | Alarm **WT-105.HIGH_HIGH** active — Hopper high-high · **first-out** |

### Hopper High Switch Failed -- Feeding Stops And The Disagreement Warns — PASS

`faults/hopper_high_switch_failed_disagreement_warns.yaml`

Stages: 1: 0.30 s / 0.50 s · 2: 0.90 s / 1.50 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 5.00 | response | Warning **LSH-105.DISAGREE** active — Hopper high switch disagrees with WT-105 · **first-out** |

### Start Refused While The Hopper Weight Signal Is Failed — PASS

`faults/hopper_weight_failure_blocks_start.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.60 | setup | Alarm **WT-105.FAIL** active — Hopper weight transmitter failed · **first-out** |
| 1.90 | response | Operator command: **start** |

### Hopper Weight Failure Recovery -- Reset Refused Until The Signal Is Restored — PASS

`faults/hopper_weight_failure_recovery.yaml`

Stages: 1: 0.30 s / 0.50 s · 2: 0.20 s / 1.00 s · 3: 0.30 s / 1.00 s · 4: 0.30 s / 1.00 s · 5: 2.00 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 4.10 | response | Line state running → **faulted** (hopper weight signal failed) |
| 4.10 | response | Alarm **WT-105.FAIL** active — Hopper weight transmitter failed · **first-out** |
| 4.20 | response | Operator command: **acknowledge** |
| 4.20 | response | Operator command: **reset** |
| 4.30 | response | Alarm WT-105.FAIL acknowledged |
| 4.60 | response | Alarm WT-105.FAIL cleared |
| 4.70 | response | Operator command: **reset** |
| 4.90 | response | Line state faulted → **idle** |
| 5.00 | response | Operator command: **start** |
| 5.10 | response | Line state idle → **starting** |
| 6.90 | response | Line state starting → **running** |

### Hopper Weight Transmitter Failure Trips A Running Line — PASS

`faults/hopper_weight_failure_trips_running.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.00 | response | Line state running → **faulted** (hopper weight signal failed) |
| 4.00 | response | Alarm **WT-105.FAIL** active — Hopper weight transmitter failed · **first-out** |

### Stuck Hopper Weight Transmitter -- The Independent High-High Switch Still Trips — PASS

`faults/hopper_weight_stuck_high_high_still_trips.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.00 | response | Line state running → **faulted** (hopper high-high) |
| 4.00 | response | Alarm **WT-105.HIGH_HIGH** active — Hopper high-high · **first-out** |

### Start Refused While An Alarm Is Unacknowledged — PASS

`faults/unacknowledged_alarm_blocks_start.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.60 | setup | Alarm **WT-105.HIGH_HIGH** active — Hopper high-high · **first-out** |
| 1.90 | response | Operator command: **start** |

### Start Blocked While E-stop Tripped — PASS

`safety/estop_blocks_start.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.60 | setup | Line state idle → **estopped** (e-stop) |
| 1.60 | setup | Alarm **ES-001.TRIP** active — E-stop tripped · **first-out** |
| 1.90 | response | Operator command: **start** |

### Conveyor Emergency Stop — PASS

`safety/estop_from_running.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.00 | response | Line state running → **estopped** (e-stop) |
| 4.00 | response | Alarm **ES-001.TRIP** active — E-stop tripped · **first-out** |

### Normal Stop Returns To Idle — PASS

`shutdown/normal_stop.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 3.90 | response | Operator command: **stop** |
| 4.00 | response | Line state running → **stopping** |
| 6.00 | response | Line state stopping → **idle** |

### Normal Start Reaches Running — PASS

`startup/normal_start.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 3.70 | response | Line state starting → **running** |
