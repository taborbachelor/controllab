# ControlLab — Master Project Context

*Read this first in any session working in this repository. It defines the destination, architectural principles, constraints, and priorities — not the current implementation state. Check `docs/ARCHITECTURE.md` for what actually exists right now, and `docs/CONTROL-LAB.md` for the full product/engineering specification this file summarizes.*

---

## 1. Project Identity

**ControlLab** — Virtual Commissioning & Control System Test Environment.

ControlLab is an open-source virtual commissioning environment for simulating industrial equipment, testing deterministic control logic, injecting realistic faults, and validating automated sequences before physical commissioning.

The project is intended to become a technically credible public engineering project demonstrating software development, industrial automation, simulation, control systems, testing, telemetry, systems architecture, and AI-assisted engineering.

This is **not** an AI wrapper, a generic dashboard, or a toy industrial simulator. The goal is a small but legitimate engineering system that could plausibly be useful to an automation engineer.

## 2. Why This Project Exists

Part of a broader portfolio spanning industrial automation, software development, controls, systems integration, industrial data, simulation, autonomous systems, AI-assisted development, and modern engineering workflows.

The project sits at the intersection of: **software + industrial automation + control systems + simulation + testing + data + AI-assisted engineering.**

Success looks like: someone experienced in industrial automation looks at the repository and thinks *"this is a legitimate engineering tool, not just another AI-generated demo."*

## 3. Business / Professional Context — Boundary

The developer is interested in eventually working in industrial automation, controls, systems integration, and related technical roles. The project was inspired partly by general conversations about modern control architectures and commissioning.

**Hard boundary, no exceptions:**
- No company or person is the customer, and none may be named, credited, or implied as a customer, endorser, or source anywhere in the product, source code, documentation, UI, package names, test scenarios, commit messages, or marketing copy.
- Never use any organization's proprietary information, architecture, internal terminology, unpublished specifications, source code, data, or branding.
- Specific names this rule covers are kept in a local, untracked `CLAUDE.local.md`, never in the repository. Read it if present.

ControlLab is a general-purpose industrial automation project inspired by publicly observable engineering problems, useful to a broad range of automation engineers and developers. Generalize anything that starts to look company-specific.

## 4. Core Product Concept

A virtual industrial plant. The initial plant is a small bulk-material handling system:

```
Material Bin → Feeder → Conveyor → Hopper
```

Full device list, I/O tags, and behavior detail: `docs/CONTROL-LAB.md` §5.

```
                  ┌──────────────────────┐
                  │     TEST RUNNER      │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │   CONTROL SYSTEM     │
                  │ States · Sequences   │
                  │ Interlocks · Modes   │
                  │ Safety Logic         │
                  └──────────┬───────────┘
                             │ Commands / I/O
                             ▼
              ┌─────────────────────────────┐
              │     VIRTUAL INDUSTRIAL      │
              │             PLANT            │
              │ Bin · Feeder · Conveyor      │
              │ Hopper · Motors · Sensors    │
              │ Actuators                    │
              └─────────────┬───────────────┘
                            │ Events / Telemetry
            ┌───────────────┼────────────────┐
            ▼               ▼                ▼
       Dashboard       Test Reports      AI Analysis
```

## 5. Critical Architectural Principle

Strict separation between: **Simulation, Control, Testing, Telemetry, Visualization, Protocol integration, AI assistance.** These layers must not become unnecessarily coupled.

- Simulation represents the physical world.
- Control represents deterministic behavior.
- Testing verifies behavior.
- Telemetry observes behavior.
- The UI visualizes behavior.
- Protocol adapters eventually let external systems interact with the environment.
- AI assists engineers.

**AI must never silently become the deterministic control authority.** No LLM makes safety-critical control decisions directly.

## 6. Engineering Philosophy

**Prioritize:** correctness, deterministic behavior, explicit state, testability, understandable architecture, modularity, reproducibility, observability, maintainability, realistic simulation, useful documentation.

**Avoid:** unnecessary abstraction, enterprise architecture for its own sake, premature microservices, excessive dependencies, generic framework layers, speculative features, giant classes, magic behavior, hidden state, AI-generated complexity that doesn't solve a real problem.

Every architectural layer must earn its existence. Prefer a simple system that works over a sophisticated system that's hard to understand.

## 7. Development Philosophy

Built with AI-assisted development (Claude Code, Codex). AI assistance is a development multiplier, not the project's selling point — the repository has to stand on its own as legitimate engineering. Optimize for useful engineering capability, not code volume.

**When implementing a feature:**
1. Understand the existing architecture.
2. Identify the smallest correct implementation.
3. Implement it.
4. Test it.
5. Verify behavior.
6. Update documentation if necessary.
7. Only then expand it.

Don't implement multiple unrelated features at once unless asked. Don't rewrite working systems unnecessarily. Before adding a dependency, ask whether it's actually needed. Before adding an abstraction, ask whether it solves a real current problem.

## 8. Technology Direction

