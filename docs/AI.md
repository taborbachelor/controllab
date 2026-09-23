# ControlLab — AI Engineering Assistance

*Phase 8 (docs/CONTROL-LAB.md §10). How the optional AI layer is built,
what it may and may not do, and how to use it.*

## What it is, and what it is not

AI in ControlLab is **engineering assistance, not control logic.** It
proposes commissioning scenarios and suggests explanations for failed
runs. Both are files an engineer reads. It never issues a command to the
controller or the plant, never changes controller logic, never edits or
accepts a scenario, and is never part of the control loop. The
deterministic controller, the plant, the scenario runner, Modbus, the
PLC integration and the dashboard neither import nor need it; an
import-line test (`tests/unit/test_ai_provider.py`) keeps every core
package free of `services.ai` and the SDK, and a subprocess test runs a
scenario with the SDK blocked.

## The flow

```
Engineer ── request ──► AI proposal engine (services/ai/generate.py)
                              │  structured JSON only, keys from the vocabulary
                              ▼
                        Schema validation (validate_candidate, in code)
                              │  malformed → rejected with a note, never written
                              ▼
                        Review gate (services/testing/candidates.py)
                              │  REJECTED / NEEDS JUDGMENT / READY FOR REVIEW
                              ▼
                        Engineer approval   ← the only way a candidate is executed
                              │             or moved into scenarios/
                              ▼
                        Deterministic runner (services/testing/runner.py)
                              │  virtual plant, or a real PLC over Modbus
                              ▼
                        Result + telemetry (events, tag history, failed stage,
                              │  expected vs actual, first divergence)
                              ▼
                        AI run analysis (services/ai/analyze.py)
                              │  bounded digest in; validated, unverified hypotheses out
                              ▼
                        Engineer
```

There is no path around the gate: `generate_candidates()` runs it on
every candidate in the same call and writes its report beside them; it
refuses to write inside `scenarios/` and never moves a file there.

## Provider abstraction

`services/ai/provider.py` defines one interface, `Provider`:

```python
complete_json(*, system: str, user: str, schema: dict, max_tokens: int) -> Completion
```

Generation and analysis are both built on that one call, so a new
provider is one class plus a `PROVIDERS` entry (`get_provider(name)`).
`AnthropicProvider` is the first: the official SDK, the Messages API
with structured JSON output, default model `claude-opus-5`, server-side
refusal fallback on. A refusal, a truncated answer (`max_tokens` is
always passed and hitting it is an error), or invalid JSON raises
`ProviderError`; nothing partial is ever used.

## Scenario generation

`python scripts/ai_generate.py "cover gate faults during shutdown" --count 3`

- **Context** (`services/ai/context.py`): a bounded, deterministic
  description built from the live sources, never hand-copied: the I/O
  tags, the vocabulary with each key's value shape, the §6.3 interlock
  rows, line states, fault reasons, alarms, start-inhibit reasons, the
  rig's timing, three example scenarios, and the names of existing
  scenarios. Over `MAX_CONTEXT_CHARS` is an error, not a truncation.
- **Output schema**: every `given`/`when`/`expect` entry is a
  `{key, value}` pair whose key is an enum of the real vocabulary, and
  each candidate must declare its **`trigger`**, the `when` key(s) that
  are the stimulus under test.
- **Validation in code** (`validate_candidate`): shape, vocabulary,
  a non-empty expectation, a trigger that is part of `when`, a sane time
  limit. A malformed candidate is rejected with a note and never
  written or reviewed.
- **The review gate** then loads the file, checks the vocabulary
  (every stage), the reachable `given`, the §6.3 row, duplicates, runs it
  twice against the built-in controller (determinism) and once across
  Modbus (agreement), and checks it is **not vacuous**: it must fail with
  its whole `when` removed, and — with a declared trigger — fail with
  exactly the trigger removed. The second check is the one a generated
  scenario needs most: a model can put the requested action in `when`
  while the expectations hold without it (e.g. an E-stop in the same
  `when` stops the motors anyway); that candidate is REJECTED.
