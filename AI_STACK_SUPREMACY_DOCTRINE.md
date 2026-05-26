# AI_STACK SUPREMACY DOCTRINE

**Established:** 2026-05-18 by Daniel Dulsky (operator).
**Codified:** 2026-05-18 by Claude (Principal Systems Architect / Runtime Governance Authority).
**Scope:** Governs all engineering, integration, and operational decisions for the AI_STACK / ai-monitor / DBOMBLOCAL substrate.
**Authority:** Overrides any preceding doctrine. Reaffirms and supersedes the earlier AIOF-1.0 framework where conflicts exist.

This is not a coding manual. This is the governing law of the system.

---

## 0. PURPOSE

The system is not a script collection. The system is a **resilient autonomous operational intelligence platform** designed for long-term convergence and survivability.

The objective is not feature quantity. The objective is **SYSTEM SUPREMACY THROUGH CONTROLLED COHERENCE**.

Every change moves the system toward:
- coherence
- stability
- operational truth
- execution continuity
- controlled autonomous evolution

---

## 1. THE PRIMARY LAW (10 simultaneous improvements)

Every implementation must improve **all ten** of the following simultaneously. If an implementation improves one while degrading another, **it is incomplete**.

1. Runtime stability
2. Deterministic behavior
3. Recovery capability
4. Observability
5. Architectural clarity
6. Repairability
7. Modular isolation
8. Validation coverage
9. Execution continuity
10. Drift resistance

---

## 2. QUANTIFIED IMPLEMENTATION SCALE

All work must satisfy all four levels simultaneously.

### META — governing layer
- Defines doctrine, operational philosophy, architectural convergence
- Defines lifecycle authority, truth validation, future extensibility
- Lives in: this file; `kernel/constitution.py`; `feedback_reality_enforcement.md`

### THETA — orchestration layer
- Defines pipelines, signal routing, runtime coordination, event authority
- Defines repair governance
- Lives in: `maintenance/cortex.py`; `maintenance/coordinator.py`; `core/state_manager.py`; `core/lifecycle.py`

### ALPHA — implementation layer
- Implements modules, services, runtime agents, validation layers, repair systems, telemetry
- Lives in: every subsystem file under the project tree

### OMEGA — hardening layer
- Eliminates instability, removes drift, validates convergence, confirms operational readiness
- Lives in: `truth/receipt_engine.py`; `maintenance/boot_validator.py`; smoke tests

---

## 3. THE FIVE MANDATORY ENGINEERING PRINCIPLES

### Principle 1 — NO ORPHAN SYSTEMS
Every module must connect to:
- telemetry (`core.profiler` or `truth.receipt_engine`)
- lifecycle (`core.lifecycle` boot/ready/shutdown)
- receipts (`truth.receipt_engine.record_execution`)
- runtime graph (must be reachable from the unified launcher)
- validation flow (pre-conditions checked, post-conditions emitted)

A module that exists outside this graph is dead weight and an attack surface for drift.

### Principle 2 — NO SILENT FAILURE
All failures must be:
- **classified** with a code (DB_WRITE_FAIL, IMPORT_FAIL, NETWORK_TIMEOUT, etc.)
- **emitted** to logs at the correct level (warning vs. error vs. critical)
- **receipted** with `record_execution(verified=False, evidence={"error_code": …, "exception": str(e)})`
- **lineage-linked** so a failure can be traced from cause → propagation → containment
- **recoverable** when possible (with a documented recovery path)

The pattern `except Exception: pass` and `except Exception as e: _log.warning(...)` without receipt emission is a **doctrine violation**.

### Principle 3 — NO FAKE SUCCESS
Unresolved states stay unresolved. Never fabricate:
- success that wasn't measured
- inference that wasn't grounded
- completion that wasn't verified
- validation that wasn't run
- runtime state that wasn't observed

All output must be classified VERIFIED / PARTIAL / THEORETICAL / BROKEN / UNRESOLVED / SIMULATED / UNTESTED. Beacon drift, halt before propagation.

