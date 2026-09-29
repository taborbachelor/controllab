# ControlLab — Commissioning Report

**Build:** controllab 1.0.0, git 1ce4cce

**Controller under test:** OpenPLC Runtime at http://127.0.0.1:8080, running examples/openplc/controllab_line.st

**Overall: PASS** — 65/65 scenarios passed; 19/19 interlocks covered (0 not yet applicable, 0 gap(s)).

All times are simulated seconds. Response time is measured from the moment the scenario's `when` stimulus is applied until every `expect` condition holds.

## Real-time conditions

The controller ran free on its own clock against the plant paced at real time (1×), reaching it only over Modbus TCP. Every scenario started from a fresh plant and a cold-restarted controller, brought to a clean IDLE by the operator procedure (acknowledge, reset), which is not part of the scenario's record.

- **Latency tolerance: 0.5 s** of plant time for the I/O round trip (a Modbus poll and a controller scan on each side of a hand-off). A result met after its limit but inside the tolerance is marked 🟡 *PASS within tolerance*, never counted as on time. The same allowance is the settle before `when` and the grace on the feeder-onto-an-unproven-conveyor invariant.
- **Passes: 3.** A scenario passes only if every pass passed; the result shown is the worst pass (the first failure, or else the slowest).
- Real-time results are not bit-exact: response times vary with where in the controller's scan a change lands. The lockstep report is the deterministic one.

## Scenario results

