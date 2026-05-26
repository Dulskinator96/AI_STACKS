# CAPABILITY GAP REPORT

Generated 2026-05-24 from `telemetry/runtime_truth_audit.json` (direct runtime probes, not assertions).
Python 3.14.4 · exe `build/release/DBOMBLOCAL.exe` 214,982,500 bytes.

This report answers the only four questions that matter:
**what actually works · what partially works · what is fake or unverified · what infrastructure is missing.**

---

## 1. WHAT ACTUALLY WORKS (VERIFIED — measured, observable artifact)

| Subsystem | Evidence |
|---|---|
| **Module imports** | 12/12 canonical anchors import clean (1637 ms) |
| **AudioWorker (called directly)** | Produces a **real 1,058,444-byte `.wav`** via procedural numpy synthesis; file exists + passes validation. State READY, backend `procedural_audio`. |
| **Worker contract substrate** | `BaseWorker.execute` 9-step contract runs: workspace → manifest → execute → validate → hash → lineage → preview → READY |
| **Artifact validation** | `ArtifactValidator` returns real valid/score on the produced `.wav` |
| **Preview registry** | preview entry created for the real artifact |
| **Memory / receipt persistence** | `execution_receipts.jsonl` grows on write (1.7 ms round-trip); persistent state JSONs present |
| **Subprocess execution** | `git --version` rc=0 in 28 ms |
| **Crash handling** | unknown realm + malformed request both return FAIL outcomes — router never raises |
| **Thread stability** | 4 concurrent dispatches, 0 exceptions (they returned FAIL, but the runtime did not crash) |
| **Executable startup** | last real launch reached `state:READY` / `first_paint` (self-instrumented) |

**The generator layer is real.** When a worker is invoked directly, it produces a real, validated file. This is the foundation worth keeping.

---

## 2. WHAT PARTIALLY WORKS (PARTIAL / MISCONFIGURED)

| Subsystem | Status | Reality |
|---|---|---|
| **UI render** | PARTIAL | App self-records `first_paint`, but **boot to interactive = 166,669 ms (~2.8 min)**. One phase (`phase:maintenance → hd_init_ui_done`) ate **134 seconds**. Pixel correctness not observable headless. |
| **LLM backend invocation** | PARTIAL | Ollama (11434) + LM Studio (1234) both reachable. Ollama lists 6 models (llama3.2, llama3.1:8b, codellama:13b, qwen2.5-coder:1.5b/32b). **But a real `/api/generate` round-trip TIMED OUT at 30 s** (cold 32B load). No verified end-to-end generation yet. |
| **Backend reachability** | PARTIAL | LLM up; all creative backends down (see §4). |
| **GPU detection** | PARTIAL | `nvidia-smi` path probed; no CUDA GPU surfaced, `torch` absent → image/video diffusion would be CPU-only or impossible. |
| **Contract compiler gate** | MISCONFIGURED | `ContractCompiler` **rejects valid intents**. `"generate a 2 second ambient tone"` → REJECTED "too vague", even though `"create audio of ocean waves"` is accepted. When it rejects, the working worker never runs. |
| **Filesystem lineage** | PARTIAL | lineage file present; delta on the probe run was inconclusive because the routed worker failed before lineage write. |

---

## 3. WHAT IS FAKE OR UNVERIFIED (BROKEN — the core problem)

### 🔴 CANONICAL PATH INTEGRITY — BROKEN

**The surface the user types into never invokes a generator.**

- `LaunchSurface._on_submit` (launch_surface.py:330) dispatches every intent to `ClosedLoopEngine.run()`.
- `ClosedLoopEngine.run()` does: `enrich → expand → generate candidate SPECS → CQI score → pick highest score → return COMPLETED`.
- **There is no `worker.execute`, no `WorkerRouter.route`, no artifact write anywhere in that loop.**
- `loop_engine._FakeOutcome` literally fabricates `state="READY", artifacts=[]` so the comparative selector has a number to read.

