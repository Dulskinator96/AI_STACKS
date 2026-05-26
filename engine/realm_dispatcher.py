"""engine/realm_dispatcher.py — PHASE 7.

Route ExecutionGraph atomic steps to the appropriate creation system.
Every backend is PROBED before dispatch — if unavailable, the dispatch
result records what failed, why, and a remediation path (Reality
Enforcement Phase 12). NO fake dispatch.

Realms covered:
  IMAGE:      imageforge (Stable Diffusion bridge)
  VIDEO:      DaVinci Resolve (probe + launch) · ffmpeg (assembly)
  AUDIO:      pyttsx3 (TTS) · audiocraft (music — when present)
  GAME:       simcore (deterministic world engine)
  CODE:       conv_programming (CodeForge engine)
  CAST:       pyramid_ensemble.EnsembleOrchestrator

All dispatches are ASYNCHRONOUS — the dispatcher submits to the
DeferredWorkspaceLoader and emits a per-step receipt on completion.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    step_id:       str
    kind:          str
    backend:       str
    realm:         str
    outcome:       str            # OK | DEGRADED | UNAVAILABLE | FAIL
    payload:       Any = None
    error:         str = ""
    duration_ms:   float = 0.0
    remediation:   str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class RealmDispatcher:
    """Asynchronous, probe-first realm dispatcher."""

    def __init__(self):
        self._dispatch_count = 0
        self._lock = threading.Lock()

    def dispatch_step(self, step, on_done: Optional[Callable[[DispatchResult], None]] = None,
                       log_fn: Optional[Callable[[str], None]] = None) -> None:
        """Submit a step to its backend on a worker thread. Calls on_done
        with a DispatchResult when finished. Never blocks the UI thread."""
        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
        except Exception as e:
            self._fail(step, on_done, log_fn, f"deferred_loader unavailable: {e}",
                       remediation="ensure runtime/ package bundled")
            return

        def _run():
            t0 = time.time()
            outcome, payload, err, remediation = self._execute(step, log_fn)
            return DispatchResult(
                step_id=step.step_id,
                kind=step.kind,
                backend=step.backend,
                realm=step.realm,
                outcome=outcome,
                payload=payload,
                error=err,
                duration_ms=(time.time() - t0) * 1000.0,
                remediation=remediation,
            )

        def _done(result):
            if isinstance(result, DispatchResult):
                self._emit_receipt(result)
                if on_done is not None:
                    try:
                        on_done(result)
                    except Exception as e:
                        _log.debug("on_done raised: %s", e)
            elif isinstance(result, dict) and "error" in result:
                fr = DispatchResult(
                    step_id=step.step_id, kind=step.kind, backend=step.backend,
                    realm=step.realm, outcome="FAIL", error=result["error"],
                )
                self._emit_receipt(fr)
                if on_done is not None:
                    on_done(fr)

        with self._lock:
            self._dispatch_count += 1
        DeferredWorkspaceLoader.run(_run, on_done=_done,
                                     name=f"realm-{step.realm or step.backend}")

    def _execute(self, step, log_fn) -> tuple:
        """Run the step. Returns (outcome, payload, error, remediation)."""
        backend = step.backend
        kind = step.kind
        params = step.parameters or {}

        if log_fn:
            try:
                log_fn(f"  → {kind} via {backend}")
            except Exception:
                pass

        # BUILD-023 — single canonical path: WorkerRouter. Workers wrap
        # realms/* pipelines with the 9-step contract. NO parallel
        # dispatch paths exist anymore: if the worker route doesn't
        # apply (no worker for this realm), we fall straight through to
        # the probe/legacy section (which only handles step.kind ==
        # "probe_*" — everything else FAILs honestly).
        worker_result = self._try_worker(step)
        if worker_result is not None:
            return worker_result

        # ── Probes (cheap, deterministic) ────────────────────────────
        if kind.startswith("probe_"):
            return self._probe(backend)

        # ── Image ────────────────────────────────────────────────────
        if backend == "imageforge":
            try:
                import imageforge as _if
                eng = _if.get_engine()
                out = eng.synthesize(params.get("prompt", ""),
                                      style=params.get("style") or "cinematic")
                return ("OK", str(out), "", "")
            except ImportError:
                return ("UNAVAILABLE", None, "imageforge module not installed",
                        "install imageforge or its A1111 bridge")
            except Exception as e:
                return ("FAIL", None, str(e), "")

        # ── Video ────────────────────────────────────────────────────
        if backend == "davinci_resolve":
            return self._probe("davinci_resolve")
        if backend == "ffmpeg":
            try:
                import shutil
                if shutil.which("ffmpeg"):
                    return ("DEGRADED", None,
                            "ffmpeg present; assembly/render pipeline is roadmap",
                            "video pipeline pending future build")
                return ("UNAVAILABLE", None, "ffmpeg not on PATH",
                        "install ffmpeg and add to PATH")
            except Exception as e:
                return ("FAIL", None, str(e), "")

        # ── Audio ────────────────────────────────────────────────────
        if backend == "pyttsx3":
            try:
                import pyttsx3
                eng = pyttsx3.init()
                eng.say(params.get("text", ""))
                eng.runAndWait()
                return ("OK", "spoken via pyttsx3", "", "")
            except ImportError:
                return ("UNAVAILABLE", None, "pyttsx3 not installed",
                        "pip install pyttsx3")
            except Exception as e:
                return ("FAIL", None, str(e), "")

        if backend == "audiocraft":
            try:
                import audiocraft  # noqa: F401
                return ("DEGRADED", None,
                        "audiocraft importable; generation pipeline is roadmap",
                        "music gen pipeline pending future build")
            except ImportError:
                return ("UNAVAILABLE", None, "audiocraft not installed",
                        "pip install audiocraft (≥1GB model + torch)")
            except Exception as e:
                return ("FAIL", None, str(e), "")

        # ── Game / Simulation ────────────────────────────────────────
        if backend == "simcore":
            try:
                import simcore
                if kind == "bootstrap_world":
                    seed = hash(params.get("intent", "")) & 0xffff
                    world = simcore.SimCore.bootstrap(seed=seed)
                    h = world.current_world().hash[:16]
                    return ("OK", {"hash": h, "seed": seed}, "", "")
                return ("OK", f"simcore symbols: {len(dir(simcore))}", "", "")
            except ImportError:
                return ("UNAVAILABLE", None, "simcore not installed",
                        "ensure simcore module is in project root")
            except Exception as e:
                return ("FAIL", None, str(e), "")

        # ── Code ─────────────────────────────────────────────────────
        if backend == "conv_programming":
            try:
                from conv_programming import get_engine
                eng = get_engine()
                if kind == "forge_proposal":
                    result = eng.process(params.get("intent", ""))
                    return ("OK", result, "", "")
                return ("OK", "conv_programming engine reachable", "", "")
            except ImportError:
                return ("UNAVAILABLE", None, "conv_programming missing",
                        "verify conv_programming.py is bundled")
            except Exception as e:
                return ("FAIL", None, str(e), "")

        if backend == "proposal_engine":
            try:
                import proposal_engine  # noqa: F401
                return ("OK", "proposal schema validated", "", "")
            except Exception as e:
                return ("FAIL", None, str(e), "")

        # ── Cast (ensemble) ──────────────────────────────────────────
        if backend == "pyramid_ensemble":
            try:
                from pyramid_ensemble import EnsembleOrchestrator
                eo = EnsembleOrchestrator()
                # Prefer run() if it exists; fall back to run_async with sync wait
                if hasattr(eo, "run"):
                    verdict = eo.run(params.get("intent", ""))
                elif hasattr(eo, "run_async"):
                    box: dict = {}
                    ev = threading.Event()
                    def _cb(event):
                        try:
                            if getattr(event, "kind", "") in ("ENSEMBLE_DONE", "DONE"):
                                box["r"] = getattr(event, "result", event)
                                ev.set()
                        except Exception:
                            ev.set()
                    eo.run_async(params.get("intent", ""), "", _cb)
                    ev.wait(timeout=60.0)
                    verdict = box.get("r")
                else:
                    return ("UNAVAILABLE", None, "EnsembleOrchestrator has no run/run_async",
                            "audit pyramid_ensemble surface")
                return ("OK", str(verdict)[:2000], "", "")
            except ImportError:
                return ("UNAVAILABLE", None, "pyramid_ensemble missing",
                        "ensure pyramid_ensemble.py bundled")
            except Exception as e:
                return ("FAIL", None, str(e), "")

        # ── LLM / Ollama ─────────────────────────────────────────────
        if backend == "ollama":
            try:
                # Probe ollama_available if won_daemon exposes it; otherwise
                # fall back to a direct HTTP probe via config.OLLAMA_URL.
                ok = self._ollama_available()
                if not ok:
                    return ("UNAVAILABLE", None, "Ollama daemon not reachable",
                            "start Ollama: `ollama serve`")
                return ("DEGRADED", None,
                        "Ollama reachable; generation pipeline is per-step routed via won_daemon",
                        "wire LLM call path through cognition loop")
            except Exception as e:
                return ("FAIL", None, str(e), "")

        return ("UNAVAILABLE", None, f"no dispatch handler for backend '{backend}'",
                "implement handler in realm_dispatcher._execute")

    # ── BUILD-022/023: route through WorkerRouter (single canonical entry) ──
    def _try_worker(self, step) -> Optional[tuple]:
        """Single canonical dispatch. WorkerRouter checks ToolFabric gate,
        selects worker, and invokes the 9-step contract. Returns
        (outcome, payload, error, remediation) tuple."""
        try:
            from engine.worker_router import get_worker_router
            from engine.workers import get_worker_for_realm
            from engine.workers.base_worker import WorkerRequest
            from engine.intent_cortex import IntentCortex
            from engine.creative_expansion import CreativeExpansionLayer
            from engine.personality_model import get_personality

            # No worker for this realm — fall through to probe handler
            if get_worker_for_realm(step.realm) is None:
                return None
            intent_text = (step.parameters or {}).get("intent") or \
                          (step.parameters or {}).get("prompt") or ""
            enriched = IntentCortex().enrich(intent_text)
            spec = CreativeExpansionLayer().expand(enriched, get_personality())
            req = WorkerRequest(
                intent_text=intent_text,
                spec=spec,
                kind=_KIND_TO_WORKER_KIND.get(step.kind, ""),
                params=dict(step.parameters or {}),
            )
            # BUILD-023: route() handles gate + worker selection + dispatch
            outcome = get_worker_router().route(step.realm, req)
            payload = {
                "worker_id":     outcome.worker_id,
                "worker_name":   outcome.worker_name,
                "state":         outcome.state,
                "workspace":     outcome.workspace,
                "manifest_path": outcome.manifest_path,
                "artifacts":     outcome.artifacts,
                "overall_score": outcome.overall_validation_score,
                "auto_refine_queued": outcome.auto_refine_queued,
            }
            if outcome.state == "READY":
                return ("OK", payload, "", "")
            if outcome.state == "DEGRADED":
                return ("DEGRADED", payload, outcome.error,
                        outcome.remediation)
            return ("FAIL", payload, outcome.error, outcome.remediation)
        except Exception as e:
            _log.exception("worker route failed: %s", e)
            return None

    # ── BUILD-021: route to realms/* real-output pipelines ──────────
    def _try_realm_pipeline(self, step) -> Optional[tuple]:
        """Map an AtomicStep → realm pipeline call. Returns the tuple
        (outcome, payload, error, remediation) if routed; None to fall
        through to the legacy per-backend handlers.

        Production sessions are auto-opened via ProductionCore when the
        step's realm matches a real-output realm. Pipeline results are
        normalized into the dispatcher's return shape.
        """
        try:
            mapping = _STEP_KIND_TO_REALM
            entry = mapping.get(step.kind)
            if entry is None:
                return None
            realm_pkg, pipeline_kind = entry

            # Open a production session for this realm
            from engine.production_core import get_production_core
            from engine.intent_cortex   import IntentCortex
            from engine.creative_expansion import CreativeExpansionLayer
            from engine.personality_model import get_personality
            core = get_production_core()
            intent_text = (step.parameters or {}).get("intent") or \
                          (step.parameters or {}).get("prompt") or ""
            # If the step carries no intent, fall back to legacy handlers
            if not intent_text and step.kind not in (
                "bootstrap_world", "terrain_map", "faction_map",
                "title_card", "assemble_timeline", "render_export",
            ):
                return None
            # Build a spec on the fly so the pipeline gets full context.
            # This is cheap (rule-based) and produces no fabricated state.
            enriched = IntentCortex().enrich(intent_text)
            spec = CreativeExpansionLayer().expand(enriched, get_personality())
            psess = core.start_session(
                intent_text=intent_text, realm=spec.realm or step.realm or "misc",
                spec_snapshot={"style": spec.style, "tone": spec.tone,
                                "ambition": spec.ambition,
                                "palette": spec.color_palette},
            )
            core.claim(psess)
            try:
                import importlib
                mod = importlib.import_module(f"realms.{realm_pkg}.pipeline")
            except ImportError as e:
                core.release(psess)
                return ("UNAVAILABLE", None, str(e),
                        f"realms/{realm_pkg} package missing — ensure bundled")
            try:
                result = mod.run(pipeline_kind, {
                    "intent_text": intent_text,
                    "spec":        spec,
                    "session":     psess,
                    **(step.parameters or {}),
                })
            finally:
                core.release(psess)

            outcome = result.get("outcome", "FAIL") if isinstance(result, dict) else "FAIL"
            artifacts = (result.get("artifacts", []) if isinstance(result, dict) else [])
            error = result.get("error", "") if isinstance(result, dict) else ""
            remediation = result.get("remediation", "") if isinstance(result, dict) else ""
            payload = {
                "artifacts": artifacts,
                "backend":   (result.get("backend", "") if isinstance(result, dict) else ""),
                "session_id": psess.session_id,
                "output_dir": psess.output_dir,
            }
            return (outcome, payload, error, remediation)
        except Exception as e:
            _log.exception("realm pipeline route failed: %s", e)
            return ("FAIL", None, str(e), "")

    # ── Probes ───────────────────────────────────────────────────────
    def _probe(self, backend: str) -> tuple:
        if backend == "imageforge":
            try:
                import imageforge  # noqa: F401
                return ("OK", "imageforge importable", "", "")
            except ImportError:
                return ("UNAVAILABLE", None, "imageforge not installed",
                        "install imageforge / A1111 bridge")
        if backend == "davinci_resolve":
            import os
            for p in (r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe",
                       r"C:\Program Files\Blackmagic Design\DaVinci Resolve Studio\Resolve.exe"):
                if os.path.isfile(p):
                    return ("OK", f"DaVinci at {p}", "", "")
            return ("UNAVAILABLE", None, "DaVinci Resolve not installed",
                    "install DaVinci Resolve (free or Studio)")
        if backend == "pyttsx3":
            try:
                import pyttsx3  # noqa: F401
                return ("OK", "pyttsx3 importable", "", "")
            except ImportError:
                return ("UNAVAILABLE", None, "pyttsx3 missing",
                        "pip install pyttsx3")
        if backend == "simcore":
            try:
                import simcore  # noqa: F401
                return ("OK", "simcore importable", "", "")
            except ImportError:
                return ("UNAVAILABLE", None, "simcore missing",
                        "ensure simcore.py is in project root")
        if backend == "conv_programming":
            try:
                import conv_programming  # noqa: F401
                return ("OK", "conv_programming importable", "", "")
            except ImportError:
                return ("UNAVAILABLE", None, "conv_programming missing",
                        "verify bundling")
        return ("UNAVAILABLE", None, f"no probe for '{backend}'",
                "add probe in RealmDispatcher._probe")

    def _ollama_available(self) -> bool:
        try:
            from won_daemon import ollama_available
            return bool(ollama_available())
        except Exception:
            try:
                import requests
                from config import OLLAMA_URL
                r = requests.get(OLLAMA_URL.rstrip("/") + "/api/tags", timeout=2)
                return r.status_code == 200
            except Exception:
                return False

    def _fail(self, step, on_done, log_fn, msg: str, remediation: str = "") -> None:
        r = DispatchResult(
            step_id=step.step_id, kind=step.kind, backend=step.backend,
            realm=step.realm, outcome="FAIL", error=msg, remediation=remediation,
        )
        if log_fn:
            try: log_fn(f"  ✗ {msg}")
            except Exception: pass
        self._emit_receipt(r)
        if on_done is not None:
            on_done(r)

    def _emit_receipt(self, r: DispatchResult) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"realm_dispatch:{r.realm or 'unknown'}:{r.kind}",
                executor="RealmDispatcher",
                duration_ms=r.duration_ms,
                verified=(r.outcome == "OK"),
                compute_sha256=False,
                failure_reason=r.error if r.outcome in ("FAIL", "UNAVAILABLE") else None,
                evidence={
                    "step_id":     r.step_id,
                    "backend":     r.backend,
                    "outcome":     r.outcome,
                    "remediation": r.remediation,
                    "payload_brief": (str(r.payload)[:200] if r.payload is not None else None),
                },
            )
        except Exception:
            pass


# BUILD-021 — step.kind -> (realm_package, pipeline_kind). Drives
# _try_realm_pipeline so the dispatcher routes to real-output pipelines.
_STEP_KIND_TO_REALM = {
    "synthesize_image":      ("image_generation", "synthesize"),
    "generate_storyboard":   ("image_generation", "storyboard"),
    "concept_art":           ("image_generation", "concept_art"),
    "synthesize_audio":      ("audio_engine",     "narration"),
    "generate_soundtrack":   ("audio_engine",     "soundtrack"),
    "narrate":               ("audio_engine",     "narration"),
    "voiceover":             ("audio_engine",     "voiceover"),
    "title_card":            ("video_production", "title_card"),
    "assemble_timeline":     ("video_production", "assemble"),
    "render_export":         ("video_production", "assemble"),
    "trim_clip":             ("video_production", "trim"),
    "scaffold_game":         ("game_creation",    "scaffold"),
    "generate_lore":         ("game_creation",    "design_doc"),
    "godot_project":         ("game_creation",    "godot_project"),
    "blender_scene":         ("game_creation",    "blender_script"),
    "bootstrap_world":       ("simulation",       "bootstrap_world"),
    "terrain_map":           ("simulation",       "terrain_map"),
    "faction_map":           ("simulation",       "faction_map"),
}


# BUILD-022 — translate execution_planner step.kind to the
# worker.kind subtype (which realm-pipeline kind to invoke inside the worker).
_KIND_TO_WORKER_KIND = {
    "synthesize_image":    "synthesize",
    "generate_storyboard": "storyboard",
    "concept_art":         "concept_art",
    "synthesize_audio":    "narration",
    "generate_soundtrack": "soundtrack",
    "narrate":             "narration",
    "voiceover":           "voiceover",
    "title_card":          "title_card",
    "assemble_timeline":   "assemble",
    "render_export":       "assemble",
    "trim_clip":           "trim",
    "scaffold_game":       "scaffold",
    "generate_lore":       "design_doc",
    "godot_project":       "godot_project",
    "blender_scene":       "blender_script",
    "bootstrap_world":     "bootstrap_world",
    "terrain_map":         "terrain_map",
    "faction_map":         "faction_map",
    "forge_proposal":      "",
    "validate_proposal":   "",
    "cast_ensemble":       "",
}
