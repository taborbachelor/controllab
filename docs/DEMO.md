# Demonstrating ControlLab

A walkthrough for showing ControlLab to another controls or software
engineer. It takes about ten minutes, fifteen with OpenPLC. Every result
you'll show is produced live, by the same code the test suite runs.

No time to set up? The [recorded demo](https://taborbachelor.github.io/controllab/)
plays four real runs in the browser (feeder jam recovery, a regression
caught, overfill protection with a stuck switch, a normal start/stop) with
the test shown beside the line.

## What you're demonstrating

> ControlLab is a virtual commissioning and controls-validation environment.
> It runs deterministic virtual process equipment against real control
> logic, lets you inject equipment and instrument faults on purpose, and
> automatically verifies safe response and recovery. The same scenarios run
> against the Python controller, over Modbus I/O, and on OpenPLC.

The question to put to the audience: **can we change this control software
without breaking the machine?**

## Before you start

```bash
pip install -e ".[dev]"
python scripts/dashboard.py            # leave it running; open http://127.0.0.1:8000
```

For the OpenPLC part, also do this (once, about two minutes; details in
[`examples/openplc/README.md`](../examples/openplc/README.md)):

```bash
docker run -d --name controllab-openplc -p 127.0.0.1:8080:8080 openplc:v3
python examples/openplc/setup_openplc.py --container controllab-openplc --controllab-host host.docker.internal
```

The dashboard detects OpenPLC when its web UI answers. The *Control runtime*
list then enables it, and *Compare runtimes* includes it. Start the dashboard
**without** `--modbus-port`: the PLC runs use port 5020 themselves.

## 1. Orientation (1 minute)

Point at the three layers of the page:

- **The header** says what it is.
- **The picture** is the plant: bin → gate → feeder → conveyor → hopper,
  with its switches and weigh-scale. Hover anything to see what it is.
- **Scenarios** (on the right) are the tests. **Engineer tools** (collapsed)
  break the plant by hand.

Say: *"The controller only sees I/O: run commands, feedback, switches, a
weight. Exactly what a PLC sees. It never touches the simulation."*

## 2. Normal operation (1 minute)

Under **Scenarios**, leave the runtime on *Python controller*, and on
**Normal operation** click **Run & verify**.

Watch the picture:

1. The conveyor starts first.
2. It proves it's moving (the *moving* lamp).
3. The gate opens, and then the feeder runs.
4. Material flows up into the hopper.
5. On stop: the feeder and gate stop first, the conveyor purges the belt,
   then it stops too.

The result card appears: **PASS, 18/18 checks**, each stage with its
response time against its limit, and invariants held on every tick.

Say: *"That wasn't an animation. The scenario runner operated the line, and
it's the same run `pytest` does. The test suite checks that the event logs
are identical."*

## 3. Feeder jam and recovery (2 minutes)

On **Feeder jam recovery**, click **Run & verify**. Walk through the result
card stage by stage:

1. **The jam trips the line and every output drops.** A jam doesn't fault
   the motor. The drive keeps running while no material comes out, and only
   the discharge-chute plug switch catches it. First-out alarm:
   `LSH-103.JAM`.
2. **Reset is refused while the chute is still plugged.** The reset
   interlock.
3. **Clearing the jam at the feeder clears the alarm.**
4. **Reset is accepted once the cause is gone.**
5. **The line restarts and material flows.**

Each stage shows MATCH for every check and its response time. Click **Watch
this run (replay)** to scrub through the exact run, tick by tick.

## 4. A failed sensor (1 minute)

On **Failed hopper weight transmitter**, click **Run & verify**:

- The transmitter loses its signal. It reads 0 kg, which is indistinguishable
  from an empty hopper, except that its input channel's diagnostic says the
  reading is meaningless.
- The controller trips ("unknown means stop"), refuses a reset until the
  instrument is repaired, then recovers.

Then **Overfill protection: failed level switch**:

- The high-high switch is stuck saying "not full", and the hopper is
  overfilled.
- The line still trips, because the overfill trip votes 1oo2 between the
  switch and the weight.
- A second alarm names the switch that disagreed.

## 5. The same scenario on a real PLC runtime (3 minutes, needs OpenPLC)

On **Feeder jam recovery**, click **Compare runtimes**. The same scenario
file runs three times:

| Runtime | What it is |
|---|---|
| Python controller | in-process, lockstep |
| Python controller over Modbus TCP | a separate process that reaches the plant only over Modbus |
| OpenPLC | an IEC 61131-3 Structured Text port of the controller on OpenPLC, polling the plant as Modbus remote I/O, in real time, from a cold PLC restart |

The comparison table shows each runtime's verdict and checks. It also shows
how each was compared:

- the Modbus run's event log is **identical** to the Python run, event for
  event;
- the PLC run is compared by verdict and checks.

The PLC's stage response times are a scan or two longer: that's the Modbus
poll plus the PLC scan on each hand-off, real latency the lockstep runs
don't have.

Say: *"The test doesn't know or care what the controller is written in.
That's the point: the same commissioning suite validates the Python
reference and the PLC program."*

The recorded full-suite result against OpenPLC is in
[`examples/openplc/COMMISSIONING-REPORT.md`](../examples/openplc/COMMISSIONING-REPORT.md).
From a terminal, run `controllab test --runtime openplc feeder_jam_recovery`.

## 6. A regression gets caught (2 minutes)

Pick **Controller build → Deliberate regression: Reset is accepted while the
discharge chute is still plugged**. On **Feeder jam recovery**, click
**Run & verify**.

The card now reads **REGRESSION CAUGHT / FAIL**:

- Stage 1 passes: the jam still trips the line.
- **Stage 2 fails.** Line state was expected *faulted*, but was actually
  *idle*: the reset was accepted with the chute still plugged.
- *Failure detected at stage 2, t = 3.30 s (the stage's deadline).*
- Later stages are marked *not run*, not passed.

Say: *"Someone 'improved' the reset logic. The build compiles, the line
runs, and on a real machine you'd find out the day someone resets onto a
plugged chute. Here it fails in a second, with the exact stage and the
actual values."*

The same thing from a terminal (the exit status is 1, so a CI pipeline would
stop):

```bash
controllab test feeder_jam_recovery --regression reset-ignores-jam
controllab test --list-regressions
controllab test                          # production build: everything passes
```

Set *Controller build* back to *Correct build* and rerun: PASS.

The regressions are testing fixtures
([`services/testing/regressions.py`](../services/testing/regressions.py)).
Production code is never modified to demonstrate one. The suite proves each
one is caught at the right stage, and that each copied method differs from
production only by its marked change.

## 7. Where AI fits (1 minute)

Say: *"When a run fails, the validator already knows the first divergence:
the stage, the deadline, expected vs actual. The optional AI layer starts
from that, plus a bounded digest of the events and signal changes around
it. It returns hypotheses marked unverified, as a file. It never touches
the controller, and it isn't needed for anything you just saw."*

To show it without an API key:

```bash
python examples/ai_assist/run_flow.py --approve feeder_jam_during_start
```

It runs the whole loop: proposals, the review gate, an engineer's approval,
deterministic execution, and analysis of a failed run. It uses a scripted
stand-in, and every file it writes is labelled as not being model output.
See [`docs/AI.md`](AI.md).

## If something goes wrong

- **OpenPLC shows "not reachable":**
  - check `docker ps`;
  - make sure the web UI answers at http://127.0.0.1:8080;
  - make sure the dashboard wasn't started with `--modbus-port 5020`.
- **Buttons are greyed out:** a verification is running. Manual controls lock
  until its result is in.
- **You want a clean line:** click **New session**.
