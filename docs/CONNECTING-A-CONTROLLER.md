# Connecting your own controller

ControlLab serves its simulated line as a **Modbus TCP remote-I/O device**.
Your controller (a PLC, a soft PLC, or a program) is the Modbus master: it
reads the line's sensors and writes its outputs, exactly as it would poll a
remote I/O rack. ControlLab moves the material, runs the faults and checks
the result. Nothing is shared between the two except the register map.

This page covers what your controller has to do, the two ways to run it
(watch it in the dashboard, or test it with scenarios), and what the results
mean.

## What your controller needs to do

The whole interface is five contiguous Modbus ranges. The full register list
with scaling is in [`MODBUS-MAP.md`](MODBUS-MAP.md).

| Table | Your controller | Addresses | Contents |
|---|---|---|---|
| Discrete inputs (FC 02) | reads | 0–21 | Every switch: limit switches, motor feedback, level switches, E-stop, the downstream ready signal |
| Input registers (FC 04) | reads | 0–5 | The analog inputs, as scaled integers (bin levels, hopper weight, motor current, belt scale) |
| Holding registers (FC 03) | reads | 100–105 | The operator's requests (`hmi_request`) and setpoints (source bin, recipe, hold time) |
| Coils (FC 15) | writes | 0–5 | The outputs: gate open commands and motor run commands |
| Holding registers (FC 16) | writes | 0–14 | The feeder speed reference, your status block, and `hmi_ack` |

There are three levels of support, and each one adds to the last:

1. **Read the inputs and write the outputs.** This is enough for your
   controller to run the line, and for any expectation about the field: what
   it commands (`conveyor_run_commanded`), and what the equipment does
   (`feeder_flowing`, `belt_empty`, `spilled`). Run with `--no-status`.
2. **Take operator commands.** For a scenario (or the dashboard) to press
   Start, Stop, Reset or Acknowledge on your controller, implement the
   request/acknowledge handshake on `hmi_request` (read) and `hmi_ack`
   (write). It takes four steps and is described under *HMI commands* in
   [`MODBUS-MAP.md`](MODBUS-MAP.md): the request bit rises, you act and set
   the ack bit, the request drops, you drop the ack. The setpoints in
   holding registers 101–105 sit beside the request word.
3. **Publish your status.** Write the status block (line state, fault
   reason, alarm bits, first-out, start inhibit, mode; codes in
   [`MODBUS-MAP.md`](MODBUS-MAP.md) *Controller status codes*) and every
   expectation a scenario can make becomes checkable. Without it, those
   expectations are reported as *not observed*, never as passed or failed:
   ControlLab won't guess at a state your controller doesn't publish.

Your PLC's I/O already at other addresses? An **I/O map file** serves the
plant at yours instead: see [`configs/io/relocated.yaml`](../configs/io/relocated.yaml)
(every range moved to its own offset), and pass it with `--map`.

### Starting from the reference program

[`examples/openplc/controllab_line.st`](../examples/openplc/controllab_line.st)
is ControlLab's whole line controller in IEC 61131-3 Structured Text:
sequences, interlocks, alarms, the handshake and the status block. It is the
quickest way to put this line's behavior on another runtime, or a working
example to compare yours against. It was written for and verified on
OpenPLC v3 (MatIEC). Its I/O is located at OpenPLC's addresses (`%IX100.0`
and on), so another runtime needs its I/O mapping changed. It has not been
tried on any runtime other than OpenPLC.

## Where your controller runs

| Your controller | Plant address | Your controller polls |
|---|---|---|
| On this machine | the default, `127.0.0.1` | `127.0.0.1:5020` |
| In Docker on this machine (a soft PLC) | the default | `host.docker.internal:5020`, resolved to its IP address if your runtime's Modbus client can't take a hostname (OpenPLC's can't) |
| Another machine (a hardware PLC on a bench network) | `--bind` with this machine's address on that network | that address, port 5020 |

**`--bind` exposes unauthenticated Modbus.** Anything that can reach the
port can drive the simulated line, and ControlLab prints a warning when you
use it. Use an isolated bench network, never a plant or office network, and
allow the port through this machine's firewall only for that network.

Your controller's **scan cycle** should be 100 ms or faster. The plant runs
in real time, one tick every 100 ms, and every hand-off (the conveyor proven
running, then the gate open, then the feeder) waits for a poll and a scan on
each side.

## Watch it run: the dashboard

```bash
python scripts/dashboard.py --external             # plant with no built-in controller, Modbus on 127.0.0.1:5020
python scripts/dashboard.py --external --bind 192.168.10.5   # the same, for a PLC on a bench network
```

Open http://127.0.0.1:8000 and start your controller. The picture shows the
line as your controller drives it, and the dashboard's Start, Stop, Reset
and Acknowledge buttons reach your controller through the handshake (level 2
above). If your controller stops writing its outputs for a second, the plant
turns every output off, the fault action real remote I/O is set up with.

## Test it: scenarios

With your controller running and polling the port (don't run the dashboard
at the same time: the test serves the plant on that port itself):

```bash
controllab test --runtime external my_scenarios/                # your scenarios, one result each
controllab test --runtime external normal_start estop_from_running   # scenarios from the suite, by name
python scripts/scenario_report.py --realtime external --markdown report.md   # the whole suite, as a commissioning report
```

Both take `--bind`, `--modbus-port`, `--map` and `--no-status` as above.
[`SCENARIOS.md`](SCENARIOS.md) covers writing your own scenarios.

**Each scenario needs a known starting state.** ControlLab starts every
scenario on a fresh plant, then brings your controller to a clean IDLE the
way an operator would after a power-up: it waits for your controller to write
its outputs, then acknowledges and resets until the controller reports IDLE
with nothing latched (without a status block, until every output has been
off for half a second).

It can't power-cycle your controller, and a reset doesn't clear everything:
a counter, a latched mode or a remembered setpoint would carry over from one
scenario to the next. Give it a command that restarts your controller, and
it runs that before every scenario:

```bash
controllab test --runtime external my_scenarios/ --restart-cmd "restart-plc.bat"
```

The command must exit 0; anything else stops the run, with the command's
output. Without `--restart-cmd`, every result and report states that the
controller was **not** restarted between scenarios.

### Reading the results

- **PASS** met every expectation within its limit. **PASS~** needed the I/O
  latency allowance: 0.5 s added to each limit for the polls and scans a
  real controller adds (`--latency` to change it, in `scenario_report.py`).
- **FAIL** shows each expectation as expected against actual, and the point
  where the run first left the scenario.
- **Run invalid, not a verdict on the logic** means the run can't be
  trusted: your controller stopped writing its outputs, a second client was
  writing the plant too (a PLC left polling the port?), or this machine fell
  behind real time. Run it again with nothing heavy running alongside.
- *controller under test never wrote its outputs after restart* means
  nothing is polling the plant's address and port.

**What a failure means.** The suite's 65 scenarios specify how *this* line
must behave: a downstream-first start, trips that cascade upstream, a reset
refused while a cause stands. A controller written to a different design
will fail some of them. That is the tool working: each failure is a place
where your logic and this specification disagree, stated precisely enough
to decide which one is right. To test your own design, write scenarios for
it.

## Proven so far

The same scenarios run unchanged against ControlLab's Python controller in
process, the same controller over Modbus, and OpenPLC running
`controllab_line.st` in real time
([`examples/openplc`](../examples/openplc/README.md)). The external runtime
on this page is tested in the suite against a free-running controller that
ControlLab does not start or restart. No other PLC runtime or hardware PLC
has been run against it yet.