- **Simulation/control:** Python (3.12+)
- **Testing:** pytest
- **Potential API:** FastAPI (later)
- **Potential frontend:** React + TypeScript (later)
- **Potential storage:** SQLite initially, PostgreSQL later if justified
- **Potential protocols:** MQTT, OPC UA, Modbus, CAN, others as appropriate

Don't implement every technology immediately. The initial system is primarily Python and self-contained; the architecture should leave room for future protocol and UI integration without forcing those components into early phases.

## 9. Control System — Modes (destination)

Eventual operating modes: `AUTOMATIC`, `MANUAL`, `BATCH`, `CONTINUOUS`, `MAINTENANCE`, `FAULT`, `ESTOP`. Early phases don't need all of them — start with the minimum for meaningful behavior. Built: Auto, Manual and Batch plus the line state machine (`docs/CONTROL-LAB.md` §6; Manual completed 2026-09-23, Batch 2026-09-24 — a recipe across the three bins with load, hold, discharge and cleanout — each in-process, over Modbus, on OpenPLC and in the dashboard). Not built: Continuous as its own mode, Maintenance.

Control logic must be deterministic: same inputs + initial conditions → same results, always.

## 10. Testing / Commissioning Philosophy

Tests describe behavior, not implementation. Conceptual shape:

```yaml
name: Conveyor Emergency Stop

given:
    conveyor: running
    hopper: filling
    emergency_stop: false

when:
    emergency_stop: true

expect:
    conveyor: stopped
    feeder: stopped
    fault_state: active

within:
    milliseconds: 500
```

The exact format can evolve — the principle (tests express expected system behavior) doesn't.

## 11. Fault Injection

A major capability, not an afterthought. Faults must be observable, reproducible, and testable. See `docs/CONTROL-LAB.md` §5.4 for the current concrete fault list (motor fail-to-start, motor trip, belt slip, gate failure/stuck limit, feeder jam, sensor failure, E-stop, bin runout).

## 12. Telemetry

Structured events, not just logs — logs and telemetry are not the same thing. Telemetry exists to serve debugging, testing, visualization, reports, and future AI analysis. Deferred out of the earliest phases (see roadmap) until Control and Testing exist to generate something worth recording.

## 13. Visualization

A future UI should resemble an engineering HMI/commissioning environment, not a generic SaaS dashboard. **Do not build the UI before the simulation and control architecture underneath it exists.**

## 14. Commissioning Reports

Eventually: exportable reports (HTML/JSON, PDF later) — tests run, pass/fail, timing vs. limits, alarm sequences, interlock coverage matrix. Don't implement every export format immediately.

## 15. AI Features (destination)

AI is a supporting capability, not the foundation. Potential capabilities: test generation, scenario suggestions, log analysis, failure summarization, commissioning report summaries, natural-language system exploration, fault investigation.

AI-generated tests must still be deterministic, executable test definitions. AI never directly alters safety-critical control behavior — it produces artifacts an engineer inspects and approves.

## 16. Future Protocol Integration

```
REAL CONTROL SYSTEM → PROTOCOL ADAPTER → CONTROLLAB → VIRTUAL PLANT
```

Enables software-in-the-loop and virtual commissioning workflows against externally-supplied control logic. Don't implement protocol support prematurely — but design interfaces (the I/O image, see `docs/ARCHITECTURE.md`) so adapters can be added later without rewriting the simulation engine.

## 17. Target Repository Architecture

The long-term shape (do **not** pre-create empty directories to match this — components get created when they have real content; see `docs/ARCHITECTURE.md` for what actually exists):

```
controllab/
├── .github/                    workflows, issue templates
├── docs/                       CONTROL-LAB.md, ARCHITECTURE.md, SIMULATION.md,
│                                CONTROL-SYSTEM.md, TESTING.md, FAULT-INJECTION.md,
│                                PROTOCOLS.md, AI.md, DEVELOPMENT.md
├── apps/                       dashboard/, simulator-ui/
├── services/
│   ├── simulation/              engine/ equipment/ sensors/ actuators/ physics/ scenarios/
│   ├── control/                 state_machine/ sequences/ interlocks/ modes/ safety/
│   ├── testing/                 runner/ assertions/ scenarios/ reports/
│   └── telemetry/                events/ logging/ metrics/
├── packages/                    core/ models/ protocols/ configuration/ utilities/
├── ai/                           test-generator/ log-analyzer/ prompts/
├── scenarios/                    basic/ startup/ shutdown/ faults/ safety/ continuous/
├── configs/                      equipment/ io/ control/
├── tests/                        unit/ integration/ simulation/ end-to-end/
├── examples/                     basic-conveyor/ bulk-material-line/ commissioning-demo/
├── scripts/                      dev/ simulation/ testing/
├── README.md · CONTRIBUTING.md
├── pyproject.toml · package.json · docker-compose.yml
```

## 18. Phased Development Roadmap

Full detail, current status, and "done when" criteria per phase: `docs/CONTROL-LAB.md` §10.

