# ControlLab — Session Handoff (2026-09-25 → 26)

*For a fresh session with no memory of the conversation that produced it.
Read this after `CLAUDE.md` (and the local, untracked `CLAUDE.local.md` if
present), before touching anything. `docs/CONTROL-LAB.md` §10 and its change
log remain the permanent record; this file is the working state and the
reasoning that isn't obvious from them. When the steps in §6 below are
done, fold anything still useful into those docs and delete this file.*

---

## 0. Read order for a cold start

1. `CLAUDE.md` — project identity, architecture rules, dev rules for the agent.
2. `CLAUDE.local.md` (untracked, local only) — the private-name rule. Every
   commit must pass its name check (a case-insensitive `git grep` for the
   name must return nothing). **Gate the commit on it**:
   `if git grep -i -q <name>; then echo STOP; else git commit ...; fi`.
   A plain `git grep ...; git commit` does not stop anything (this session
   committed once past a match — see §3).
3. This file.
4. `docs/CONTROL-LAB.md` §10, the three sections added this session:
   *"The hopper as a buffer: a downstream consumer and discharge enablement"*,
   *"Hardening: the logic review's three open minors"*, and the unchecked
   *"Wrap-up: the three-pass OpenPLC commissioning report"* item under
   *"Completing the master specification"*. Plus the change-log rows dated
   2026-09-25.
5. `docs/ARCHITECTURE.md` — the "Module responsibilities (hardening: the
   logic review's minors)" section (it also holds the downstream entries).

---

## 1. Current state

### Numbers (as of commit `a9e96be`, pushed, CI green, demo site deployed)

| | |
|---|---|
| Scenarios | **65** (`scenarios/`: batch, bins, downstream *(new)*, faults, manual, safety, shutdown, startup) |
| §6.3 interlock rows | **19** (all covered) |
| Automated tests | **947** = 941 that run anywhere + 6 in `tests/integration/test_mqtt_broker.py` that need a live broker (`CONTROLLAB_MQTT_BROKER`) |
| I/O tags | **35** (`DS-107.READY` is the newest) |
| Public demo tabs | **6** (feeder jam, bad change, overfill, normal, batch, manual) |
| OpenPLC | Program compiles (MatIEC) with everything below; see "verified where" |

### What was built this session (oldest first; all pushed to `main`)

| Commit | What |
|---|---|
| `cbbccbb` | Logic-review minor 1: a start with the hopper above LSH-105 holds the feed (the gate step asks level control first); `HopperHysteresis.rearm()` at every Start. Scenario `startup/full_hopper_start_holds_feed.yaml`. |
| `831f479` | Minor 2: STOPPING trips on belt-motion loss once the belt has proven moving during the stop, and on a conveyor that never proves after a Stop mid-startup. Scenario `faults/belt_slip_during_stop_trips.yaml`. |
| `17b9949` | Minor 3: new start permissive **Gates proven closed** (every bin gate + outlet at `ZSC`), `StartInhibit.GATE_NOT_CLOSED = 8192`, read field `gates_closed`, scenario `faults/gate_stuck_open_blocks_start.yaml`; six places that pressed Start while a gate was still closing now wait. |
| `89da167` | Phone layout: the line picture keeps 660 px and scrolls sideways under 700 px; a shown test is ordered directly under the picture under 1000 px (dashboard and every replay). `.wide-only`/`.narrow-only` spans for left/right wording. |
| `5f6f67c` | Public demo: `batch.html` + `manual.html` tabs; single-row sideways-scrolling tab bar on phones; replay intro says "injects any fault". |
| `6d4bbbf` | CI flake fix: real-time tests rerun (≤ 2×) **only** a run the runner invalidated for host lag. |
| `b80d3d0` | README: three screenshots retaken on the three-bin line; §3 plant description corrected (three bins, outlet, 34→now 35 tags). |
| `fa6c937` | Re-encoded `dashboard-overview.jpg` (quality 87) because its bytes matched the name check (see §3). |
| `425f2b2` | Reports: **Batch** row in "Operating modes validated" (Batch scenarios had been counted as Auto); `report_export.py` uses `report.scenario_mode()`; `run_suite_realtime` keeps only each run's last tag sample (bounded memory). |
| `dec7c82` | Downstream step 1: `DS-107` consumer model + fail-safe DI `DS-107.READY` (Modbus DI 21, `%IX102.5`), stimulus `downstream_stopped`, read fields `downstream_ready`, `discharging`. |
| `a9e96be` | Downstream step 2: the outlet `XV-106` as an interlocked discharge-enablement device in Auto/Manual/Batch; `StartInhibit.DOWNSTREAM_NOT_READY = 16384`; §6.3 row 19 *Downstream ready for discharge*; ST port; dashboard picture/button/narration; 4 scenarios; `tests/integration/test_downstream.py`; test rig consumer 10 → 3 kg/s and the consequences. |