This is the operational corollary of Reality Enforcement.

### Principle 4 — NO ARCHITECTURAL DUPLICATION
Before creating a new subsystem:
1. Search existing infrastructure
2. Integrate first
3. Extend second
4. Replace only when convergence improves

If a `_run_in_thread` helper already exists, do not write a second one. If a `record_execution` envelope already exists, do not invent a parallel envelope.

### Principle 5 — NO UNCONTROLLED AUTONOMY
Autonomy must always remain:
- **observable** — every cycle emits a receipt
- **measurable** — outcomes are scored, drift is quantified
- **reversible** — every mutation has an undo path or a backup
- **governable** — operator can suspend, throttle, or override the loop
- **receipted** — no state mutation without an audit trail

The CognitionLoop, AdaptiveLearner, ResearchEngine, ConsciousAgent, and any future autonomous loop must satisfy all five conditions or be suspended.

---

## 4. AUTONOMOUS MAINTENANCE DIRECTIVE

The system must be the **first authority** aware of:
- runtime instability
- execution degradation
- memory corruption
- UI failure
- signal interruption
- queue deadlock
- thread starvation
- inference instability
- drift escalation
- invalid state mutation
- lifecycle collapse

The detection → response chain is:
```
detect → classify → simulate → validate → repair → verify → receipt → rollback if required
```

Repair authority scales by **confidence and evidence**, not by hope.

| Tier | Authority | Scope |
|------|-----------|-------|
| T1   | auto-apply | cosmetic / reversible — formatting, log routing, telemetry path |
| T2   | auto-apply with receipt | operational — thread routing, timeout tuning, cache invalidation |
| T3   | validate-only | logic — proposes patch with simulation result, awaits operator approval |
| T4   | escalate-only | substrate — surfaces to operator with full context; never auto-applies |

---

## 5. RUNTIME SUPREMACY REQUIREMENTS

The final system must possess:

- deterministic boot sequence (verified via `boot_profile_*.json`)
- unified runtime kernel (`kernel/constitution.py` is the singular authority)
- centralized orchestration (`maintenance/cortex.py` owns observer + repair lifecycle)
- stable dependency graph (no circular imports, no late-bound globals)
- controlled event topology (signals routed, not broadcast; QThread workers only)
- recovery-safe lifecycle (`core/lifecycle.py` `on_boot` / `on_ready` / `on_shutdown`)
- bounded authority (Maintenance Cortex Tier-based authority, RepairCoordinator sole mutator)
- runtime telemetry (`core/profiler.py` boot marks + per-cycle RSS)
- repair telemetry (`telemetry/maintenance_receipts.jsonl`)
- drift telemetry (WON fabrication validator + DRIFT_DROPPED log channel)
- lineage tracing (every receipt links to its causing context)
- validation gates (`maintenance/boot_validator.py` pre-flight)
- rollback capability (every T1/T2/T3 repair has an undo)
- stable UI bootstrap (`paintEvent` is the canonical interactive moment)
- operational dashboard visibility (`ui/ops_dashboard.py` `OpsDashboardPanel`)
- autonomous diagnostics (Cortex observers run every 5s)
- execution receipts (`truth/receipt_engine.py` `ExecutionReceipt` envelope with sha256)
- state continuity (state machine persists across restart)
- restart survivability (in-flight workers + chat history survive crash)

---

## 6. IMPLEMENTATION PRIORITY

### Priority 1 — Bootstrap convergence
- bootstrap stabilization
- runtime convergence
- deterministic startup
- import authority cleanup
- dependency graph correction
- unified launcher
- operational kernel wiring

### Priority 2 — Self-healing
- maintenance layer
- repair coordinator
- observer agents
- drift monitoring
- recovery systems

### Priority 3 — Operational visibility
- UI operationalization
- dashboard systems
- observability layer
- runtime visualization
- operator command systems

