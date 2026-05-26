# PRODUCTION ROADMAP

Generated 2026-05-24. Priority order is the directive's Phase 6: **grounding before intelligence.**
Each step has a single acceptance test that must pass with a REAL artifact — no scores, no self-report.

> Governing rule: **UNVERIFIED = INVALID.** A step is not "done" until its acceptance test produces an observable file or measured response.

---

## P0 — RECONNECT THE CANONICAL PATH (the only thing that matters first)

The generators work. The surface doesn't reach them. Fix the two breaks.

### P0.1 — Make ContractCompiler fail OPEN
- **Change:** in `WorkerRouter.route` (or `ProductionGuarantee.guarantee`), when the compiler returns REJECTED, fall back to the `IntentCortex`-detected realm and dispatch the worker anyway. Record low confidence as a diagnostic; never return a synthetic FAIL for a routable realm.
- **Acceptance:** `route("audio", "generate a 2 second ambient tone")` returns state READY with a real `.wav` (today it returns synthetic FAIL).

### P0.2 — Wire LaunchSurface → WorkerRouter
- **Change:** `LaunchSurface._on_submit` calls `WorkerRouter.route(realm, request)` (directly, or have `ClosedLoopEngine.run` terminate in it). Surface `WorkerOutcome.artifacts` in the preview panel.
- **Acceptance:** typing "generate audio of ocean waves" in the UI produces a playable `.wav` shown in the preview panel.

### P0.3 — Kill `_FakeOutcome`
- **Change:** `ClosedLoopEngine` either (a) generates candidates by calling `worker.execute` for real, or (b) is demoted to a post-hoc refinement that scores a REAL artifact. Delete `_FakeOutcome`.
- **Acceptance:** `ComparativeSelectorV2` only ever receives real `WorkerOutcome`s with non-empty `artifacts`.

**Exit P0 when:** a UI intent → a real file, end to end, for the `audio` and `simulation` realms.

---

## P1 — BACKEND TRUTH (live, not declared)

### P1.1 — Refresh backend_registry from live probes at boot
- Reuse the probe logic in `runtime_truth_audit.py` (`shutil.which`, `find_spec`, port checks) to populate `backend_registry` at startup.
- **Acceptance:** registry reports ffmpeg=UNAVAILABLE, ollama=READY matching reality; `decide()` consults only the registry.

### P1.2 — Verify one real Ollama round-trip
- Warm a **small** model: `ollama run qwen2.5-coder:1.5b`. Re-run the backend probe with the small model.
- **Acceptance:** `runtime_truth_audit.json → backend_invocation.real_generation == true` with captured text (today: timeout on 32B).

**Exit P1 when:** `code` realm produces a real `.py`/`.md` file via Ollama, validated.

---

## P2 — ARTIFACT VALIDATION HARDENING

- `ArtifactValidator` is the single source of truth (build-023). Confirm per-realm rules reject empty/corrupt files for every realm, not just audio.
- **Acceptance:** feeding a 0-byte file of each realm → validator returns `valid=False`; a real file → `valid=True`. Already true for audio.

---

## P3 — STABLE UI (fix the 166-second boot)

- Boot to interactive is **166,669 ms**; `init_ui` alone is **134 s**. This is the user-facing emergency after output.
- **Change:** at boot construct ONLY LaunchSurface + LiveStreamBus + WorkerRouter + backend_registry. Lazy-load everything else via `DeferredWorkspaceLoader` on first use. Quarantine legacy STRATUM tabs (don't construct).
- **Acceptance:** new `boot_profile_*.json` shows `click_to_interactive_ms < 5000`.

---

## P4 — REAL GENERATION, REALM BY REALM (install backends)

Lowest cost → highest unlock, in order:
1. **ffmpeg** → unlocks `video` assembly + audio mux. Acceptance: a real `.mp4` from image frames + audio.
2. **Image**: ComfyUI on 8188 (if GPU) or `pip install torch diffusers` + 1 SD model (CPU). Acceptance: a real non-procedural `.png` from a prompt.
3. **Godot 4** headless → `game` export. Acceptance: a runnable Godot project that opens.

Each realm flips from ⚠/❌ to ✅ in `backend_dependency_matrix.md` only when its acceptance test passes.

---

## P5 — MEMORY GROUNDING

- Receipts + persistent state already VERIFIED. Add: SQLite/vector store for project state + semantic retrieval (CLAUDE.md already anticipates this; `kernel.db` exists).
- **Acceptance:** an intent references a prior artifact by description and the system retrieves the real file path.

---

## P6 — ORCHESTRATION (multi-step projects)

- Only after single-realm output is real: task graph that decomposes "build me a cinematic cyberpunk strategy game" into ordered worker calls (assets → code → assembly) with lineage + retries.
- **Acceptance:** one compound intent yields multiple real artifacts with a dependency manifest.

---

## P7 — REFINEMENT (closed loop over REAL artifacts)

- Re-enable ClosedLoop/CQI **as a wrapper around real output**: generate → score the real file (pixel/audio analysis already exists) → regenerate if below threshold (bounded).
- **Acceptance:** a low-quality real artifact triggers a real regeneration that scores higher, both files on disk.

---

## P8 — INTELLIGENCE LAYERS (last)

- aesthetic_intelligence / oracle / cinematic_director / coherence / semantic_memory move from the critical path into TRACE-mode diagnostics that *inform* generation parameters. They never replace a worker call.
- **Acceptance:** disabling every intelligence module still produces real artifacts (proves grounding is independent of intelligence).

---

## SHORTEST PATH TO "REAL"

> **P0 (reconnect) + P1.2 (warm small model) + P3 (fast boot) + ffmpeg install.**
>
> After P0 alone, the app produces real audio and simulation files from the UI. That is the minimum honest claim of "a working orchestration engine," and it is **3 code wires + delete one fake class** away — no new intelligence required.

---

## STATUS LEDGER (update as tests pass)

| Step | Acceptance test | Status |
|---|---|---|
| P0.1 fail-open compiler | vague audio intent → real .wav | ⛔ NOT STARTED |
| P0.2 UI→WorkerRouter | UI intent → previewed .wav | ⛔ NOT STARTED |
| P0.3 kill _FakeOutcome | selector sees only real outcomes | ⛔ NOT STARTED |
| P1.1 live backend registry | registry matches probes | ⛔ NOT STARTED |
| P1.2 real Ollama gen | real_generation==true | ⛔ NOT STARTED |
| P3 fast boot | click_to_interactive < 5 s | ⛔ NOT STARTED |
| P4.1 ffmpeg video | real .mp4 | ⛔ NOT STARTED |
