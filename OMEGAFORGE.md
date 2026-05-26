# ⟡ OMEGAFORGE

### Reality-Locked Autonomous Execution Kernel — TASKMASTER Ω / DBOMBCENTRAL / AI_STACK

> *Nothing is complete because it was described. Nothing is operational because it compiled.*
> *Success exists only when execution + artifact + hash + ledger + trace + runtime all agree.*
> *Everything else is entropy.*

OMEGAFORGE is the cognitive operating environment for AI_STACK: a **deterministic, supervised, reality-first execution kernel** that turns human intent into *verified* output. It is not a chatbot and not a simulation — it is a forge that only stamps an artifact as real when the filesystem, the hash, the ledger, and the runtime all confirm it.

---

## Doctrine (non-negotiable)

- **Reality supersedes narrative.** A subsystem is `VERIFIED` only with real execution + on-disk artifact + hash match + execution lineage + ledger reconciliation + telemetry confirmation. Otherwise it is reported honestly as `PARTIAL / UNRESOLVED / FAILED / BLOCKED / DEFERRED`. Uncertainty is never collapsed into success.
- **Supervised autonomy, not artificial consciousness.** The system diagnoses itself, detects drift/anomalies/entropy, and *proposes* patches — but **never self-mutates**. All evolution flows: `PROPOSE → VERIFY → REBUILD → TEST → PROMOTE`.
- **Trace everything.** Every operation is thread-linked (`trace_id` / `execution_id` / `intent_id`), file-origin-stamped, colorized, and persisted. No anonymous failure; no orphan logs.

## Architecture (two complementary layers over the verified engine)

| Package | Role |
|---|---|
| `kernel/` | Deterministic **planning / intent compilation** (pre-existing). |
| `omega/` | Deterministic **execution / orchestration / verification** (TASKMASTER Ω). |
| `engine/` | Verified execution primitives — workers, validator, MemPalace ledger, tool fabric. |
| `service/` | FastAPI transport layer (hosted in-process by the packaged runtime). |
| `backends/` | Real backends: ffmpeg, Godot (verified PRESENT). |

**Authority chain:** `USER → kernel.intent_compiler → omega.orchestrator → engine workers → artifact_validator → truth ledger → telemetry traces → rooms`.

Only `omega` may collapse `PARTIAL → RESOLVED`, and only after: **file exists · hash verified · backend READY · ledger execution_id exists.**

### `omega/` modules
- `contracts` — dual-layer truth (`RESOLVED/PARTIAL/UNRESOLVED/FAILED/BLOCKED` → `PRESENT/LIMITED/DEFERRED`), independent sha256, no-optimism aggregation.
- `dag` — cycle-detected DAG compiler (never invents realms).
- `orchestrator` — `INTENT → PLAN → DAG → ROUTE → EXECUTE → zero-trust re-hash → LEDGER → TELEMETRY → DRIFT`; expanded cold-boot self-check.
- `agents` — Pyramid roles (Strategist · Analyst · **Executor** [only mutator] · Auditor), capability-whitelisted.
- `rooms` — DBOMBCENTRAL filtered surfaces over ONE shared runtime.
- `tracing` — colorized, thread-linked Trace Engine + anomaly/drift detector (`DRIFT_REPORT.json`, `telemetry/anomalies/`).
- `evolution` — self-diagnosis → repair planner → patch proposals (propose-only).
- `embedded_server` — hosts the FastAPI service as a separate process (own GIL) inside the packaged runtime.

## Verified status (frozen runtime, BUILD-034)

Verified live in the packaged `DBOMBLOCAL.exe`:
- Boot gates: `boot_self_check = PASS_REAL_EXECUTION`, `mem_palace_boot = PASS_MEMORY_PERSISTED`.
- Substrate boot: delegates 6/6 `RESOLVED`, 7 rooms, 4 agents, replay + orchestration OK.
- Embedded API **serving** externally (`/health` RESOLVED 6/6); intent → `RESOLVED` audio artifact with **hash match** and a reconciled ledger row.
- **Durability:** artifact + ledger row survive process exit (no `_MEIPASS` phantoms).
- Backends: ffmpeg + Godot `PRESENT` (`backend_scan.json`, `FROZEN_RUNTIME`). AI heavy stack (torch/diffusers) honestly `ABSENT` / deferred.

## Honest non-goals / deferred
- React/TS room UI (next surface, connects to the verified API).
- Blender/Unreal adapters, local image/audio model weights (absent).
- In-app diagnostics/fix-rendering surface (substrate side done; UI pending).

*This system is designed to become more capable, modular, traceable, autonomous, and diagnosable — without becoming deceptive, unverifiable, or narratively inflated.*