> Result: typing an intent into the UI produces a **CQI score and a "winner spec"** — never an image, audio file, video, game, or code file.

### 🔴 Two real generators, both unreachable from the UI

1. **AudioWorker works** — but is only reachable via `WorkerRouter.route`, which the UI does not call.
2. **`WorkerRouter.route` itself** wraps the worker in `ProductionGuarantee.guarantee()`, whose `ContractCompiler` rejects reasonable intents and returns a **synthetic FAIL** without ever invoking the worker.

So there are **two independent breaks** between "user intent" and "real file":
- Break A: UI → ClosedLoop never reaches a worker.
- Break B: WorkerRouter → Guarantee gate rejects valid intents.

This is the precise failure the validation directive named: **a scoring engine wearing the costume of a production engine.**

---

## 4. WHAT INFRASTRUCTURE IS MISSING

Measured on this machine (`shutil.which` + `importlib.util.find_spec` + port probes):

| Need | Realm | Present? |
|---|---|---|
| `ffmpeg` / `ffprobe` | video, audio mux | ❌ NOT FOUND |
| `godot` | game export | ❌ NOT FOUND |
| `blender` | 3D / game assets | ❌ NOT FOUND |
| `torch` | image/video diffusion | ❌ MISSING |
| `diffusers` | image gen | ❌ MISSING |
| `transformers` | model loading | ❌ MISSING |
| `soundfile` | audio I/O | ❌ MISSING (worker uses stdlib `wave` instead — fine) |
| `cv2` (opencv) | video/image frames | ❌ MISSING |
| ComfyUI (8188) | image gen | ❌ closed |
| Automatic1111 (7860) | image gen | ❌ closed |
| `numpy`, `PIL`, `scipy`, `PyQt6`, `requests` | core | ✅ present |
| **Ollama (11434)** | text/code LLM | ✅ **OPEN** (6 models) |
| **LM Studio (1234)** | text LLM | ✅ **OPEN** (gemma + embeddings) |

**Net:** Only **text/code** (via Ollama/LM Studio), **procedural audio** (numpy `.wav`), **procedural simulation** (numpy/PIL), and **PIL image manipulation** have real backing on this machine right now. **Image diffusion, video, and game export have no backend installed.**

---

## 5. CAPABILITY SCORECARD vs. STATED TARGETS

| Stated capability | Real status |
|---|---|
| Prompt engineering / workflow orchestration | scaffolding present; not wired to output |
| Local AI coordination | **PARTIAL** — Ollama/LMStudio reachable, generation unverified (timeout) |
| Image generation | **MISSING BACKEND** — no torch/diffusers/ComfyUI/A1111 |
| Video generation | **MISSING BACKEND** — no ffmpeg |
| Audio/music generation | **VERIFIED (procedural)** — real `.wav`; no Bark/AudioCraft |
| Code generation | **PLAUSIBLE** — Ollama codellama/qwen-coder present; not verified end-to-end |
| Game generation | **SCAFFOLD ONLY** — no Godot/Blender |
| Cinematic composition | computes CQI scores; **no rendered output** |
| Memory-backed personalization | **VERIFIED** — receipts + persistent state files |
| Iterative refinement | runs as scoring; refines *specs*, not artifacts |
| Execution verification | **VERIFIED** for direct worker calls; bypassed on UI path |

---

## 6. BOTTOM LINE

The app is **not** a fake shell *at the generator layer* — the audio worker proves real production works.
The app **is currently a scoring engine at the surface layer** — the UI path never reaches a generator.

**Shortest path to real capability** is not more intelligence. It is **three wires and one install** (see `production_roadmap.md`):
1. Connect `ClosedLoopEngine`/`LaunchSurface` to `WorkerRouter` so an intent yields a file.
2. Make the `ContractCompiler` fail *open* (dispatch the worker) instead of fail *closed* (synthetic FAIL).
3. Verify one real Ollama generation round-trip (warm the model).
4. Install `ffmpeg` + (optionally) `torch`/ComfyUI for image/video.