| Result | Scenario | Response | Limit | Margin | File |
|---|---|---:|---:|---:|---|
| ✅ PASS | A Batch -- Load From Two Bins, Hold, Discharge, Clean Out | 1.80 s | 3.00 s | 1.20 s | `batch/batch_cycle.yaml` |
| ✅ PASS | A Discharge That Never Empties The Hopper Times Out | 13.70 s | 30.00 s | 16.30 s | `batch/batch_discharge_timeout.yaml` |
| ✅ PASS | A Batch Discharge Waits For The Downstream | 13.80 s | 40.00 s | 26.20 s | `batch/batch_discharge_waits_for_downstream.yaml` |
| ✅ PASS | A Batch Dose That Stops Flowing Trips The Batch | 1.80 s | 3.00 s | 1.20 s | `batch/batch_feed_stalls_on_a_bridged_bin.yaml` |
| ✅ PASS | A Batch Weighed In Out Of Tolerance Raises A Warning | 0.20 s | 3.00 s | 2.80 s | `batch/batch_out_of_tolerance_warns.yaml` |
| ✅ PASS | A Hopper Outlet That Won't Open Trips The Discharge | 13.80 s | 30.00 s | 16.20 s | `batch/batch_outlet_stuck_trips_the_discharge.yaml` |
| 🟡 PASS within tolerance | A Batch Starts Only With A Recipe That Fits, Into An Empty Hopper | 0.20 s | 0.30 s | 0.10 s | `batch/batch_start_permissives.yaml` |
| ✅ PASS | Stop Aborts A Batch | 1.80 s | 3.00 s | 1.20 s | `batch/stop_aborts_a_batch.yaml` |
| ✅ PASS | Bin B's Gate Fails To Prove Open | 0.60 s | 1.00 s | 0.40 s | `bins/bin_b_gate_fails_to_prove_open.yaml` |
| ✅ PASS | A Bin Gate That Won't Close On Stop Trips The Line | 2.20 s | 3.00 s | 0.80 s | `bins/bin_gate_that_wont_close_trips_the_stop.yaml` |
| ✅ PASS | Running From Bin B -- Only Bin B's Gate Opens | 1.90 s | 3.00 s | 1.10 s | `bins/run_from_bin_b.yaml` |
| 🟡 PASS within tolerance | Only The Source Bin's Low Switch Refuses A Start | 0.20 s | 0.30 s | 0.10 s | `bins/source_bin_low_blocks_start.yaml` |
| ✅ PASS | A Source Bin Change During A Run Waits For The Next Start | 0.20 s | 0.30 s | 0.10 s | `bins/source_change_waits_for_the_next_start.yaml` |
| ✅ PASS | The Hopper Buffers Between The Feed And A Ready Downstream | 2.70 s | 4.00 s | 1.30 s | `downstream/buffer_feeds_a_ready_downstream.yaml` |
| ✅ PASS | A Downstream Stop Closes The Outlet Without Tripping The Line | 0.30 s | 0.50 s | 0.20 s | `downstream/downstream_stop_closes_the_outlet.yaml` |
| ✅ PASS | Alarm Lifecycle -- Start Refused Until Acknowledged, Even After The Cause Clears | 0.40 s | 0.50 s | 0.10 s | `faults/alarm_lifecycle_start_refused_until_acknowledged.yaml` |
| ✅ PASS | Belt Slip During The Stop Purge Trips The Line | 0.20 s | 0.50 s | 0.30 s | `faults/belt_slip_during_stop_trips.yaml` |
| ✅ PASS | Belt Slip Stops The Feeder And Faults The Line | 0.30 s | 0.50 s | 0.20 s | `faults/belt_slip_stops_feeder.yaml` |
| ✅ PASS | Material Bridging In The Bin Is Caught By The Belt Scale | 6.10 s | 10.00 s | 3.90 s | `faults/bin_bridging_caught_by_the_belt_scale.yaml` |
| ✅ PASS | Start Refused When Bin Low | 0.20 s | 0.30 s | 0.10 s | `faults/bin_low_blocks_start.yaml` |
| ✅ PASS | Bin Low While Running Raises A Warning, Not A Trip | 0.30 s | 0.50 s | 0.20 s | `faults/bin_low_while_running_warns_only.yaml` |
| ✅ PASS | Conveyor Fails To Prove Running | 0.20 s | 0.50 s | 0.30 s | `faults/conveyor_fail_to_start.yaml` |
| ✅ PASS | A Conveyor Jam Trips The Line, Diagnosed From The Motor Current | 0.30 s | 0.50 s | 0.20 s | `faults/conveyor_jam_trips_as_a_jam.yaml` |
| ✅ PASS | A Conveyor Jam Behind A Stuck Motion Switch Is Caught By Overcurrent | 1.20 s | 1.50 s | 0.30 s | `faults/conveyor_jam_with_stuck_motion_switch_caught_by_overcurrent.yaml` |
| ✅ PASS | Conveyor Trip Recovery -- Reset Refused Until The Overload Is Reset | 0.30 s | 0.50 s | 0.20 s | `faults/conveyor_trip_recovery.yaml` |
| ✅ PASS | Conveyor Trip While Running Faults The Line | 0.40 s | 0.50 s | 0.10 s | `faults/conveyor_trip_while_running.yaml` |
| ✅ PASS | Feeder Fails To Prove Running | 1.60 s | 3.00 s | 1.40 s | `faults/feeder_fail_to_start.yaml` |
| ✅ PASS | Feeder Fails To Restart Mid-Run -- Level Control Asks, The Drive Never Runs, The Line Trips | 1.30 s | 2.00 s | 0.70 s | `faults/feeder_fails_to_restart_trips.yaml` |
| ✅ PASS | Feeder Jam Recovery -- Reset Refused Until The Jam Is Cleared | 0.80 s | 1.00 s | 0.20 s | `faults/feeder_jam_recovery.yaml` |
| ✅ PASS | Feeder Jam Is Detected By The Plug Switch And Faults The Line | 0.10 s | 0.20 s | 0.10 s | `faults/feeder_jam_trips_running.yaml` |
| ✅ PASS | Feeder Trip Recovery -- Reset Refused Until The Drive Is Reset | 0.30 s | 0.50 s | 0.20 s | `faults/feeder_trip_recovery.yaml` |
| ✅ PASS | Feeder Trip While Running Faults The Line | 0.40 s | 0.50 s | 0.10 s | `faults/feeder_trip_while_running.yaml` |
| ✅ PASS | A Gate Stuck Open Blocks The Next Start | 2.20 s | 3.00 s | 0.80 s | `faults/gate_stuck_open_blocks_start.yaml` |
| ✅ PASS | Gate Fails To Prove Open | 0.50 s | 1.00 s | 0.50 s | `faults/gate_travel_timeout.yaml` |
| ✅ PASS | Start Refused When Hopper High-High | 0.20 s | 0.30 s | 0.10 s | `faults/hopper_high_high_blocks_start.yaml` |
| ✅ PASS | High-High Switch Stuck Healthy -- WT-105 Still Trips (1oo2) And The Disagreement Is Alarmed | 0.70 s | 1.00 s | 0.30 s | `faults/hopper_high_high_switch_stuck_weight_trips.yaml` |
| ✅ PASS | Broken High-High Switch Wire Trips The Line -- Fail-Safe Polarity | 0.30 s | 0.50 s | 0.20 s | `faults/hopper_high_high_switch_wire_break_trips.yaml` |
| ✅ PASS | Hopper High-High Faults The Line While Running | 0.30 s | 0.50 s | 0.20 s | `faults/hopper_high_high_trips_running.yaml` |
| ✅ PASS | Hopper High Switch Failed -- Feeding Stops And The Disagreement Warns | 0.30 s | 0.50 s | 0.20 s | `faults/hopper_high_switch_failed_disagreement_warns.yaml` |
| ✅ PASS | A Drifting Hopper Weight Transmitter Is Caught At The High Switch | 42.30 s | 60.00 s | 17.70 s | `faults/hopper_weight_drift_caught_at_the_high_switch.yaml` |
| ✅ PASS | Start Refused While The Hopper Weight Signal Is Failed | 0.20 s | 0.30 s | 0.10 s | `faults/hopper_weight_failure_blocks_start.yaml` |
| ✅ PASS | Hopper Weight Failure Recovery -- Reset Refused Until The Signal Is Restored | 0.30 s | 0.50 s | 0.20 s | `faults/hopper_weight_failure_recovery.yaml` |
| ✅ PASS | Hopper Weight Transmitter Failure Trips A Running Line | 0.30 s | 0.50 s | 0.20 s | `faults/hopper_weight_failure_trips_running.yaml` |
| ✅ PASS | A Noisy Weight Transmitter Near High-High -- No Trip On Noise, A Real Overfill Still Trips | 0.10 s | 0.50 s | 0.40 s | `faults/hopper_weight_noise_near_high_high.yaml` |
| ✅ PASS | Stuck Hopper Weight Transmitter -- The Independent High-High Switch Still Trips | 0.30 s | 0.50 s | 0.20 s | `faults/hopper_weight_stuck_high_high_still_trips.yaml` |
| ✅ PASS | A Motion Switch Too Slow For The Proof Window Fails The Start | 0.20 s | 0.30 s | 0.10 s | `faults/motion_switch_too_slow_fails_to_prove.yaml` |
| ✅ PASS | Start Refused While An Alarm Is Unacknowledged | 0.20 s | 0.30 s | 0.10 s | `faults/unacknowledged_alarm_blocks_start.yaml` |
| ✅ PASS | An Unacknowledged Warning Never Blocks A Start | 0.30 s | 0.50 s | 0.20 s | `faults/unacknowledged_warning_never_blocks_start.yaml` |
| ✅ PASS | A Manual Device Command During An Auto Run Is Refused | 0.20 s | 0.30 s | 0.10 s | `manual/device_command_during_auto_refused.yaml` |
| ✅ PASS | Belt Slip In Manual Trips The Line | 0.30 s | 1.00 s | 0.70 s | `manual/manual_belt_slip_trips.yaml` |
| ✅ PASS | Stopping The Conveyor In Manual Stops The Feeder With It, Without A Trip | 0.30 s | 1.00 s | 0.70 s | `manual/manual_conveyor_stop_takes_the_feeder.yaml` |
| ✅ PASS | E-Stop In Manual -- Everything Off, Reset Returns To Manual With Nothing Running | 0.30 s | 1.00 s | 0.70 s | `manual/manual_estop_reset_returns_to_manual.yaml` |
| ✅ PASS | Manual Feeder Start Refused Without The Conveyor Proven | 0.20 s | 0.30 s | 0.10 s | `manual/manual_feeder_refused_without_conveyor.yaml` |
| ✅ PASS | Hopper High-High In Manual Trips The Line | 0.30 s | 1.00 s | 0.70 s | `manual/manual_high_high_trips.yaml` |
| ✅ PASS | The Hopper High Switch Stops A Manual Feeder Without A Trip | 0.30 s | 1.00 s | 0.70 s | `manual/manual_high_switch_stops_feeder.yaml` |
| ✅ PASS | Manual Operation -- Each Device By Hand, Material Flows, Nothing Spilled | 0.30 s | 1.00 s | 0.70 s | `manual/manual_operation.yaml` |
| ✅ PASS | Manual Outlet Open Refused While The Downstream Isn't Ready | 0.20 s | 0.30 s | 0.10 s | `manual/manual_outlet_refused_without_downstream.yaml` |
| ✅ PASS | Mode Change Refused While The Line Runs | 0.20 s | 0.30 s | 0.10 s | `manual/mode_change_refused_while_running.yaml` |
| ✅ PASS | Start Blocked While E-stop Tripped | 0.20 s | 0.30 s | 0.10 s | `safety/estop_blocks_start.yaml` |
| ✅ PASS | Conveyor Emergency Stop | 0.30 s | 0.50 s | 0.20 s | `safety/estop_from_running.yaml` |
| ✅ PASS | E-stop Reset Does Not Bypass A Standing Fault -- A Jam Still In The Chute Returns The Line To FAULTED | 0.80 s | 1.00 s | 0.20 s | `safety/estop_reset_does_not_bypass_a_standing_fault.yaml` |
| ✅ PASS | Normal Stop Returns To Idle | 2.20 s | 3.00 s | 0.80 s | `shutdown/normal_stop.yaml` |
| ✅ PASS | Start With The Hopper Above The High Switch -- The Line Runs, The Feed Waits | 1.60 s | 2.00 s | 0.40 s | `startup/full_hopper_start_holds_feed.yaml` |
| ✅ PASS | Normal Operation -- Start Sequence, Material Flow, Stop Sequence | 0.20 s | 0.30 s | 0.10 s | `startup/normal_operation.yaml` |
| ✅ PASS | Normal Start Reaches Running | 2.00 s | 3.00 s | 1.00 s | `startup/normal_start.yaml` |

## Response time across 3 passes

