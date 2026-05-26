# CANONICAL EXECUTION FLOW

Generated 2026-05-24. Two diagrams: **what runs today (broken)** and **the single canonical path that must exist**.

---

## A. WHAT ACTUALLY RUNS TODAY (measured)

```
user types intent in LaunchSurface
        │
        ▼
LaunchSurface._on_submit            (launch_surface.py:330)
        │
        ▼
ClosedLoopEngine.run(intent, count=4)   (engine/closed_loop/loop_engine.py)
        │
        ├─ IntentCortex.enrich(intent)          → enriched text
        ├─ CreativeExpansionLayer.expand(...)    → spec dataclass
        ├─ CandidateGenerator.generate(...)      → 3-7 SPEC variants
        ├─ CQI scoring per variant               → numbers
        ├─ ComparativeSelectorV2.select(...)     → reads _FakeOutcome(state=READY, artifacts=[])
        ├─ FeedbackVector (entropy adjust)       → numbers
        ├─ enforcer.verify(4 invariants)         → allowed/blocked
        └─ return LoopOutcome(state=COMPLETED)   → a winning SPEC + CQI score
        │
        ▼
   ❌ NO WORKER CALLED · ❌ NO FILE WRITTEN
```

**Separately, never reached by the UI:**

```
WorkerRouter.route(realm, request)      (engine/worker_router.py:101)
        │
        ▼
ProductionGuarantee.guarantee(...)      (engine/production_guarantee.py)
        │
        ├─ ContractCompiler.compile(intent)
        │        │
        │        └─ if "too vague" → REJECTED → worker_outcome=None
        │                              │
        │                              ▼
        │                    router returns SYNTHETIC FAIL   ❌ worker never runs
        │
        └─ if compiled → worker.execute(request)   ✅ real path (rarely taken)
                 │
                 ▼
        BaseWorker.execute  →  REAL artifact (verified: 1.05 MB .wav)
```

---

## B. THE SINGLE CANONICAL PATH (target)

One spine. Every intent terminates in a real worker invocation and a real validated artifact. Scoring is a *wrapper around* real output, never a substitute for it.

```
user intent (LaunchSurface)
        │
        ▼
[1] IntentCortex.enrich          → normalized intent + detected realm
        │
        ▼
[2] WorkerRouter.decide(realm)   → backend gate (backend_registry truth)
        │                            ├─ READY      → dispatch
        │                            └─ NO BACKEND → return FAIL + remediation (honest)
        ▼
[3] WorkerRouter.route(realm, request)
        │
        ▼
[4] BaseWorker.execute  ← 9-step contract (ALREADY REAL)
        │   workspace → manifest → _do_execute → VALIDATING →
        │   verify exists → sha256 → ArtifactValidator → lineage → preview
        │
        ├─ READY   → real artifact path + validation score
        └─ FAIL    → remediation (no backend / validation failed)
        │
        ▼
[5] (OPTIONAL sidecar) ClosedLoop / CQI refinement
        │   runs ONLY on a real artifact:
        │   score the produced file → if < threshold, regenerate via [3] again
        │   (bounded, max 2 extra cycles)
        ▼
[6] LiveStreamBus.emit(worker_ready, artifact)  → LaunchSurface preview
        │
        ▼
   ✅ user sees a REAL file (audio/image/video/code/game/sim)
```

### Contract changes required to make B real

1. **LaunchSurface._on_submit** must call (directly or via ClosedLoop) `WorkerRouter.route(realm, request)` and surface the resulting `WorkerOutcome.artifacts` — not a CQI score.
2. **ContractCompiler must fail OPEN**: on "too vague", default to the realm detected by `IntentCortex` and dispatch the worker anyway; record the low-confidence as a diagnostic, do not return synthetic FAIL.
3. **ClosedLoopEngine.run** must replace its `_FakeOutcome` candidates with real `worker.execute` results (or be moved entirely to step [5] as a post-hoc refinement over a real artifact).
4. **CQI/aesthetic scoring** reads the **real artifact** (pixel analysis already exists in `visual_harmony_pixel.py`) — not a spec.

### Realm → worker map (already wired, verified present)

| Realm | Worker | Backend today |
|---|---|---|
| audio | AudioWorker | ✅ procedural numpy (real) |
| image | ImageWorker | ❌ needs torch/diffusers/ComfyUI/A1111 |
| video | VideoWorker | ❌ needs ffmpeg |
| code | CodeWorker | ⚠ Ollama codellama/qwen-coder (reachable, unverified) |
| game | GameWorker | ❌ needs Godot/Blender (scaffold-only today) |
| simulation | SimulationWorker | ✅ numpy/PIL terrain (real) |
| cast | CastWorker | ⚠ pyramid_ensemble internal |

**Today, only `audio` and `simulation` can produce a real artifact end-to-end with installed backends.** That is the honest current envelope of the canonical path.
