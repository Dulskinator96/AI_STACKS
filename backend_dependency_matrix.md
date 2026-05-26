# BACKEND DEPENDENCY MATRIX

Generated 2026-05-24 from live probes (`shutil.which`, `importlib.util.find_spec`, socket port checks) recorded in `runtime_truth_audit.json`.
Legend: ✅ present & reachable · ⚠ reachable but unverified end-to-end · ❌ absent.

---

## 1. MEASURED ENVIRONMENT (this machine, now)

### Binaries (PATH)
| Binary | Status | Needed for |
|---|---|---|
| `git` | ✅ 2.53.0 | code repo ops |
| `node` | ✅ v24.14.1 | web/tooling |
| `ffmpeg` / `ffprobe` | ❌ NOT FOUND | video assembly, audio mux |
| `godot` | ❌ NOT FOUND | game export |
| `blender` | ❌ NOT FOUND | 3D assets |

### Python deps
| Package | Status | Needed for |
|---|---|---|
| `numpy` | ✅ | audio synth, sim, pixel analysis |
| `PIL` | ✅ | image manipulation, previews |
| `scipy` | ✅ | DSP |
| `PyQt6` | ✅ | UI |
| `requests` | ✅ | HTTP backends |
| `torch` | ❌ | diffusion (image/video) |
| `diffusers` | ❌ | Stable Diffusion |
| `transformers` | ❌ | model loading |
| `soundfile` | ❌ | audio I/O (worker uses stdlib `wave` — OK) |
| `cv2` | ❌ | video frames |

### Local service ports
| Service | Port | Status | Models seen |
|---|---|---|---|
| **Ollama** | 11434 | ✅ OPEN | llama3.2, llama3.1:8b, llama3, codellama:13b-instruct, qwen2.5-coder:1.5b, qwen2.5-coder:32b |
| **LM Studio** | 1234 | ✅ OPEN | google/gemma-4-e4b, nomic-embed-text-v1.5 |
| ComfyUI | 8188 | ❌ closed | — |
| Automatic1111 | 7860 | ❌ closed | — |

⚠ **Ollama `/api/generate` round-trip TIMED OUT at 30 s** in the probe (likely cold 32B model). Reachability ✅, real generation **unverified**.

---

## 2. PER-REALM REQUIRED vs AVAILABLE

| Realm | Preferred backend chain | Available now | Real output today? |
|---|---|---|---|
| **audio** | Bark → AudioCraft → pyttsx3 → **procedural numpy** | procedural numpy ✅ | ✅ **YES** (1.05 MB .wav verified) |
| **simulation** | numpy/PIL (diamond-square, Voronoi) | numpy/PIL ✅ | ✅ **YES** (terrain PNG) |
| **code** | local LLM (Ollama) → conv_programming | Ollama ⚠ | ⚠ likely, unverified (codellama/qwen present) |
| **cast** | pyramid_ensemble (internal) → Ollama | internal + Ollama ⚠ | ⚠ unverified |
| **image** | ComfyUI → A1111 → diffusers/torch → imageforge(PIL) | only PIL fallback | ⚠ PIL-only (no diffusion) |
| **video** | ffmpeg CLI (+ SVD/AnimateDiff) | none | ❌ **NO** (no ffmpeg) |
| **game** | Godot → Blender → design-doc scaffold | scaffold text only | ⚠ scaffold only, no engine |

---

## 3. MINIMUM INSTALL TO UNLOCK EACH REALM

| Realm | Smallest real-capability install |
|---|---|
| audio | *(already real)* — optional: `pip install bark` for TTS |
| simulation | *(already real)* |
| code | warm an Ollama coder model (`ollama run qwen2.5-coder:1.5b`) — small + fast |
| image | **Option A** `pip install torch diffusers` + 1 SD model (CPU slow). **Option B** run ComfyUI on 8188 (preferred if GPU). |
| video | install `ffmpeg`, add to PATH (unlocks assembly of image/audio into video) |
| game | install Godot 4 (headless export) — Blender optional for assets |

**Highest leverage, lowest cost:** `ffmpeg` (one download, unlocks video + audio mux) and warming a **small** Ollama coder model (`qwen2.5-coder:1.5b`, not the 32B that timed out).

---

## 4. BACKEND ABSTRACTION STATUS

- `engine/backend_registry.py` exists (build-026) and tracks 20 backend capabilities with `executable/runtime/output_verified` flags — **this is the right truth source.** It should be the single gate `WorkerRouter.decide()` consults (today routing also touches `tool_fabric`/`production_tool_fabric` — collapse to `backend_registry`).
- `WorkerRouter._remediation_for` already emits correct install hints for image/video — keep.
- **Gap:** `backend_registry` must be *refreshed from live probes at boot* (the same `shutil.which` / port checks this audit uses), not from static declarations, or it will report stale READY/UNAVAILABLE.