| Scenario | Passed | Min | Max | Each pass |
|---|---:|---:|---:|---|
| A Batch -- Load From Two Bins, Hold, Discharge, Clean Out | 3/3 | 1.70 s | 1.80 s | 1.70, 1.70, 1.80 |
| A Discharge That Never Empties The Hopper Times Out | 3/3 | 13.70 s | 13.70 s | 13.70, 13.70, 13.70 |
| A Batch Discharge Waits For The Downstream | 3/3 | 13.70 s | 13.80 s | 13.80, 13.70, 13.80 |
| A Batch Dose That Stops Flowing Trips The Batch | 3/3 | 1.70 s | 1.80 s | 1.70, 1.70, 1.80 |
| A Batch Weighed In Out Of Tolerance Raises A Warning | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| A Hopper Outlet That Won't Open Trips The Discharge | 3/3 | 13.70 s | 13.80 s | 13.70, 13.80, 13.80 |
| A Batch Starts Only With A Recipe That Fits, Into An Empty Hopper | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Stop Aborts A Batch | 3/3 | 1.70 s | 1.80 s | 1.80, 1.70, 1.80 |
| Bin B's Gate Fails To Prove Open | 3/3 | 0.50 s | 0.60 s | 0.50, 0.60, 0.50 |
| A Bin Gate That Won't Close On Stop Trips The Line | 3/3 | 2.20 s | 2.20 s | 2.20, 2.20, 2.20 |
| Running From Bin B -- Only Bin B's Gate Opens | 3/3 | 1.90 s | 1.90 s | 1.90, 1.90, 1.90 |
| Only The Source Bin's Low Switch Refuses A Start | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| A Source Bin Change During A Run Waits For The Next Start | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| The Hopper Buffers Between The Feed And A Ready Downstream | 3/3 | 2.70 s | 2.70 s | 2.70, 2.70, 2.70 |
| A Downstream Stop Closes The Outlet Without Tripping The Line | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Alarm Lifecycle -- Start Refused Until Acknowledged, Even After The Cause Clears | 3/3 | 0.30 s | 0.40 s | 0.30, 0.40, 0.30 |
| Belt Slip During The Stop Purge Trips The Line | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Belt Slip Stops The Feeder And Faults The Line | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Material Bridging In The Bin Is Caught By The Belt Scale | 3/3 | 6.10 s | 6.10 s | 6.10, 6.10, 6.10 |
| Start Refused When Bin Low | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Bin Low While Running Raises A Warning, Not A Trip | 3/3 | 0.20 s | 0.30 s | 0.20, 0.30, 0.30 |
| Conveyor Fails To Prove Running | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| A Conveyor Jam Trips The Line, Diagnosed From The Motor Current | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| A Conveyor Jam Behind A Stuck Motion Switch Is Caught By Overcurrent | 3/3 | 1.10 s | 1.20 s | 1.20, 1.20, 1.10 |
| Conveyor Trip Recovery -- Reset Refused Until The Overload Is Reset | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Conveyor Trip While Running Faults The Line | 3/3 | 0.30 s | 0.40 s | 0.30, 0.30, 0.40 |
| Feeder Fails To Prove Running | 3/3 | 1.60 s | 1.60 s | 1.60, 1.60, 1.60 |
| Feeder Fails To Restart Mid-Run -- Level Control Asks, The Drive Never Runs, The Line Trips | 3/3 | 1.20 s | 1.30 s | 1.30, 1.30, 1.20 |
| Feeder Jam Recovery -- Reset Refused Until The Jam Is Cleared | 3/3 | 0.70 s | 0.80 s | 0.70, 0.80, 0.80 |
| Feeder Jam Is Detected By The Plug Switch And Faults The Line | 3/3 | 0.10 s | 0.10 s | 0.10, 0.10, 0.10 |
| Feeder Trip Recovery -- Reset Refused Until The Drive Is Reset | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Feeder Trip While Running Faults The Line | 3/3 | 0.30 s | 0.40 s | 0.40, 0.30, 0.30 |
| A Gate Stuck Open Blocks The Next Start | 3/3 | 2.20 s | 2.20 s | 2.20, 2.20, 2.20 |
| Gate Fails To Prove Open | 3/3 | 0.50 s | 0.50 s | 0.50, 0.50, 0.50 |
| Start Refused When Hopper High-High | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| High-High Switch Stuck Healthy -- WT-105 Still Trips (1oo2) And The Disagreement Is Alarmed | 3/3 | 0.60 s | 0.70 s | 0.60, 0.70, 0.60 |
| Broken High-High Switch Wire Trips The Line -- Fail-Safe Polarity | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Hopper High-High Faults The Line While Running | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Hopper High Switch Failed -- Feeding Stops And The Disagreement Warns | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| A Drifting Hopper Weight Transmitter Is Caught At The High Switch | 3/3 | 42.20 s | 42.30 s | 42.30, 42.20, 42.20 |
| Start Refused While The Hopper Weight Signal Is Failed | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Hopper Weight Failure Recovery -- Reset Refused Until The Signal Is Restored | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Hopper Weight Transmitter Failure Trips A Running Line | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| A Noisy Weight Transmitter Near High-High -- No Trip On Noise, A Real Overfill Still Trips | 3/3 | 0.10 s | 0.10 s | 0.10, 0.10, 0.10 |
| Stuck Hopper Weight Transmitter -- The Independent High-High Switch Still Trips | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| A Motion Switch Too Slow For The Proof Window Fails The Start | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Start Refused While An Alarm Is Unacknowledged | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| An Unacknowledged Warning Never Blocks A Start | 3/3 | 0.20 s | 0.30 s | 0.20, 0.30, 0.30 |
| A Manual Device Command During An Auto Run Is Refused | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Belt Slip In Manual Trips The Line | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Stopping The Conveyor In Manual Stops The Feeder With It, Without A Trip | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| E-Stop In Manual -- Everything Off, Reset Returns To Manual With Nothing Running | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Manual Feeder Start Refused Without The Conveyor Proven | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Hopper High-High In Manual Trips The Line | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| The Hopper High Switch Stops A Manual Feeder Without A Trip | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Manual Operation -- Each Device By Hand, Material Flows, Nothing Spilled | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| Manual Outlet Open Refused While The Downstream Isn't Ready | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Mode Change Refused While The Line Runs | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Start Blocked While E-stop Tripped | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Conveyor Emergency Stop | 3/3 | 0.30 s | 0.30 s | 0.30, 0.30, 0.30 |
| E-stop Reset Does Not Bypass A Standing Fault -- A Jam Still In The Chute Returns The Line To FAULTED | 3/3 | 0.70 s | 0.80 s | 0.70, 0.80, 0.80 |
| Normal Stop Returns To Idle | 3/3 | 2.20 s | 2.20 s | 2.20, 2.20, 2.20 |
| Start With The Hopper Above The High Switch -- The Line Runs, The Feed Waits | 3/3 | 1.60 s | 1.60 s | 1.60, 1.60, 1.60 |
| Normal Operation -- Start Sequence, Material Flow, Stop Sequence | 3/3 | 0.20 s | 0.20 s | 0.20, 0.20, 0.20 |
| Normal Start Reaches Running | 3/3 | 1.90 s | 2.00 s | 2.00, 1.90, 2.00 |

## Interlock coverage (docs/CONTROL-LAB.md §6.3)