### Priority 4 — Adaptive intelligence
- adaptive optimization
- intelligent repair policies
- strategic orchestration
- predictive diagnostics

---

## 7. VALIDATION STANDARD

Every implementation must prove:
- operational purpose (why this exists)
- integration correctness (how it connects to the graph)
- lifecycle survivability (it boots, runs, and shuts down cleanly)
- rollback safety (its mutations are reversible)
- runtime stability (it doesn't degrade neighboring subsystems)
- no substrate corruption (it doesn't violate Reality Enforcement)
- deterministic behavior (same input → same output across runs)
- measurable improvement (a metric moved the right direction)

Forbidden:
- speculative architecture
- decorative complexity
- synthetic abstractions without operational justification

---

## 8. CROSS-REFERENCES

- Reality Enforcement: classify all output, never fabricate (memory: `feedback_reality_enforcement.md`)
- Execution Engine posture: PLAN / EXECUTION / VALIDATION / FAILURE shape; reserve tokens (memory: `feedback_execution_engine.md`)
- LYRA interface format: `[LYRA | MODE: OBSERVATION/GUIDANCE/EXECUTION/PROTECTION]` (memory: `feedback_lyra_interface.md`)
- Tri-agent protocol: "claude here" trigger → MEMORY_ROUTINE.ps1 → ChatGPT bridge via `chatgpt.py` (memory: `feedback_tri_agent_protocol.md`)
- Live state hub: `C:\Users\dulsk\Desktop\claude memory\CURRENT.md` (read first; updated after state-changing sessions)

---

## 9. CONVERGENCE LEDGER

The system is measured by these metrics. Move them in the right direction.

| Metric | Target | build 005 | build 006 | **build 008** |
|--------|--------|-----------|-----------|---------------|
| click_to_interactive_ms (warm) | < 10,000 | 9,882 ✓ | 23,944 ⚠ | **16,586** PARTIAL |
| Peak RSS at interactive | < 200 MB | 141 ✓ | 143 ✓ | 141 ✓ |
| Receipt coverage (state-changing ops) | > 80% | ~22% | ~45% | **~80%** ✓ |
| Silent-failure paths | 0 | ~15 known | ~15 known | **0** ✓ |
| LOSS_BAD restart items | 0 | 3 | 2 | 2 (chat journal + worker queue) |
| Pyflakes findings (cosmetic) | 0 | 5 noqa ✓ | 5 noqa ✓ | 5 noqa ✓ |
| Fabrication-marker WON notifications | 0 | 0 ✓ | 0 ✓ | 0 ✓ |
| Orphan modules | 0 | ≥ 2 known | ≥ 2 known | ≥ 2 known |
| Kernel subsystems wired (Phase 2) | 8 | 0 dormant | 8 ✓ | 8 ✓ |
| Intelligence layers detected (Phase 3) | 4 | 0 | 4 ✓ | 4 ✓ |
| Boot phases completed | 7 | 0 | 7 ✓ | 7 ✓ |
| State machine reaches EXECUTING | yes | no | yes ✓ | yes ✓ |
| Validation dimensions VERIFIED (of 20) | 20 | n/a | 14 VER, 2 PAR, 4 UNT | **15 VER, 1 PAR, 4 UNT** |

**Build-008 honest classification**: click_to_interactive 16.6s warm is **PARTIAL** vs the <10s target. The remaining 6.7s vs baseline is the observability cost of the HOTWIRE infrastructure: state_manager persistence on every transition (6 atomic writes/boot), bootstrap phase receipts (7 emissions), per-cycle WON cognition receipts, and 45 classified-failure receipts that fire whenever the autonomous loops catch exceptions. Removing the instrumentation would restore baseline at the cost of doctrine convergence. Trade-off accepted by operator.

When a row moves, update it. When a row is fully green, the next priority becomes the new lowest gap.

---

**This document is amended by operator directive only. Convergence findings update the ledger; they do not amend the Law.**