### Verified where

| Path | Coverage |
|---|---|
| Python in-process (lockstep) | All 65 scenarios, full pytest suite: pass. |
| Python over Modbus (lockstep) | All 65 (the suite runs every scenario across Modbus too): pass. |
| Free-running reference controller, real time 4× over Modbus | **61/61** scenarios passed (`scenario_report.py --realtime reference --speed 4`), run **before** the downstream work (commits `dec7c82`, `a9e96be`). Not re-run since. |
| OpenPLC (real PLC runtime, real time 1×) | **Only the scenarios changed this session**, single pass: the 6 from the logic-review fixes (`full_hopper_start`, `belt_slip_during_stop`, `gate_stuck_open`, `conveyor_trip_recovery`, `feeder_fails_to_restart`, `hopper_weight_failure_recovery`) and the 5 from the downstream work (the 4 new + `hopper_weight_drift`). All passed first time. **The full suite has not been run on OpenPLC since 2026-09-24 (58/58 then, one pass).** |
| Mosquitto broker tests | 6/6 pass locally against `eclipse-mosquitto:2` in Docker. |
| Browser | Dashboard + replays checked at desktop width and 390 px; downstream picture/button/narration checked; no console errors. |

### Half-done

1. **The three-pass OpenPLC commissioning report** — never completed.
   2026-09-24: killed by the host at 160/174 runs (the runner held every
   run's full tag history; fixed in `425f2b2`). 2026-09-25: started again
   from a Claude Code background shell and **killed by Claude Code's own
   low-memory reaper before its first result** (system at ~2 GB free of
   15.6 GB; Chrome, Edge, Slack and others held the memory, not this
   process). Not restarted, per that tool's instruction.
2. **`examples/openplc/COMMISSIONING-REPORT.md` and the README's OpenPLC
   lines are stale**: they still say **38/38 scenarios, 114/114 runs, Auto
   and Manual mode, 11/11 interlock rows**. The README spots: the "What's
   verified" bullet (≈ line 41–44) and §6 "Result on OpenPLC" (≈ line 213).
3. **`docs/images/dashboard-parity.jpg`** still shows the one-bin line. It
   is the dashboard's *Compare runtimes* table (Python / Modbus / OpenPLC),
   so it needs OpenPLC up.
4. `docs/CONTROL-LAB.md` line 3 (the status line under the title) is stale:
   it says "Last updated: 2026-09-23", "51 declarative commissioning
   scenarios covering all 13 of §6.3's rows", "38/38 … 114/114". Refresh it
   when the report lands.
5. `docs/CONTROL-LAB.md` §10: the item *"☐ Wrap-up: the three-pass OpenPLC
   commissioning report"* is still unchecked.

---

## 2. Key decisions and why

All of these were Tabor's calls, made on explicit options with a stated
recommendation (the project's working style: scope real decisions with
tradeoffs, let Tabor choose, never pick silently).

### Logic-review minors (2026-09-25)

- **Full hopper at Start → start, hold the feed** (not "refuse Start"). The
  line can legitimately run a full buffer down; refusing would be odd.
  Level control is re-armed at every Start because the hysteresis kept a
  stale "no feed" from the previous run, which held a new run's feed in the
  60–80 % dead band.
- **Belt slip during the stop purge → trip** (not "pause the purge timer"):
  pausing would leave the line in STOPPING forever with the motor running
  if the belt never recovers. The trip is `_motion_loss_reason()` (slip vs
  jam by current), same as RUNNING, and only once the belt has proven
  moving during the stop (`_stop_belt_proven`, set on entry to STOPPING
  and latched each scan), so a Stop pressed mid-startup isn't a false trip;
  that case trips on the start-proof fault instead.
- **Gate not proven closed → a start permissive** (not "latched travel
  fault blocks start"): the permissive also catches a gate stuck open
  without a timed-out fault, and a non-source gate open would feed from
  two bins. **Consequence accepted:** after a trip the gates need their
  travel time (1 s rig, 2 s real) to close, so every procedure must wait
  for `gates_closed` before Start. That is the operator procedure being
  corrected, not a limit loosened.

### Narrow screens and the demo

- The phone problem was two things: 4 px labels in the 900-unit SVG, and
  the test 1,300 px below the picture. Fix is CSS only in the shared
  `hmi.css`, so the dashboard, every replay and the public demo all get it.
- Demo tabs: **Batch and Manual both** (Tabor). The Manual tab is
  `manual/manual_operation.yaml` as it stands; it does **not** include the
  refused feeder start (that's `manual_feeder_refused_without_conveyor`).
  Merging them was not done: it would rewrite a scenario already verified
  on OpenPLC.

### The downstream consumer (Tabor's design, 2026-09-25)

The gap: since Batch mode (master spec item 7) the hopper drew only through
the outlet, and **Auto never opened it**, so an Auto run filled to 80 % and
stopped; the 60 % restart never happened. Tabor's directive, verbatim in
substance:

- **Do not** make Auto simply open the outlet at 80 %.
- The hopper is a **buffer** between an upstream source and a **downstream
  consumer**; add a **minimal** consumer model.
- The outlet is an **interlocked discharge-enablement device**.
- Use the existing **60 %/80 % thresholds as hysteresis** for the
  upstream/downstream coordination (that is: the feed's existing
  hysteresis tops the buffer up behind the draw; the outlet never opens on
  a level).
- **Batch stays an explicit fill → discharge sequence.**

Three follow-up calls (all the recommended option):

| Question | Decision | Why |
|---|---|---|
| When is discharge enabled in Auto? | **Only while RUNNING** | Keeps "IDLE means every output off" and the stop sequence unchanged. |
| Downstream stops with the outlet open | **Close the outlet in the same scan, no alarm** | A hand-off between processes, not a fault. An outlet that won't close still trips (existing travel fault). |
| Batch DISCHARGING waiting for the downstream | **Pause the discharge timeout** while not ready | So "discharge timeout" still means "the hopper won't empty", never "the downstream isn't taking". |

Implementation facts a new session needs:

- `DS-107` (`services/simulation/equipment/downstream.py`) is only a
  `stopped` flag and a `ready` property. Its rate **is**
  `PlantConfig.hopper_draw_rate_kg_s`. `Plant.step()` discharges the hopper
  only when the outlet is fully open, not plugged, and the consumer is
  ready; it records `Plant.discharge_flow_kg_s`.
- `DS-107.READY` is **fail-safe** (1 = ready), published through
  `Instruments` like other inputs, so a stuck/failed signal behaves like a
  real one.
- `LineController._enable_discharge(wanted)` is the one place the outlet
  opens in Auto/Batch; Manual's open pushbutton checks
  `Interlocks.downstream_ready` and the every-scan rule closes it.
- **Test rig consumer rate changed 10 → 3 kg/s** (`services/testing/rig.py`).
  At 10 kg/s it outran the 5 kg/s feed: the buffer could never fill, no
  60/80 cycle, and the dashboard walkthrough waited forever. 3 kg/s is the
  plant default's ratio. The live dashboard **must** use the same rig as
  the suite (its *Run & verify* is tested to match the suite event for
  event), so a separate dashboard config was not an option.
  Consequences, each stated in its file: rig `discharge_timeout_s` 240 →
  600 s (largest recipe 1,600 kg ÷ 3 kg/s = 533 s) and `LIM_DISCHARGE`
  2400 → 6000 scans in the ST port (drift-tested);
  `batch/batch_cycle.yaml` "Empty: cleanout…" stage 90 → 200 s;
  `batch/batch_discharge_timeout.yaml` timeout stage 250 → 610 s;
  `tests/integration/test_batch_mode.py::run_batch` cap 600 → 1,200 s.

### Tooling decisions

- `run_suite_realtime` keeps only the **last** tag sample per run (the
  report needs only the final plant time; events stay whole). This was the
  real cause of the 2026-09-24 out-of-memory kill.
- Real-time tests retry **only** "behind real time" invalidations
  (`run_rt()` in `tests/integration/test_realtime.py`).
- No Pillow dependency: screenshots are converted to JPEG with PowerShell
  `System.Drawing` (quality 88; 87 was used once, see §3).

---

## 3. Tried and rejected (don't redo these)

- **Fix A's first scenario draft passed against the old controller.** A
  scenario passes the moment its expectations first hold, and the old
  controller's brief feeder run ended inside the limit. `belt_empty: true`
  (plus `within: 2.0`) is the check only the fix can meet. **Always
  sabotage-check new scenarios** (see §4).
- **Adding `gate_open_commanded: false` to stage 1 of
  `gate_stuck_open_blocks_start`** made the scenario field-observable, and
  then it *failed* on field evidence (a travel-fault trip looks exactly
  like a normal stop in the field for 2 s), which
  `tests/unit/test_observability.py` forbids. Left controller-only on
  purpose.
- **Relaxing the gates-closed permissive** to allow a gate that's still
  travelling: rejected; a stuck gate is indistinguishable from a travelling
  one until its timeout. The procedures wait instead.
- **Opening the outlet at 80 % in Auto**: rejected by Tabor (§2).
- **"Discharge whenever healthy"**, **a `DS-107.NOT_READY` warning alarm**,
  **"keep counting the batch timeout"**: the rejected options of §2's table.
- **Modeling "outlet open into a stopped downstream" as spillage**: rejected.
  The controller sees `DS-107.READY` drop one scan after it happens, and the
  gate leaves "fully open" a tick later, so every normal downstream stop
  would spill 10–20 kg in lockstep and break the no-spill invariants. The
  chute backs up instead (no flow), and the interlock is proven through the
  commanded output (`outlet_open_commanded`).
- **Keeping the rig's 10 kg/s draw and marking every Auto test
  `downstream_stopped`**: rejected (dashboard can't show buffering; the
  live rig must equal the suite rig).
- **A sticky line picture on phones**: rejected (≈ 400 px of an 844 px
  screen); reordering the test under the picture instead.
- **Starting Docker Desktop from Claude Code** (`Start-Process …`): blocked
  by the permission classifier. Tabor starts Docker.
- **`rm -f "$VAR"/*.yaml`**: blocked by a built-in safety check. Copy into a
  fresh directory instead of deleting.
- **Running the 2-hour OpenPLC report as a Claude Code background shell on
  a memory-tight machine**: reaped by Claude Code (not a bug in the run).
  Either free memory first or run it in a normal terminal (§6).
- **A test's `plant.conveyor.belt_slip = True`**: not a real hook (Python
  just set a new attribute). Belt slip is
  `plant.conveyor.motion_switch_stuck_false = True`, as the vocabulary does.
- **The name check matched random bytes inside a JPEG** (`b80d3d0`,
  `dashboard-overview.jpg`); no text matched. Fixed by re-encoding at
  quality 87 (`fa6c937`). The earlier commit still contains those bytes;
  no history rewrite (Tabor has declined history rewrites before).

---

## 4. Conventions and patterns

### The step workflow (every change)

1. Inspect the code first. For a real design decision, present options
   with a recommendation and let Tabor choose (AskUserQuestion works well).
2. Smallest change; Python **and** the Structured Text port
   (`examples/openplc/controllab_line.st`) together, scan for scan.
3. Full suite before and after: `py -m pytest -q -p no:cacheprovider`
   (~70 s; `-x` for a fast first failure) and `controllab test`.
4. New scenario → **sabotage check**: `git stash push -q
   services/control/line_controller.py`, run the scenario (must FAIL),
   `git stash pop -q`, confirm the diff is back. Same for new pytests.
5. New scenario → **review gate** on a copy outside `scenarios/`:
   `py scripts/review_candidates.py <dir>` must say READY FOR REVIEW. Use
   a fresh directory (no `rm`). The "duplicate" warning on a copy of a file
   already in `scenarios/` is expected.
6. Docs in the same commit: `docs/CONTROL-LAB.md` (§5/§6 text if behavior
   changed, a §10 entry, a change-log row at the bottom), `docs/ARCHITECTURE.md`
   module responsibilities, README counts (scenarios / interlocks / tests;
   they appear on ≈ lines 37, 48, 173, 341).
7. Gated name check, commit (`Co-Authored-By: Claude Opus 5.5
   <noreply@anthropic.com>` trailer), **push**, then `gh run list` until
   *Tests* and *Demo site* are green. Standing rule: commit and push each
   finished step before starting the next, without asking.

### Scenario authoring rules

- `given` = preconditions (settled two scans before `when`); `when` = the
  stimulus; declare `trigger:`; multi-stage via `then:`; each stage's
  actions apply the tick after the previous stage's expectations hold.
- A stage that claims something is **refused** must expect something only
  the command's evaluation produces (e.g. `start_inhibit`, or
  `any_unacknowledged_trip: false` with a reset).
- **A command must not race a field change**: release the E-stop, *then*
  reset; wait for `gates_closed: true`, *then* Start.
- Field-vacuity rule (`tests/unit/test_observability.py`): judged on field
  evidence alone, a scenario must either pass (and fail without its `when`)
  or be *not observable* (some stage asserts only controller state).
- Never widen a limit to fit a measurement. When a limit changes because a
  requirement or rig parameter changed, say so in a YAML comment.
- State preconditions honestly: tests about level protection set
  `downstream_stopped: true` so the hopper holds (§2).
- Interlock tag names must match a `docs/CONTROL-LAB.md` §6.3 row **verbatim**,
  and `services/testing/report.py` `INTERLOCKS` must list the rows **in the
  same order** as the doc.

### Append-only contracts (never move or reuse)

- `StartInhibit` bits (`services/control/line_state.py`): newest are
  `GATE_NOT_CLOSED = 8192`, `DOWNSTREAM_NOT_READY = 16384`. ST uses
  `16#2000`, `16#4000`.
- Modbus addresses (`services/protocols/line_map.py`, `configs/io/line.yaml`,
  `configs/io/relocated.yaml`): newest DI is 21 `DS-107.READY` (relocated
  1021). After any map change: `py scripts/register_map.py --out
  docs/MODBUS-MAP.md`, and update the pinned range sizes in
  `tests/unit/test_map_file.py` and `tests/unit/test_register_map.py`
  (DI range is now `(0, 22)` / `(1000, 22)`).
- Fault-reason codes, alarm bits, line-state codes: append only; drift
  tests tie the ST program to Python.

### Adding a vocabulary field or stimulus touches

`services/testing/vocabulary.py` (APPLY_ACTIONS / READ_FIELDS),
`services/testing/verdict.py` (plain label; `_FAULTS`/`_PROCESS`
classification; `describe_action` text for true/false), `services/ai/context.py`
(`VALUE_SHAPES`), `services/visualization/live.py` (stimulus kinds and the
snapshot's `injected` dict), and for a dashboard toggle the `FAULTS` list in
`services/visualization/live_template.html`. Drift tests catch omissions.

### UI rules ("readable cold")

Plain names first, tag numbers secondary; never fail silently (every
refusal has words in `narrate.py`'s `_REFUSALS`, tested); expert tools
collapsed; check new UI in a real browser. Left/right wording uses
`<span class="wide-only">…</span><span class="narrow-only">…</span>`.

### Machine/tooling notes (Windows dev machine)

- Use `py`, not `python3`. Bash is Git Bash; PowerShell 5.1 is available.
- **Bash heredocs containing apostrophes break the Bash tool.** Write
  multi-line edit scripts to a scratch file with the Write tool, then run
  them with `py`. Edit scripts should preserve each file's line endings
  (most tracked files are CRLF in the working copy).
- Browser checks at phone width: the Chrome window is maximized, so
  `resize_window` has no effect; write a same-origin wrapper page with a
  `<iframe style="width:390px">` and inspect `iframe.contentDocument`.
- Screenshots: a 1300 px-wide same-origin iframe, scrub the replay
  (`#scrub` range + `input` event; pause via `#play`), hover the mouse off
  the frame, `zoom` capture with `save_to_disk` at scale 1 (the capture
  frame is scaled ≈ 0.8 from CSS px), convert PNG→JPEG with PowerShell
  `System.Drawing` (quality 88), then run the name check on the binary.
- Docker: `openplc:v3` image exists locally. Containers from this session
  (may still be running): `controllab-openplc` (configured with the
  current program and DI range 22) and `controllab-mosquitto`.
  - OpenPLC: `docker run -d --name controllab-openplc -p
    127.0.0.1:8080:8080 openplc:v3`, then `py examples/openplc/setup_openplc.py
    --container controllab-openplc --controllab-host host.docker.internal`
    (upload, MatIEC compile, slave device, start). This session recreated
    the container rather than re-running setup on a configured one, in case
    setup adds a second slave device (not verified either way).
  - Mosquitto (Git Bash needs `MSYS_NO_PATHCONV=1`):
    `MSYS_NO_PATHCONV=1 docker run -d --name controllab-mosquitto -p
    127.0.0.1:1883:1883 eclipse-mosquitto:2 mosquitto -c /mosquitto-no-auth.conf`;
    tests: `CONTROLLAB_MQTT_BROKER=127.0.0.1:1883
    CONTROLLAB_MQTT_CONTAINER=controllab-mosquitto py -m pytest
    tests/integration/test_mqtt_broker.py`.
- Real-time runs serve the plant on port 5020 themselves: never start the
  dashboard with `--modbus-port 5020` alongside, and run nothing
  CPU-heavy (plant lag > 0.1 s invalidates a run).
- Quick PLC check of a few scenarios: `controllab test --runtime openplc
  <name fragments…>`.

---

## 5. Open questions and known issues

1. **OpenPLC three-pass report not run** (§1 half-done). Expect it to be
   long: 65 scenarios × 3 at 1×, with `batch/batch_discharge_timeout.yaml`
   now ~10 min per run and `batch_cycle` ~5–6 min per run. Estimate
   2–2.5 h.
2. The full suite has not run on OpenPLC since the downstream change
   altered Auto (the outlet now opens in RUNNING). Everything changed was
   spot-checked on the PLC and passed, but untouched scenarios whose Auto
   runs now discharge have only been run in Python/Modbus/reference.
3. `tests/integration/test_downstream.py::test_a_downstream_stop_is_not_an_alarm_and_the_buffer_fills_to_the_switch`
   also passes against the old controller (which never opened the outlet);
   the closing itself is proven by `downstream/downstream_stop_closes_the_outlet.yaml`.
4. The live dashboard fills its buffer slowly at 1× (net 2 kg/s → ~800 s to
   80 %). Speed control exists (up to 10×); no change made.
5. The demo's `batch.html` was ~1.1 MB when the rig drew 10 kg/s; the batch
   run is now longer, so the page is larger. Not measured since. Consider
   whether it matters for phone visitors.
6. Standing (from earlier sessions, unchanged): **no paid model calls** —
   the AI `--live` path is built but not exercised; don't run or propose it.
   Still undecided: whether to keep Anthropic's server-side refusal fallback
   (`fallbacks="default"`) in `services/ai/provider.py`.
7. Not built (the *Later* list in `docs/CONTROL-LAB.md` §10): a Continuous
   mode of its own, Maintenance with audited bypass, a plant definition
   file, PI feed control, ISA-88 phases.

---

## 6. Exact next steps

1. **Memory and containers.** Confirm free memory is comfortable (the last
   attempt was reaped at ~2 GB free; closing browsers helps) and that
   Docker is running with `controllab-openplc` up (`docker ps`; if absent,
   recreate and run `setup_openplc.py` as in §4).
2. **Run the three-pass report** (≈ 2–2.5 h, nothing heavy alongside, no
   dashboard on 5020). Prefer a normal terminal, or a Claude Code
   background shell only when memory is ample:
   ```
   py scripts/scenario_report.py --realtime openplc --repeat 3 --markdown examples/openplc/COMMISSIONING-REPORT.md
   ```
   Watch its console for `FAIL`, `PASS~` (met only inside the latency
   tolerance) and "run invalid". Do not widen any limit to make it pass: a
   failure is a finding, recorded in §10.
3. **Record the result.** Check the report says 65/65, 19/19 rows, and
   Auto/Manual/Batch validated; then update the README's "What's verified"
   OpenPLC bullet and §6 "Result on OpenPLC" line, `docs/CONTROL-LAB.md`
   line 3 (status), tick the §10 wrap-up item, add a change-log row.
4. **Retake `docs/images/dashboard-parity.jpg`**: `py scripts/dashboard.py`
   (no `--modbus-port`), OpenPLC up, *Scenarios → Feeder jam recovery →
   Compare runtimes*, capture per §4's screenshot method, JPEG, name check.
   Update its README alt text if the numbers differ (it currently reads
   "PASS 12/12 on each").
5. **Commit, push, verify CI and the demo site**, then delete this handoff
   file (or trim it to what's still open) in the same or a follow-up
   commit, and stop the containers if no longer needed.

---

## 7. Files most relevant to resume

| Area | Files |
|---|---|
| Controller | `services/control/line_controller.py` (`_scan_idle`, `_begin_start_sequence`, `_scan_starting`, `_scan_running`, `_begin_stop_sequence`/`_scan_stopping`/`_stopping_trip_reason`, `_gates_not_closed`, `_enable_discharge`, `_scan_manual`, `_scan_discharging`, `_scan_cleaning`), `services/control/interlocks.py` (`downstream_ready`), `services/control/line_state.py` (`StartInhibit`), `services/control/hopper_hysteresis.py` (`rearm`) |
| PLC port | `examples/openplc/controllab_line.st`, `examples/openplc/setup_openplc.py`, `examples/openplc/COMMISSIONING-REPORT.md` (stale), `examples/openplc/README.md` |
| Plant | `services/simulation/equipment/plant.py`, `services/simulation/equipment/downstream.py`, `services/simulation/engine/plant_io.py` |
| Rig and runner | `services/testing/rig.py` (rates, timeouts), `services/testing/runner.py` (`_line_running`), `services/testing/realtime.py` (`run_suite_realtime`), `services/testing/report.py` (`INTERLOCKS`, `scenario_mode`), `services/testing/report_export.py`, `services/testing/vocabulary.py`, `services/testing/verdict.py`, `services/ai/context.py` |
| Protocols | `services/protocols/line_map.py`, `configs/io/line.yaml`, `configs/io/relocated.yaml`, `docs/MODBUS-MAP.md` (generated) |
| UI | `services/visualization/hmi.css`, `hmi.js`, `mimic.svg.html`, `live_template.html`, `replay_template.html`, `narrate.py`, `walkthroughs.py`, `live.py`; `scripts/build_site.py` |
| Scenarios added | `startup/full_hopper_start_holds_feed.yaml`, `faults/belt_slip_during_stop_trips.yaml`, `faults/gate_stuck_open_blocks_start.yaml`, `downstream/buffer_feeds_a_ready_downstream.yaml`, `downstream/downstream_stop_closes_the_outlet.yaml`, `manual/manual_outlet_refused_without_downstream.yaml`, `batch/batch_discharge_waits_for_downstream.yaml` |
| Tests added | `tests/integration/test_downstream.py`; additions in `test_line_controller.py`, `test_plant.py`, `test_narrate.py`, `test_hopper_hysteresis.py`, `test_realtime.py` |
| Docs | `docs/CONTROL-LAB.md` (§5.1–5.4, §6.1–6.3, §10, change log), `docs/ARCHITECTURE.md`, `README.md`, `docs/DEMO.md`, `CLAUDE.md` |