| Status | Interlock | Kind | Scenarios | Note |
|---|---|---|---|---|
| ✅ covered | E-stop healthy | Permissive + trip | E-Stop In Manual -- Everything Off, Reset Returns To Manual With Nothing Running<br>Start Blocked While E-stop Tripped<br>Conveyor Emergency Stop | — |
| ✅ covered | No active latched alarms | Permissive | Alarm Lifecycle -- Start Refused Until Acknowledged, Even After The Cause Clears<br>Start Refused While An Alarm Is Unacknowledged<br>An Unacknowledged Warning Never Blocks A Start | the full latch/acknowledge lifecycle is proven by multi-stage scenarios: refused on the unacknowledged alarm alone once its cause is gone, accepted once acknowledged (alarm_lifecycle_start_refused_until_acknowledged), and a recovered but unacknowledged warning never blocking (unacknowledged_warning_never_blocks_start) |
| ✅ covered | Hopper not high-high | Permissive | Start Refused When Hopper High-High | — |
| ✅ covered | Bin not low | Permissive | Only The Source Bin's Low Switch Refuses A Start<br>Start Refused When Bin Low<br>Bin Low While Running Raises A Warning, Not A Trip | the "warning only while running" half is proven by a scenario reaching the warning, and sustained over 10 s of running at the pytest level -- a declarative scenario passes the moment its expectations first hold, so it can't show the line never trips later; see tests/integration/test_line_controller.py::test_bin_low_while_running_stays_a_warning_for_the_whole_run |
| ✅ covered | Gates proven closed | Permissive | A Gate Stuck Open Blocks The Next Start | — |
| ✅ covered | Conveyor proven running | Permissive + trip for feeder | Belt Slip During The Stop Purge Trips The Line<br>Belt Slip Stops The Feeder And Faults The Line<br>Belt Slip In Manual Trips The Line<br>Stopping The Conveyor In Manual Stops The Feeder With It, Without A Trip<br>Manual Feeder Start Refused Without The Conveyor Proven | the permissive half (feeder cannot run onto a stopped belt) is proven declaratively in Manual mode, the one place an operator can attempt the wrong order (manual_feeder_refused_without_conveyor); in Auto the sequence has no way to attempt it, see tests/integration/test_line_controller.py::test_wrong_order_spillage_is_structurally_unreachable_through_control |
| ✅ covered | Hopper high-high | Trip | High-High Switch Stuck Healthy -- WT-105 Still Trips (1oo2) And The Disagreement Is Alarmed<br>Broken High-High Switch Wire Trips The Line -- Fail-Safe Polarity<br>Hopper High-High Faults The Line While Running<br>A Noisy Weight Transmitter Near High-High -- No Trip On Noise, A Real Overfill Still Trips<br>Stuck Hopper Weight Transmitter -- The Independent High-High Switch Still Trips<br>Hopper High-High In Manual Trips The Line | — |
| ✅ covered | Hopper level instruments agree | Alarm | Hopper High Switch Failed -- Feeding Stops And The Disagreement Warns<br>A Drifting Hopper Weight Transmitter Is Caught At The High Switch | — |
| ✅ covered | Any motor fail-to-start / trip | Trip | Conveyor Fails To Prove Running<br>Conveyor Trip Recovery -- Reset Refused Until The Overload Is Reset<br>Conveyor Trip While Running Faults The Line<br>Feeder Fails To Prove Running<br>Feeder Fails To Restart Mid-Run -- Level Control Asks, The Drive Never Runs, The Line Trips<br>Feeder Trip Recovery -- Reset Refused Until The Drive Is Reset<br>Feeder Trip While Running Faults The Line<br>A Motion Switch Too Slow For The Proof Window Fails The Start | — |
| ✅ covered | Gate travel timeout | Trip | Bin B's Gate Fails To Prove Open<br>A Bin Gate That Won't Close On Stop Trips The Line<br>Gate Fails To Prove Open | — |
| ✅ covered | Feeder jam | Trip | Feeder Jam Recovery -- Reset Refused Until The Jam Is Cleared<br>Feeder Jam Is Detected By The Plug Switch And Faults The Line<br>E-stop Reset Does Not Bypass A Standing Fault -- A Jam Still In The Chute Returns The Line To FAULTED | — |
| ✅ covered | Hopper weight signal healthy | Permissive + trip | Start Refused While The Hopper Weight Signal Is Failed<br>Hopper Weight Failure Recovery -- Reset Refused Until The Signal Is Restored<br>Hopper Weight Transmitter Failure Trips A Running Line | — |
| ✅ covered | Conveyor motor current normal | Trip | A Conveyor Jam Trips The Line, Diagnosed From The Motor Current<br>A Conveyor Jam Behind A Stuck Motion Switch Is Caught By Overcurrent | — |
| ✅ covered | Material flowing on the belt | Alarm | Material Bridging In The Bin Is Caught By The Belt Scale | — |
| ✅ covered | Batch start permissives | Permissive | A Batch Starts Only With A Recipe That Fits, Into An Empty Hopper | — |
| ✅ covered | Batch dose flows | Trip | A Batch Dose That Stops Flowing Trips The Batch | — |
| ✅ covered | Hopper discharges | Trip | A Discharge That Never Empties The Hopper Times Out<br>A Hopper Outlet That Won't Open Trips The Discharge | — |
| ✅ covered | Batch weighed in within tolerance | Alarm | A Batch -- Load From Two Bins, Hold, Discharge, Clean Out<br>A Batch Weighed In Out Of Tolerance Raises A Warning | — |
| ✅ covered | Downstream ready for discharge | Permissive | A Batch Discharge Waits For The Downstream<br>A Downstream Stop Closes The Outlet Without Tripping The Line<br>Manual Outlet Open Refused While The Downstream Isn't Ready | — |

## Operating modes validated (docs/CONTROL-LAB.md §6.1)

| Status | Mode | Scenarios run | Passed | Not observable |
|---|---|---:|---:|---:|
| ✅ validated | Auto | 49 | 49 | 0 |
| ✅ validated | Manual | 8 | 8 | 0 |
| ✅ validated | Batch | 8 | 8 | 0 |

## Event sequences

What each scenario actually did, from its telemetry record. **setup** events come from reaching the scenario's `given` preconditions; **response** events are the system reacting to `when`.

### A Batch -- Load From Two Bins, Hold, Discharge, Clean Out — PASS

`batch/batch_cycle.yaml`

Stages: 1: 1.80 s / 3.00 s · 2: 62.90 s / 90.00 s · 3: 42.20 s / 90.00 s · 4: 5.00 s / 6.00 s · 5: 167.00 s / 200.00 s · 6: 3.30 s / 10.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **recipe A 300 kg** |
| 1.40 | setup | Operator command: **recipe B 200 kg** |
| 1.40 | setup | Operator command: **hold 5 s** |
| 1.40 | setup | Operator command: **select_batch** |
| 2.10 | response | Operator command: **start** |
| 2.20 | response | Line state idle → **loading** |
| 108.90 | response | Line state loading → **processing** |
| 113.90 | response | Line state processing → **discharging** |
| 280.90 | response | Line state discharging → **cleaning** |
| 284.20 | response | Line state cleaning → **idle** |

### A Discharge That Never Empties The Hopper Times Out — PASS

`batch/batch_discharge_timeout.yaml`

Stages: 1: 13.70 s / 30.00 s · 2: 2.90 s / 5.00 s · 3: 599.10 s / 610.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **recipe A 50 kg** |
| 1.40 | setup | Operator command: **hold 2 s** |
| 1.40 | setup | Operator command: **select_batch** |
| 2.10 | response | Operator command: **start** |
| 2.20 | response | Line state idle → **loading** |
| 15.70 | response | Line state loading → **processing** |
| 17.70 | response | Line state processing → **discharging** |
| 617.60 | response | Line state discharging → **faulted** (discharge timeout) |
| 617.70 | response | Alarm **HOP-105.NOT_EMPTYING** active — Batch discharge didn't empty the hopper · **first-out** |

### A Batch Discharge Waits For The Downstream — PASS

`batch/batch_discharge_waits_for_downstream.yaml`

Stages: 1: 13.80 s / 40.00 s · 2: 0.90 s / 3.00 s · 3: 1.40 s / 2.00 s · 4: 19.40 s / 60.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **recipe A 50 kg** |
| 1.40 | setup | Operator command: **hold 1 s** |
| 1.40 | setup | Operator command: **select_batch** |
| 2.10 | response | Operator command: **start** |
| 2.20 | response | Line state idle → **loading** |
| 15.80 | response | Line state loading → **processing** |
| 16.70 | response | Line state processing → **discharging** |
| 34.20 | response | Line state discharging → **cleaning** |
| 37.50 | response | Line state cleaning → **idle** |

### A Batch Dose That Stops Flowing Trips The Batch — PASS

`batch/batch_feed_stalls_on_a_bridged_bin.yaml`

Stages: 1: 1.80 s / 3.00 s · 2: 6.10 s / 10.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **recipe A 300 kg** |
| 1.40 | setup | Operator command: **select_batch** |
| 2.10 | response | Operator command: **start** |
| 2.20 | response | Line state idle → **loading** |
| 9.80 | response | Line state loading → **faulted** (batch feed stalled) |
| 9.80 | response | Warning **FT-104.NO_FLOW** active — No flow on the belt while feeding · **first-out** |