| Phase | Focus |
|---|---|
| 0 | Foundation — repo, specs, Python env, pytest, conventions, domain model |
| 1 | Simulation core — clock, equipment models, deterministic state transitions |
| 2 | Control — state machines, sequences, interlocks, Auto/Manual, E-stop, fault state |
| 3 | Testing — scenario definitions, runner, assertions, timing constraints, reports |
| 4 | Fault injection — sensor/motor/gate/comms faults, E-stop, recovery behavior |
| 5 | Telemetry — structured events, measurement/state/fault/test history |
| 6 | Visualization — plant view, HMI, live state, alarms, test execution |
| 7 | Protocols — MQTT, OPC UA, Modbus, adapters as justified |
| 8 | AI engineering assistance — test generation, scenario generation, log analysis |
| 9 | Virtual commissioning — external controller integration, I/O mapping, SIL workflows |

## 19. Quality Bar

Every meaningful feature has tests, and tests verify behavior, not code coverage — avoid tests that just mirror implementation details. Important behavior is deterministic. Errors are explicit. State transitions are observable. Faults are reproducible. Simulation scenarios are repeatable. Documentation explains *why* architectural decisions exist, not just what they are.

## 20. GitHub / Public Portfolio Standard

This is intended to be public. The README should eventually carry: a concise description, architecture diagram, screenshots/GIFs, a live demo if practical, quick start, an example scenario, testing information, architecture explanation, roadmap, and key technical decisions.

Don't inflate the project with meaningless statistics. Don't claim industrial deployment or production readiness unless actually achieved. Don't claim compatibility with real industrial systems unless actually tested. Be technically honest — credibility comes from what it actually does.

## 21. Anti-Overengineering Rule

The project must not become an architecture showcase disguised as a simulator. Do not introduce microservices without need, Kubernetes, distributed databases, event buses, message brokers, complex dependency injection, elaborate plugin systems, excessive design patterns, or premature cloud infrastructure — unless a concrete project requirement eventually justifies it.

A well-designed monolith is acceptable. A small amount of excellent code beats a large amount of unnecessary code.

## 22. Development Rules for the AI Agent

Before making substantial changes: inspect the current repository, inspect relevant documentation, understand existing architecture, determine current implementation status. **Don't assume a feature exists because it appears in this document** — this describes the desired system, not necessarily the current one.

When implementing: (1) state what you're going to change, (2) make the smallest reasonable change, (3) run relevant tests, (4) fix failures, (5) review the implementation, (6) update documentation when architecture or behavior changes, (7) report what changed.

If you discover a better architecture than the one described here: **do not silently rewrite it** — explain the issue and propose the change. If a requested feature conflicts with the architecture: stop and explain the conflict before implementing a large workaround. If a feature is unnecessary for the current phase: say so and propose deferring it. If uncertain: don't invent requirements — use existing docs/code as the source of truth and ask when necessary.

## 23. Current Immediate Objective

**If `docs/HANDOFF-design.md` exists, read it before anything else in this section:** it holds the controls work's in-progress state and next steps. (`docs/HANDOFF-frontend.md`, if present and untracked, belongs to a separate frontend design workstream.)

All roadmap phases (0-10) are complete; Phase 10 made the validation workflow the face of the project (run summaries, `controllab test`, regression fixtures, dashboard scenarios, `docs/DEMO.md`). The work now is hardening and finishing, not new phases:

1. Close real engineering findings as they surface (they are recorded in `docs/CONTROL-LAB.md` §10 and the change log), one small tested step at a time.
2. Keep the repository presentable as a public portfolio project: README, docs, and reports current with what actually exists.
3. New scope comes from the *Later* list in `docs/CONTROL-LAB.md` §10, and only on a deliberate decision.

**Standing decision:** no paid model calls. The AI live-model path (`--live`) is built but is not to be run or proposed unless the developer raises it.

## 24. Definition of Success

**First milestone:** a simulated bulk-material system can be started programmatically, equipment transitions through explicit deterministic states, material moves through the system, sensors report meaningful values, faults can be introduced, and automated tests verify expected behavior.

**Eventual success:** an engineer can define or load a virtual industrial system, connect deterministic control logic to it, execute repeatable commissioning scenarios, inject faults, inspect telemetry, generate reports, and optionally use AI to accelerate test creation and system analysis.

## 25. How to Work With This Project

Direction comes at a high level; act as a senior software/controls development partner, not a passive code generator. When useful: identify architectural problems, missing tests, risky assumptions; challenge unnecessary complexity; propose simpler alternatives; point out inconsistencies; explain real tradeoffs.

Don't turn every small task into a lengthy architectural discussion — execute routine work efficiently, reserve explanation for decisions that actually matter. Prioritize forward progress.

## 26. Final Principle

ControlLab should feel like something an engineer could actually use — not "look how much AI-generated code I made," but "here is a working virtual industrial system, its control architecture, its tests, its fault injection, its telemetry, how the behavior was validated, and how real control software could eventually connect to it." Build toward that standard, incrementally, from the current repository state.
