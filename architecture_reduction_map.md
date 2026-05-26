# ARCHITECTURE REDUCTION MAP

Generated 2026-05-24. Grounded in `runtime_truth_audit.json` + `engine.system_synopsis` (270 real `.py` files observed).
Goal: collapse the over-expanded surface into **ONE primary surface + TRACE mode**, and cut everything that does not move an intent toward a real artifact.

---

## 1. THE CENTRAL FRAGMENTATION

There are **three orchestration spines** that all claim to be "the canonical path," and they do not agree:

| Spine | Entry | Reaches a real worker? | Used by UI? |
|---|---|---|---|
| **ClosedLoopEngine** (build-029) | `engine.closed_loop.loop_engine` | ❌ **No** — scores specs only | ✅ **Yes** (LaunchSurface:330) |
| **WorkerRouter + Guarantee** (build-023/025) | `engine.worker_router` | ✅ Yes — but gated, rejects valid intents | ❌ No (UI doesn't call it) |
| **CognitiveCore** (build-020) | `engine.cognitive_core` | partially (routes through WorkerRouter) | unclear / legacy |

**Reduction decision:** there must be exactly ONE spine. The ClosedLoop's scoring is valuable as a *refinement wrapper*, but it must terminate in a real `WorkerRouter.route()` call. CognitiveCore should be folded into or behind the same single dispatch.

---

## 2. DUPLICATE / OVERLAPPING SYSTEMS (candidates for merge or deletion)

From `system_synopsis` (10 duplicate filenames, 30 orphan modules) + manual reading:

### Overlapping orchestration / dispatch
- `engine/realm_dispatcher.py` — superseded by `worker_router.py` (build-023 deprecated its dispatch paths) → **demote to internal helper or delete**
- `engine/production_pipeline_engine.py` — its `_call_realm` was rewired through WorkerRouter → **keep only the pipeline-kind planning, drop direct realm calls**
- `engine/media_generation_layer.py` — `_dispatch_job` rewired through WorkerRouter → **merge into WorkerRouter or delete**
- `engine/tool_router.py` vs `engine/tool_fabric.py` vs `engine/production_tool_fabric.py` — three tool-capability surfaces → **collapse to one (`backend_registry` is the truth source)**

### Overlapping "intelligence" that produces no artifact
- `engine/aesthetic_intelligence/` · `engine/refinement/` · `engine/coherence/` · `engine/cinematic_director/` · `engine/oracle/` · `engine/semantic_memory/` · `engine/creative_composition/` — all real code, all compute scores/plans, **none produce a file**. → **Keep as an optional scoring sidecar; remove from the critical path until output works.**
- `engine/comparative_selector_v2.py` + `_FakeOutcome` — selects among *fabricated* outcomes → **must select among REAL worker outcomes or be disabled.**

### Legacy STRATUM layer (pre-build-018, per CLAUDE.md)
- `consciousness.py`, `perceptual_engine.py`, `agent_chatroom.py`, `pyramid_*.py`, `stratum_ui.py`, `pyramid_ui.py`, `simcore*.py` — the original app. Much is **orphaned** relative to the new engine/. → **Quarantine into a `legacy/` folder; do not load at boot.**

### DBOMBCENTRAL_WON subtree
- 30 orphan modules reported by synopsis live here → **not imported by the running app; exclude from the build and from boot.**

---

## 3. DEAD PATHS / UNUSED SURFACES

| Item | Why it's dead | Action |
|---|---|---|
| `_FakeOutcome` (loop_engine) | fabricates READY so scorer runs | **delete** once loop calls real worker |
| 18 AST-invalid `.py` files (synopsis) incl. `app.py`*, `briefer.py` | *app.py runs frozen but fails standalone AST parse — triage | triage parse errors |
| ~60 root-level `_*.py` / `_*.log` / `_*.png` scratch files | dev scratch (`_verify_*`, `_bare_run*`, `_v12_*`) | **move to `scratch/` or delete** |
| Tab sprawl in main window | build-024 already introduced LaunchSurface as primary; old tabs still constructed during the 134 s `init_ui` | **stop constructing non-primary tabs eagerly** |

---

## 4. THE TARGET: ONE PRIMARY SURFACE + TRACE MODE

LaunchSurface (build-024) is already the right primary shell. Reduce to:

```
┌─────────────────────────────────────────────────────────┐
│ PRIMARY SURFACE  (LaunchSurface)                          │
│  • prompt input            ← single intent box            │
│  • execution stream        ← push events from LiveStreamBus│
│  • artifact preview        ← REAL file preview (not score) │
│  • backend status          ← from backend_registry         │
│  • truth diagnostics       ← runtime_truth_audit summary   │
├─────────────────────────────────────────────────────────┤
│ TRACE MODE  (toggle, collapsed by default)                │
│  • execution logs / stderr / stdout                       │
│  • timing + subprocess details                            │
│  • lineage + validation chain                             │
│  • CQI / closed-loop scoring (demoted here)               │
└─────────────────────────────────────────────────────────┘
```

**Rule:** the primary surface shows **artifacts and backend truth**. All scoring/intelligence output (CQI, feedback vectors, oracle advisories) moves into TRACE. Intelligence is diagnostic, not the product.

---

## 5. BOOT REDUCTION

Boot is **166 s** because `init_ui` constructs the entire legacy + intelligence surface eagerly (134 s in one phase).

- Construct **only** LaunchSurface + LiveStreamBus + WorkerRouter at boot.
- Everything else (legacy tabs, intelligence sidecars, synopsis) → lazy, on first use, on a worker thread (the `DeferredWorkspaceLoader` already exists).
- Target: **< 5 s to interactive.**

---

## 6. REDUCTION SUMMARY (what to keep on the critical path)

**KEEP (critical path):**
`runtime/` (registry, deferred loader) · `engine/worker_router.py` · `engine/workers/*` · `engine/artifact_validator.py` · `engine/artifact_lineage.py` (via production_core) · `engine/preview_registry.py` · `engine/backend_registry.py` · `engine/live_stream.py` · `ui/production_console/launch_surface.py` · `truth/receipt_engine.py`

**DEMOTE to optional scoring sidecar (off critical path):**
`closed_loop/` · `creative_composition/` · `aesthetic_intelligence/` · `refinement/` · `coherence/` · `cinematic_director/` · `oracle/` · `semantic_memory/` · `comparative_selector_v2`

**QUARANTINE (legacy, don't boot):**
`consciousness.py` · `perceptual_engine.py` · `pyramid_*` · `stratum_ui.py` · `simcore*` · `DBOMBCENTRAL_WON/`

**DELETE:**
`_FakeOutcome` · root `_*.py`/`_*.log`/`_*.png` scratch · deprecated dispatch paths in `realm_dispatcher`/`media_generation_layer`