### A Batch Weighed In Out Of Tolerance Raises A Warning — PASS

`batch/batch_out_of_tolerance_warns.yaml`

Stages: 1: 0.20 s / 3.00 s · 2: 3.70 s / 90.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **recipe A 300 kg** |
| 1.40 | setup | Operator command: **hold 5 s** |
| 1.40 | setup | Operator command: **select_batch** |
| 2.10 | response | Operator command: **start** |
| 2.20 | response | Line state idle → **loading** |
| 5.80 | response | Line state loading → **processing** |
| 5.90 | response | Warning **BATCH.TOLERANCE** active — Batch weighed in out of tolerance · **first-out** |

### A Hopper Outlet That Won't Open Trips The Discharge — PASS

`batch/batch_outlet_stuck_trips_the_discharge.yaml`

Stages: 1: 13.80 s / 30.00 s · 2: 4.00 s / 6.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **recipe A 50 kg** |
| 1.40 | setup | Operator command: **hold 2 s** |
| 1.40 | setup | Operator command: **select_batch** |
| 2.10 | response | Operator command: **start** |
| 2.20 | response | Line state idle → **loading** |
| 15.80 | response | Line state loading → **processing** |
| 17.80 | response | Line state processing → **discharging** |
| 19.80 | response | Line state discharging → **faulted** (outlet travel fault) |
| 19.80 | response | Alarm **XV-106.TRAVEL_FAULT** active — Hopper outlet gate travel fault · **first-out** |

### A Batch Starts Only With A Recipe That Fits, Into An Empty Hopper — PASS

`batch/batch_start_permissives.yaml`

Stages: 1: 0.20 s / 0.30 s · 2: 0.10 s / 0.30 s · 3: 0.40 s / 0.30 s · 4: 0.10 s / 0.30 s · 5: 0.30 s / 0.30 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **select_batch** |
| 2.10 | response | Operator command: **start** |
| 2.30 | response | Operator command: **recipe A 1000 kg** |
| 2.30 | response | Operator command: **recipe B 700 kg** |
| 2.40 | response | Operator command: **start** |
| 2.40 | response | command_refused: {'commands': ['start'], 'inhibit': ['RECIPE_EMPTY']} |
| 2.80 | response | Operator command: **recipe A 300 kg** |
| 2.80 | response | Operator command: **recipe B 0 kg** |
| 2.90 | response | Operator command: **start** |
| 2.90 | response | command_refused: {'commands': ['start'], 'inhibit': ['RECIPE_TOO_LARGE']} |

### Stop Aborts A Batch — PASS

`batch/stop_aborts_a_batch.yaml`

Stages: 1: 1.80 s / 3.00 s · 2: 0.20 s / 0.30 s · 3: 2.00 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **recipe A 300 kg** |
| 1.40 | setup | Operator command: **select_batch** |
| 2.10 | response | Operator command: **start** |
| 2.20 | response | Line state idle → **loading** |
| 3.90 | response | Operator command: **stop** |
| 4.00 | response | Line state loading → **stopping** |
| 6.00 | response | Line state stopping → **idle** |

### Bin B's Gate Fails To Prove Open — PASS

`bins/bin_b_gate_fails_to_prove_open.yaml`

Stages: 1: 0.60 s / 1.00 s · 2: 2.00 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **source_bin B** |
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 4.40 | response | Line state starting → **faulted** (gate failed to prove open) |
| 4.40 | response | Alarm **XV-112.TRAVEL_FAULT** active — Bin B gate travel fault · **first-out** |

### A Bin Gate That Won't Close On Stop Trips The Line — PASS

`bins/bin_gate_that_wont_close_trips_the_stop.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **source_bin B** |
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 3.90 | response | Operator command: **stop** |
| 4.00 | response | Line state running → **stopping** |
| 6.00 | response | Line state stopping → **faulted** (gate travel fault) |
| 6.00 | response | Alarm **XV-112.TRAVEL_FAULT** active — Bin B gate travel fault · **first-out** |

### Running From Bin B -- Only Bin B's Gate Opens — PASS

`bins/run_from_bin_b.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **source_bin B** |
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 3.70 | response | Line state starting → **running** |

### Only The Source Bin's Low Switch Refuses A Start — PASS

`bins/source_bin_low_blocks_start.yaml`

Stages: 1: 0.20 s / 0.30 s · 2: 0.30 s / 0.30 s · 3: 0.20 s / 0.30 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **source_bin B** |
| 1.60 | setup | Warning **LSL-111.LOW** active — Bin B low · **first-out** |
| 1.90 | response | Operator command: **start** |
| 2.30 | response | Warning **LSL-101.LOW** active — Bin A low |
| 2.30 | response | Alarm LSL-111.LOW cleared |
| 2.40 | response | Operator command: **start** |
| 2.40 | response | command_refused: {'commands': ['start'], 'inhibit': ['BIN_LOW']} |
| 2.50 | response | Line state idle → **starting** |

### A Source Bin Change During A Run Waits For The Next Start — PASS

`bins/source_change_waits_for_the_next_start.yaml`

Stages: 1: 0.20 s / 0.30 s · 2: 2.20 s / 3.00 s · 3: 2.30 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 3.80 | response | Operator command: **source_bin C** |
| 4.00 | response | Operator command: **stop** |
| 4.10 | response | Line state running → **stopping** |
| 6.10 | response | Line state stopping → **idle** |
| 6.20 | response | Operator command: **start** |
| 6.40 | response | Line state idle → **starting** |
| 8.40 | response | Line state starting → **running** |

### The Hopper Buffers Between The Feed And A Ready Downstream — PASS

`downstream/buffer_feeds_a_ready_downstream.yaml`

Stages: 1: 2.70 s / 4.00 s · 2: 7.00 s / 12.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 3.40 | response | Line state starting → **running** |

### A Downstream Stop Closes The Outlet Without Tripping The Line — PASS

`downstream/downstream_stop_closes_the_outlet.yaml`

Stages: 1: 0.30 s / 0.50 s · 2: 0.30 s / 0.50 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |

### Alarm Lifecycle -- Start Refused Until Acknowledged, Even After The Cause Clears — PASS

`faults/alarm_lifecycle_start_refused_until_acknowledged.yaml`

Stages: 1: 0.40 s / 0.50 s · 2: 0.10 s / 0.50 s · 3: 0.20 s / 0.30 s · 4: 0.20 s / 0.30 s · 5: 0.20 s / 0.30 s

| t (s) | Phase | Event |
|---:|---|---|
| 2.30 | response | Alarm **WT-105.HIGH_HIGH** active — Hopper high-high · **first-out** |
| 2.50 | response | Operator command: **start** |
| 2.60 | response | Alarm WT-105.HIGH_HIGH cleared |
| 2.70 | response | Operator command: **acknowledge** |
| 2.80 | response | Alarm WT-105.HIGH_HIGH acknowledged |
| 2.90 | response | Operator command: **start** |
| 2.90 | response | command_refused: {'commands': ['start'], 'inhibit': ['UNACKNOWLEDGED_ALARM']} |
| 3.00 | response | Line state idle → **starting** |

### Belt Slip During The Stop Purge Trips The Line — PASS

`faults/belt_slip_during_stop_trips.yaml`

Stages: 1: 0.20 s / 0.50 s · 2: 0.30 s / 0.50 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 3.80 | response | Operator command: **stop** |
| 3.90 | response | Line state running → **stopping** |
| 4.20 | response | Line state stopping → **faulted** (conveyor lost confirmation) |
| 4.20 | response | Alarm **ZSS-104.LOST** active — Conveyor motion loss (belt slip) · **first-out** |

### Belt Slip Stops The Feeder And Faults The Line — PASS