- **Verdicts**: REJECTED (any error), NEEDS JUDGMENT (clean, but fails
  against the controller: a wrong test or a real finding, which only an
  engineer can decide), READY FOR REVIEW.
- **Approval**: an engineer reads a READY candidate and moves it into
  `scenarios/`. From then on it is an ordinary deterministic test.

Generated candidates are single-stage (`given`/`when`/`expect`/`within`);
multi-stage `then:` scenarios are written by engineers.

## Run analysis

`python scripts/ai_analyze.py path/to/failing_scenario.yaml [--external]`

Only a failed run is analyzed, and the run is produced by the
deterministic runner first; a passing run is refused before any call.
The model gets a **bounded digest**, never the telemetry history:

- the scenario (every stage and its trigger) and the outcome, with the
  **structured failure** from the runner: the failing stage, each
  expectation still unmet as expected vs actual, and the **first
  divergence** — the earliest point the run is *known* to depart from
  the scenario (a deadline passing or an invariant tripping), with the
  caveat that the cause may lie earlier;
- the events nearest the failure (≤ `MAX_ANALYSIS_EVENTS`), the discrete
  tag transitions in a window before it (≤ `MAX_TAG_CHANGES`), each
  analog tag summarized as start/end/min/max;
- all under `MAX_ANALYSIS_INPUT_CHARS`, oldest dropped first, with every
  omission counted inside the digest.

The answer must contain a summary, the **first observed divergence** in
the evidence, one or more hypotheses (each with a kind — including
"scenario expectation", so *the test is wrong* is a first-class answer —
a confidence, supporting and contradicting evidence, and a check to
confirm or rule it out), **recommended investigation** steps, and an
**overall confidence with its uncertainty**. It is validated in code
(`validate_analysis`); a malformed answer is rejected and no file is
written. The renderer labels the result *hypotheses for an engineer to
verify — not conclusions*, stamps every hypothesis *unverified*, flags a
hypothesis whose wording claims certainty, and prints the runner's
deterministic divergence separately from the model's reading of the
evidence. The only side effect is one Markdown file.

## Limits

All in `services/ai/limits.py`, enforced in code before or after the
call — none relies on the model obeying an instruction: at most 5
scenarios per request (extras dropped with a note), a 2,000-character
request, 8,000 / 6,000 output tokens for generation / analysis, a
16,000-character analysis digest with capped events and tag changes, a
24,000-character generation context. Every AI call is an explicit
command; nothing in the test suite or in normal operation makes a
network call.

## Setup

AI is an optional extra:

```bash
pip install -e ".[ai]"          # the anthropic SDK; nothing else needs it
export ANTHROPIC_API_KEY=...    # PowerShell: $env:ANTHROPIC_API_KEY = "..."
```

Never put the key in a file inside the repository (`.env` is git-ignored if you keep one; ControlLab doesn't load it — export it into the shell). The key is read from the environment at call time, passed to a client
that lives for one call, and never stored, logged, or returned. Without
the SDK or the key, AI commands fail with a clear message and everything
else works exactly as before.

## A complete example

`examples/ai_assist/run_flow.py` runs the whole loop:

```bash
python examples/ai_assist/run_flow.py --approve feeder_jam_during_start   # no key, no network
python examples/ai_assist/run_flow.py --live --approve <candidate>        # Claude
```

By default it uses a **scripted stand-in** (`scripted_provider.py`) that
returns hand-written canned answers — not model output, and labelled so
in every file it writes — so the flow runs anywhere: three proposals come
back; the gate marks one READY, rejects one whose trigger doesn't matter,
and sends one to NEEDS JUDGMENT; the engineer approves the READY one by
name and it runs deterministically; the NEEDS JUDGMENT one's failed run
goes to analysis, which suggests the scenario's expectation is probably
what's wrong and says how to check. `tests/integration/test_ai_flow_example.py`
runs it in the suite. `--live` swaps in the Anthropic provider and
nothing else.
