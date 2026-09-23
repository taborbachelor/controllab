# ControlLab

Virtual commissioning and control-system test environment for industrial automation.

ControlLab simulates a small industrial plant — material bin → gate →
feeder → conveyor → hopper — so deterministic control logic can be run
against it and tested: startup, shutdown, interlocks, fault injection, and
recovery, before any physical equipment exists.

**Status:** all ten roadmap phases (0-9) complete; 625 tests passing.

What's in it:

- **Simulation core** — a deterministic plant (bin, gate, feeder, conveyor,
  hopper, E-stop) with material transport, conservation, and spillage
  accounting. The same scenario run twice gives identical results.
- **Control** — an I/O image (tag table), device control modules, and the
  full `IDLE/STARTING/RUNNING/STOPPING/FAULTED/ESTOPPED` line state
  machine with start permissives, trips, and a machine-readable reason
  for every refused start. Control only ever touches I/O tags, never the
  simulated equipment (enforced by a test).
- **Commissioning scenarios** — a declarative `given`/`when`/`expect`
  YAML format (multi-stage with `then:`, so a whole recovery procedure is
  one scenario). 25 scenarios cover all 11 interlock rows; the coverage
  matrix (`python scripts/scenario_report.py`) reports 11/11, 0 gaps.
- **Fault injection and alarms** — motor fail-to-start and trips, belt
  slip, stuck gates, E-stop, a feeder jam (the drive keeps running; a
  discharge-chute plug switch catches it), and instrument failure (stuck,
  or failed with an input-channel diagnostic that tells "0 kg" from
  "unknown"). Alarms latch, report first-out, need acknowledging, and a
  reset is refused while its cause remains. The hopper's overfill
  protection is built the way it would be on a real line: fail-safe
  level switches (a broken wire trips), a 1oo2 high-high vote between the
  switch and the weight transmitter (a switch seized in the healthy
  position can't remove the trip), and an alarm when the two disagree.
- **Telemetry and reports** — sampled tag history (CSV), a state/alarm
  event log (JSONL), operator-command capture, and a generated Markdown
  commissioning report: pass/fail, response time against each limit, and
  the interlock coverage matrix. Byte-identical run to run.
- **Visualization** — a self-contained HTML replay of any scenario run
  (line mimic, alarm board, event log, I/O tags, scrubbable tick by tick)
  and a live localhost dashboard with operator controls and a separate
  fault-injection panel.
- **Protocols** — a stdlib Modbus TCP server (tested against the spec's
  own examples and `pymodbus`) serving a documented register map
  ([`docs/MODBUS-MAP.md`](docs/MODBUS-MAP.md)), and an external-controller
  mode with a comm-loss watchdog.
- **Virtual commissioning against a real PLC** — the unchanged scenario
  suite runs against a free-running controller in real time, limits in
  plant time with a stated I/O latency tolerance. OpenPLC in Docker,
  running a Structured Text port of the controller, passes 25/25
  scenarios over 3 passes (75/75 runs):
  [`examples/openplc/COMMISSIONING-REPORT.md`](examples/openplc/COMMISSIONING-REPORT.md).
  A controller that doesn't publish ControlLab's status block is judged on
  field evidence and gets *not observable* rather than a guess; an I/O map
  file serves the plant at the addresses an existing PLC program already
  uses.
- **Optional AI assistance** — scenario generation and failed-run analysis
  behind a deterministic review gate (below).

### Optional AI assistance (Phase 8)

Not needed for anything above. With `pip install -e ".[ai]"` and
`ANTHROPIC_API_KEY` set:

```bash
python scripts/ai_generate.py "cover gate faults during shutdown" --count 3
python scripts/ai_analyze.py path/to/failing_scenario.yaml
```

Generated scenarios are *proposals*: they land in `candidates/` and every
one goes through a deterministic review gate (`scripts/review_candidates.py`)
that rejects broken, duplicate, non-deterministic, and vacuous tests,
including one whose declared trigger the expectations don't depend on. A
candidate becomes a test only when an engineer moves it into `scenarios/`.
Run analysis sends a bounded digest of a failed run, never the full
telemetry, and returns hypotheses marked unverified. The API key is read
from the environment per call and never stored.

The whole loop (request, proposals, gate, approval, deterministic
execution, analysis of a failed run) runs without a key using a labelled
scripted stand-in: `python examples/ai_assist/run_flow.py --approve
feeder_jam_during_start` (add `--live` for Claude). Details: [`docs/AI.md`](docs/AI.md).

The live-model path is built and tested against a faked SDK, but has
deliberately not been run against a real model (a choice not to spend on
API calls for this project). The scripted stand-in exercises every
verdict of the gate and the analysis; how good Claude's own proposals
are is untested.

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
For the interlock coverage matrix and the commissioning report:

```bash
python scripts/scenario_report.py            # print
python scripts/scenario_report.py --out coverage_report.txt
python scripts/scenario_report.py --markdown commissioning_report.md
```

The Markdown commissioning report is deterministic: the same code
produces a byte-identical file every run.

To watch a scenario play back on a line mimic:

```bash
python scripts/replay.py scenarios/safety/estop_from_running.yaml   # writes estop_from_running.replay.html
```

Open the file in any browser. It needs no server and no network.

To run the line live:

```bash
python scripts/dashboard.py        # then open http://127.0.0.1:8000
```

New to it? The page explains itself: a "What's happening" card narrates
the line in plain words, and five guided walkthroughs (a normal start and
stop, a refused start, an emergency stop, a motor fault and its recovery,
overfill protection with a broken sensor) run step by step, each with a
"Do it for me" button.

Start it, inject a fault, and walk through the recovery (clear the
fault, reset the device at the field, acknowledge, reset, start) the
way a commissioning engineer would. The instrument panel makes the
hopper's weight transmitter and level switches stick or fail: stick
LSHH-105, set the hopper to 97 %, and watch WT-105 trip the line on its
own while the cross-check names the switch. Localhost only, no dependencies
beyond the standard library. Add `--modbus-port 5020` to also expose the
line to any Modbus TCP client (a SCADA package, Modbus Poll, a PLC):
sensors and outputs readable, operator commands on HMI coils 100-103.

To run the controller as a separate program that only talks Modbus:

```bash
python scripts/dashboard.py --external        # terminal 1: the plant, no controller
python scripts/external_controller.py         # terminal 2: the controller, over Modbus TCP
```

Press Start on the dashboard; kill the controller mid-run and the
watchdog stops the plant within a second.

To run the whole scenario suite against a free-running controller in
real time, the way you would against a PLC (Phase 9):

```bash
python scripts/scenario_report.py --realtime reference --speed 4       # our controller, free-running
python scripts/scenario_report.py --realtime openplc --repeat 3        # a real PLC runtime, see examples/openplc
```

Limits are still checked in plant time, with a stated I/O latency
tolerance; a result met only inside it is reported as such, and repeat
passes report the response-time spread. For a controller that doesn't
publish ControlLab's status block, `--no-status` reports expectations on
its internal state as *not observable* rather than reading registers
nobody wrote.

To commission a PLC program whose I/O configuration already exists,
describe its addresses in an I/O map file instead of changing the
program: see [`configs/io/`](configs/io/) (`line.yaml` is the built-in
map, `relocated.yaml` the same line at remote-I/O offsets). `--map FILE`
on `scenario_report.py --realtime`, `scripts/register_map.py` (the map
document and PLC master configuration), and
`examples/openplc/setup_openplc.py`. A map without a status block
declares a controller without one. The unchanged OpenPLC program passed
the suite (15 scenarios at the time) against the relocated map with only
its slave-device ranges changed.

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| 0 | Foundation | done |
| 1 | Simulation core | done |
| 2 | Control (states, sequences, interlocks) | done |
| 3 | Testing / commissioning scenarios | done |
| 4 | Fault injection, alarms | done |
| 5 | Telemetry | done |
| 6 | Visualization | done |
| 7 | Protocols (Modbus + external controller mode) | done |
| 8 | AI engineering assistance | done — live-model path built, not exercised (see below) |
| 9 | Virtual commissioning | done |

Full detail: `docs/CONTROL-LAB.md` §10.

## License

MIT — see [`LICENSE`](LICENSE).