`faults/belt_slip_stops_feeder.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.50 | setup | Operator command: **start** |
| 1.60 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 4.10 | response | Line state running → **faulted** (conveyor lost confirmation) |
| 4.10 | response | Alarm **ZSS-104.LOST** active — Conveyor motion loss (belt slip) · **first-out** |

### Material Bridging In The Bin Is Caught By The Belt Scale — PASS

`faults/bin_bridging_caught_by_the_belt_scale.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 9.90 | response | Warning **FT-104.NO_FLOW** active — No flow on the belt while feeding · **first-out** |

### Start Refused When Bin Low — PASS

`faults/bin_low_blocks_start.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.60 | setup | Warning **LSL-101.LOW** active — Bin A low · **first-out** |
| 1.90 | response | Operator command: **start** |

### Bin Low While Running Raises A Warning, Not A Trip — PASS

`faults/bin_low_while_running_warns_only.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.00 | response | Warning **LSL-101.LOW** active — Bin A low · **first-out** |

### Conveyor Fails To Prove Running — PASS

`faults/conveyor_fail_to_start.yaml`

Stages: 1: 0.20 s / 0.50 s · 2: 1.00 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 3.00 | response | Line state starting → **faulted** (conveyor failed to prove running) |
| 3.00 | response | Alarm **M-104.START_PROOF** active — Conveyor failed to prove running · **first-out** |

### A Conveyor Jam Trips The Line, Diagnosed From The Motor Current — PASS

`faults/conveyor_jam_trips_as_a_jam.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.00 | response | Line state running → **faulted** (conveyor jam) |
| 4.00 | response | Alarm **ZSS-104.LOST** active — Conveyor motion loss (belt slip) · **first-out** |

### A Conveyor Jam Behind A Stuck Motion Switch Is Caught By Overcurrent — PASS

`faults/conveyor_jam_with_stuck_motion_switch_caught_by_overcurrent.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.90 | response | Line state running → **faulted** (conveyor jam) |
| 4.90 | response | Alarm **IT-104.HIGH** active — Conveyor motor overcurrent (jam) · **first-out** |

### Conveyor Trip Recovery -- Reset Refused Until The Overload Is Reset — PASS

`faults/conveyor_trip_recovery.yaml`

Stages: 1: 0.30 s / 0.50 s · 2: 0.20 s / 1.00 s · 3: 0.30 s / 1.00 s · 4: 0.40 s / 1.00 s · 5: 2.00 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 4.10 | response | Line state running → **faulted** (conveyor trip) |
| 4.10 | response | Alarm **M-104.OL** active — Conveyor trip (overload) · **first-out** |
| 4.20 | response | Operator command: **acknowledge** |
| 4.20 | response | Operator command: **reset** |
| 4.30 | response | Alarm M-104.OL acknowledged |
| 4.60 | response | Alarm M-104.OL cleared |
| 4.70 | response | Operator command: **reset** |
| 4.70 | response | command_refused: {'commands': ['reset'], 'inhibit': ['CAUSE_STANDING']} |
| 4.80 | response | Line state faulted → **idle** |
| 5.10 | response | Operator command: **start** |
| 5.30 | response | Line state idle → **starting** |
| 7.00 | response | Line state starting → **running** |

### Conveyor Trip While Running Faults The Line — PASS

`faults/conveyor_trip_while_running.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.50 | setup | Operator command: **start** |
| 1.60 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 4.20 | response | Line state running → **faulted** (conveyor trip) |
| 4.20 | response | Alarm **M-104.OL** active — Conveyor trip (overload) · **first-out** |

### Feeder Fails To Prove Running — PASS

`faults/feeder_fail_to_start.yaml`

Stages: 1: 1.60 s / 3.00 s · 2: 1.00 s / 5.00 s · 3: 2.00 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 4.40 | response | Line state starting → **faulted** (feeder failed to prove running) |

### Feeder Fails To Restart Mid-Run -- Level Control Asks, The Drive Never Runs, The Line Trips — PASS

`faults/feeder_fails_to_restart_trips.yaml`

Stages: 1: 1.30 s / 2.00 s · 2: 0.80 s / 1.00 s · 3: 1.90 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.00 | setup | Line state starting → **running** |
| 4.80 | response | Line state running → **faulted** (feeder failed to prove running) |
| 4.80 | response | Alarm **M-103.START_PROOF** active — Feeder failed to prove running · **first-out** |
| 4.90 | response | Operator command: **acknowledge** |
| 4.90 | response | Operator command: **reset** |
| 4.90 | response | Alarm M-103.START_PROOF cleared |
| 5.00 | response | Line state faulted → **idle** |
| 5.00 | response | Alarm M-103.START_PROOF acknowledged |
| 5.70 | response | Operator command: **start** |
| 5.80 | response | Line state idle → **starting** |
| 7.50 | response | Line state starting → **running** |

### Feeder Jam Recovery -- Reset Refused Until The Jam Is Cleared — PASS

`faults/feeder_jam_recovery.yaml`

Stages: 1: 0.80 s / 1.00 s · 2: 0.20 s / 1.00 s · 3: 1.80 s / 3.00 s · 4: 0.30 s / 1.00 s · 5: 0.20 s / 1.00 s · 6: 1.90 s / 3.00 s

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
| 6.80 | response | Alarm LSH-103.JAM cleared |
| 6.90 | response | Operator command: **reset** |
| 6.90 | response | command_refused: {'commands': ['reset'], 'inhibit': ['CAUSE_STANDING']} |
| 7.00 | response | Line state faulted → **idle** |
| 7.10 | response | Operator command: **start** |
| 7.20 | response | Line state idle → **starting** |
| 8.90 | response | Line state starting → **running** |

### Feeder Jam Is Detected By The Plug Switch And Faults The Line — PASS

`faults/feeder_jam_trips_running.yaml`

Stages: 1: 0.10 s / 0.20 s · 2: 0.60 s / 1.00 s · 3: 2.00 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.40 | response | Line state running → **faulted** (feeder jam) |
| 4.40 | response | Alarm **LSH-103.JAM** active — Feeder jam (discharge chute plugged) · **first-out** |

### Feeder Trip Recovery -- Reset Refused Until The Drive Is Reset — PASS

`faults/feeder_trip_recovery.yaml`

Stages: 1: 0.30 s / 0.50 s · 2: 0.20 s / 1.00 s · 3: 1.80 s / 3.00 s · 4: 0.30 s / 1.00 s · 5: 0.30 s / 1.00 s · 6: 1.90 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.00 | response | Line state running → **faulted** (feeder trip) |
| 4.00 | response | Alarm **M-103.FAULT** active — Feeder trip (VFD fault/overload) · **first-out** |
| 4.10 | response | Operator command: **acknowledge** |
| 4.10 | response | Operator command: **reset** |
| 4.20 | response | Alarm M-103.FAULT acknowledged |
| 6.30 | response | Alarm M-103.FAULT cleared |
| 6.40 | response | Operator command: **reset** |
| 6.40 | response | command_refused: {'commands': ['reset'], 'inhibit': ['CAUSE_STANDING']} |
| 6.60 | response | Line state faulted → **idle** |
| 6.70 | response | Operator command: **start** |
| 6.80 | response | Line state idle → **starting** |
| 8.50 | response | Line state starting → **running** |

### Feeder Trip While Running Faults The Line — PASS

`faults/feeder_trip_while_running.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.10 | response | Line state running → **faulted** (feeder trip) |
| 4.10 | response | Alarm **M-103.FAULT** active — Feeder trip (VFD fault/overload) · **first-out** |

### A Gate Stuck Open Blocks The Next Start — PASS

`faults/gate_stuck_open_blocks_start.yaml`

Stages: 1: 2.20 s / 3.00 s · 2: 0.20 s / 1.00 s · 3: 0.20 s / 0.50 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 3.80 | response | Operator command: **stop** |
| 3.90 | response | Line state running → **stopping** |
| 5.90 | response | Line state stopping → **faulted** (gate travel fault) |
| 5.90 | response | Alarm **XV-102.TRAVEL_FAULT** active — Bin A gate travel fault · **first-out** |
| 6.00 | response | Operator command: **acknowledge** |
| 6.00 | response | Operator command: **reset** |
| 6.10 | response | Line state faulted → **idle** |
| 6.10 | response | Alarm XV-102.TRAVEL_FAULT acknowledged |
| 6.20 | response | Operator command: **start** |
| 6.20 | response | Alarm XV-102.TRAVEL_FAULT cleared |

### Gate Fails To Prove Open — PASS

`faults/gate_travel_timeout.yaml`

Stages: 1: 0.50 s / 1.00 s · 2: 2.00 s / 5.00 s · 3: 2.00 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 4.30 | response | Line state starting → **faulted** (gate failed to prove open) |
| 4.30 | response | Alarm **XV-102.TRAVEL_FAULT** active — Bin A gate travel fault · **first-out** |
| 4.40 | response | Alarm XV-102.TRAVEL_FAULT cleared |
| 6.30 | response | Alarm **XV-102.TRAVEL_FAULT** active — Bin A gate travel fault · **first-out** |

### Start Refused When Hopper High-High — PASS

`faults/hopper_high_high_blocks_start.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.70 | setup | Alarm **WT-105.HIGH_HIGH** active — Hopper high-high · **first-out** |
| 2.00 | response | Operator command: **start** |

### High-High Switch Stuck Healthy -- WT-105 Still Trips (1oo2) And The Disagreement Is Alarmed — PASS

`faults/hopper_high_high_switch_stuck_weight_trips.yaml`

Stages: 1: 0.70 s / 1.00 s · 2: 0.50 s / 1.50 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.40 | response | Line state running → **faulted** (hopper high-high) |
| 4.40 | response | Alarm **WT-105.HIGH_HIGH** active — Hopper high-high · **first-out** |
| 4.90 | response | Alarm **LSHH-105.DISAGREE** active — Hopper high-high switch disagrees with WT-105 |

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
| 3.20 | setup | Line state starting → **running** |
| 4.90 | response | Warning **LSH-105.DISAGREE** active — Hopper high switch disagrees with WT-105 · **first-out** |

### A Drifting Hopper Weight Transmitter Is Caught At The High Switch — PASS

`faults/hopper_weight_drift_caught_at_the_high_switch.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 46.00 | response | Warning **LSH-105.DISAGREE** active — Hopper high switch disagrees with WT-105 · **first-out** |

### Start Refused While The Hopper Weight Signal Is Failed — PASS

`faults/hopper_weight_failure_blocks_start.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.60 | setup | Alarm **WT-105.FAIL** active — Hopper weight transmitter failed · **first-out** |
| 1.90 | response | Operator command: **start** |

### Hopper Weight Failure Recovery -- Reset Refused Until The Signal Is Restored — PASS

`faults/hopper_weight_failure_recovery.yaml`

Stages: 1: 0.30 s / 0.50 s · 2: 0.20 s / 1.00 s · 3: 0.40 s / 1.00 s · 4: 0.30 s / 1.00 s · 5: 1.90 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.00 | response | Line state running → **faulted** (hopper weight signal failed) |
| 4.00 | response | Alarm **WT-105.FAIL** active — Hopper weight transmitter failed · **first-out** |
| 4.10 | response | Operator command: **acknowledge** |
| 4.10 | response | Operator command: **reset** |
| 4.20 | response | Alarm WT-105.FAIL acknowledged |
| 4.60 | response | Alarm WT-105.FAIL cleared |
| 4.70 | response | Operator command: **reset** |
| 4.70 | response | command_refused: {'commands': ['reset'], 'inhibit': ['CAUSE_STANDING']} |
| 4.80 | response | Line state faulted → **idle** |
| 5.00 | response | Operator command: **start** |
| 5.10 | response | Line state idle → **starting** |
| 6.80 | response | Line state starting → **running** |

### Hopper Weight Transmitter Failure Trips A Running Line — PASS

`faults/hopper_weight_failure_trips_running.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 4.10 | response | Line state running → **faulted** (hopper weight signal failed) |
| 4.10 | response | Alarm **WT-105.FAIL** active — Hopper weight transmitter failed · **first-out** |

### A Noisy Weight Transmitter Near High-High -- No Trip On Noise, A Real Overfill Still Trips — PASS

`faults/hopper_weight_noise_near_high_high.yaml`

Stages: 1: 0.10 s / 0.50 s · 2: 0.30 s / 1.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 2.90 | setup | Line state starting → **running** |
| 3.80 | response | Line state running → **faulted** (hopper high-high) |
| 3.80 | response | Alarm **WT-105.HIGH_HIGH** active — Hopper high-high · **first-out** |

### Stuck Hopper Weight Transmitter -- The Independent High-High Switch Still Trips — PASS

`faults/hopper_weight_stuck_high_high_still_trips.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.00 | response | Line state running → **faulted** (hopper high-high) |
| 4.00 | response | Alarm **WT-105.HIGH_HIGH** active — Hopper high-high · **first-out** |

### A Motion Switch Too Slow For The Proof Window Fails The Start — PASS

`faults/motion_switch_too_slow_fails_to_prove.yaml`

Stages: 1: 0.20 s / 0.30 s · 2: 1.00 s / 2.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 2.30 | response | Alarm **ZSS-104.LOST** active — Conveyor motion loss (belt slip) · **first-out** |
| 3.00 | response | Line state starting → **faulted** (conveyor failed to prove running) |

### Start Refused While An Alarm Is Unacknowledged — PASS

`faults/unacknowledged_alarm_blocks_start.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.60 | setup | Alarm **WT-105.HIGH_HIGH** active — Hopper high-high · **first-out** |
| 1.90 | response | Operator command: **start** |

### An Unacknowledged Warning Never Blocks A Start — PASS

`faults/unacknowledged_warning_never_blocks_start.yaml`

Stages: 1: 0.30 s / 0.50 s · 2: 0.10 s / 0.50 s · 3: 0.20 s / 0.30 s

| t (s) | Phase | Event |
|---:|---|---|
| 2.10 | response | Warning **LSL-101.LOW** active — Bin A low · **first-out** |
| 2.30 | response | Operator command: **start** |
| 2.40 | response | Line state idle → **starting** |
| 2.40 | response | Alarm LSL-101.LOW cleared |

### A Manual Device Command During An Auto Run Is Refused — PASS

`manual/device_command_during_auto_refused.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.30 | setup | Line state starting → **running** |
| 3.90 | response | Operator command: **start_feeder** |

### Belt Slip In Manual Trips The Line — PASS

`manual/manual_belt_slip_trips.yaml`

Stages: 1: 0.30 s / 1.00 s · 2: 1.20 s / 2.00 s · 3: 0.30 s / 0.50 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **select_manual** |
| 1.50 | setup | Line state idle → **manual** |
| 2.10 | response | Operator command: **start_conveyor** |
| 2.40 | response | Operator command: **open_gate** |
| 2.40 | response | Operator command: **start_feeder** |
| 3.80 | response | Line state manual → **faulted** (conveyor lost confirmation) |
| 3.80 | response | Alarm **ZSS-104.LOST** active — Conveyor motion loss (belt slip) · **first-out** |

### Stopping The Conveyor In Manual Stops The Feeder With It, Without A Trip — PASS

`manual/manual_conveyor_stop_takes_the_feeder.yaml`

Stages: 1: 0.30 s / 1.00 s · 2: 1.20 s / 2.00 s · 3: 0.20 s / 0.20 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **select_manual** |
| 1.50 | setup | Line state idle → **manual** |
| 2.10 | response | Operator command: **start_conveyor** |
| 2.40 | response | Operator command: **open_gate** |
| 2.40 | response | Operator command: **start_feeder** |
| 3.60 | response | Operator command: **stop_conveyor** |

### E-Stop In Manual -- Everything Off, Reset Returns To Manual With Nothing Running — PASS

`manual/manual_estop_reset_returns_to_manual.yaml`

Stages: 1: 0.30 s / 1.00 s · 2: 0.40 s / 0.50 s · 3: 0.20 s / 0.50 s · 4: 0.20 s / 0.50 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **select_manual** |
| 1.50 | setup | Line state idle → **manual** |
| 2.10 | response | Operator command: **start_conveyor** |
| 2.70 | response | Line state manual → **estopped** (e-stop) |
| 2.70 | response | Alarm **ES-001.TRIP** active — E-stop tripped · **first-out** |
| 2.80 | response | Operator command: **acknowledge** |
| 2.90 | response | Alarm ES-001.TRIP acknowledged |
| 3.00 | response | Operator command: **reset** |
| 3.00 | response | Alarm ES-001.TRIP cleared |
| 3.10 | response | Line state estopped → **manual** |

### Manual Feeder Start Refused Without The Conveyor Proven — PASS

`manual/manual_feeder_refused_without_conveyor.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **select_manual** |
| 1.50 | setup | Line state idle → **manual** |
| 2.10 | response | Operator command: **start_feeder** |

### Hopper High-High In Manual Trips The Line — PASS

`manual/manual_high_high_trips.yaml`

Stages: 1: 0.30 s / 1.00 s · 2: 0.30 s / 0.50 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **select_manual** |
| 1.50 | setup | Line state idle → **manual** |
| 2.10 | response | Operator command: **start_conveyor** |
| 2.60 | response | Line state manual → **faulted** (hopper high-high) |
| 2.60 | response | Alarm **WT-105.HIGH_HIGH** active — Hopper high-high · **first-out** |

### The Hopper High Switch Stops A Manual Feeder Without A Trip — PASS

`manual/manual_high_switch_stops_feeder.yaml`

Stages: 1: 0.30 s / 1.00 s · 2: 1.20 s / 2.00 s · 3: 0.30 s / 0.50 s · 4: 0.20 s / 0.30 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **select_manual** |
| 1.50 | setup | Line state idle → **manual** |
| 2.10 | response | Operator command: **start_conveyor** |
| 2.40 | response | Operator command: **open_gate** |
| 2.40 | response | Operator command: **start_feeder** |
| 3.90 | response | Operator command: **start_feeder** |

### Manual Operation -- Each Device By Hand, Material Flows, Nothing Spilled — PASS

`manual/manual_operation.yaml`

Stages: 1: 0.30 s / 1.00 s · 2: 1.10 s / 2.00 s · 3: 0.30 s / 1.00 s · 4: 2.00 s / 4.00 s · 5: 0.20 s / 2.00 s · 6: 0.20 s / 0.30 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **select_manual** |
| 1.50 | setup | Line state idle → **manual** |
| 2.10 | response | Operator command: **start_conveyor** |
| 2.40 | response | Operator command: **open_gate** |
| 3.50 | response | Operator command: **start_feeder** |
| 3.80 | response | Operator command: **stop_feeder** |
| 3.80 | response | Operator command: **close_gate** |
| 5.80 | response | Operator command: **stop_conveyor** |
| 6.00 | response | Operator command: **select_auto** |
| 6.10 | response | Line state manual → **idle** |

### Manual Outlet Open Refused While The Downstream Isn't Ready — PASS

`manual/manual_outlet_refused_without_downstream.yaml`

Stages: 1: 0.20 s / 0.30 s · 2: 0.10 s / 0.50 s · 3: 0.30 s / 0.30 s · 4: 0.40 s / 0.50 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **select_manual** |
| 1.50 | setup | Line state idle → **manual** |
| 2.10 | response | Operator command: **open_outlet** |
| 2.40 | response | Operator command: **open_outlet** |
| 2.40 | response | command_refused: {'commands': ['open_outlet'], 'inhibit': ['DOWNSTREAM_NOT_READY']} |

### Mode Change Refused While The Line Runs — PASS

`manual/mode_change_refused_while_running.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 3.80 | response | Operator command: **select_manual** |

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

### E-stop Reset Does Not Bypass A Standing Fault -- A Jam Still In The Chute Returns The Line To FAULTED — PASS

`safety/estop_reset_does_not_bypass_a_standing_fault.yaml`

Stages: 1: 0.80 s / 1.00 s · 2: 0.30 s / 0.50 s · 3: 0.20 s / 0.50 s · 4: 0.10 s / 0.50 s · 5: 0.30 s / 1.00 s · 6: 0.20 s / 1.00 s · 7: 0.30 s / 1.00 s · 8: 0.20 s / 1.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 4.50 | response | Line state running → **faulted** (feeder jam) |
| 4.50 | response | Alarm **LSH-103.JAM** active — Feeder jam (discharge chute plugged) · **first-out** |
| 4.80 | response | Line state faulted → **estopped** (e-stop) |
| 4.80 | response | Alarm **ES-001.TRIP** active — E-stop tripped |
| 4.90 | response | Operator command: **reset** |
| 5.20 | response | Operator command: **acknowledge** |
| 5.20 | response | Operator command: **reset** |
| 5.20 | response | command_refused: {'commands': ['reset'], 'inhibit': ['ESTOP_ACTIVE']} |
| 5.30 | response | Alarm ES-001.TRIP cleared |
| 5.30 | response | Alarm ES-001.TRIP acknowledged |
| 5.30 | response | Alarm LSH-103.JAM acknowledged |
| 5.40 | response | Line state estopped → **faulted** (feeder jam) |
| 5.50 | response | Operator command: **start** |
| 5.90 | response | Alarm LSH-103.JAM cleared |
| 6.00 | response | Operator command: **reset** |
| 6.00 | response | command_refused: {'commands': ['reset'], 'inhibit': ['LINE_FAULTED']} |
| 6.10 | response | Line state faulted → **idle** |

### Normal Stop Returns To Idle — PASS

`shutdown/normal_stop.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.40 | setup | Operator command: **start** |
| 1.50 | setup | Line state idle → **starting** |
| 3.20 | setup | Line state starting → **running** |
| 3.80 | response | Operator command: **stop** |
| 3.90 | response | Line state running → **stopping** |
| 5.90 | response | Line state stopping → **idle** |

### Start With The Hopper Above The High Switch -- The Line Runs, The Feed Waits — PASS

`startup/full_hopper_start_holds_feed.yaml`

Stages: 1: 1.60 s / 2.00 s · 2: 0.40 s / 1.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 3.40 | response | Line state starting → **running** |

### Normal Operation -- Start Sequence, Material Flow, Stop Sequence — PASS

`startup/normal_operation.yaml`

Stages: 1: 0.20 s / 0.30 s · 2: 1.70 s / 3.00 s · 3: 0.20 s / 0.30 s · 4: 2.00 s / 3.00 s

| t (s) | Phase | Event |
|---:|---|---|
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 3.70 | response | Line state starting → **running** |
| 3.80 | response | Operator command: **stop** |
| 3.90 | response | Line state running → **stopping** |
| 5.90 | response | Line state stopping → **idle** |

### Normal Start Reaches Running — PASS

`startup/normal_start.yaml`

| t (s) | Phase | Event |
|---:|---|---|
| 1.90 | response | Operator command: **start** |
| 2.00 | response | Line state idle → **starting** |
| 3.80 | response | Line state starting → **running** |
