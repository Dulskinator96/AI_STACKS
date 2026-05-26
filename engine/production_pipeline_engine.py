"""engine/production_pipeline_engine.py — BUILD-021 SECTION 13.

Multi-stage production pipeline coordinator. Orchestrates the full flow
for a complex creative intent across multiple realms:

  intent → analyze → expand → visual + soundtrack + voiceover →
    timeline assembly → reflection → refinement wave → export

This wraps the existing engines:
  · IntentCortex (already)
  · CreativeExpansionLayer (already)
  · realms/image_generation (new)
  · realms/audio_engine (new)
  · realms/video_production (new)
  · realms/game_creation (new)
  · realms/simulation (new)
  · ReflectionEngine (already)

The pipeline emits a per-stage receipt and writes a manifest of all
artifacts to the production session's output directory.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


PIPELINE_TRAILER = "trailer"          # script + visuals + audio + timeline
PIPELINE_GAME    = "game_concept"     # mechanics + world + soundtrack + concept_art
PIPELINE_ALBUM   = "album"            # multiple soundtracks
PIPELINE_GALLERY = "gallery"          # multiple images, single intent
PIPELINE_SIM     = "simulation"        # procedural world + tactical map


@dataclass
class PipelineRun:
    run_id:         str
    pipeline_kind:  str
    intent_text:    str
    started_at:     float
    stages:         list = field(default_factory=list)  # list[dict]
    state:          str = "INITIATED"   # INITIATED|RUNNING|REFINING|DONE|FAILED
    production_session_id: str = ""
    error:          str = ""
    overall_score:  float = 0.0

    def to_dict(self) -> dict:
        return {
            "run_id":              self.run_id,
            "pipeline_kind":       self.pipeline_kind,
            "intent_text":         self.intent_text[:200],
            "started_at":          self.started_at,
            "state":               self.state,
            "stage_count":         len(self.stages),
            "production_session_id": self.production_session_id,
            "error":               self.error,
            "overall_score":       self.overall_score,
        }


class ProductionPipelineEngine:
    """Multi-stage production coordinator."""

    def __init__(self):
        self._runs: dict[str, PipelineRun] = {}
        self._lock = threading.RLock()
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.production_pipeline", self)
        except Exception:
            pass

    def detect_pipeline(self, intent_text: str) -> str:
        """Heuristic pipeline selection."""
        t = (intent_text or "").lower()
        if any(k in t for k in ("trailer", "intro", "cinematic", "promo")):
            return PIPELINE_TRAILER
        if any(k in t for k in ("game", "level", "playable", "world", "mechanics")):
            return PIPELINE_GAME
        if any(k in t for k in ("album", "ep ", "soundtrack collection")):
            return PIPELINE_ALBUM
        if any(k in t for k in ("gallery", "concept art", "image set", "moodboard")):
            return PIPELINE_GALLERY
        if any(k in t for k in ("simulation", "tactical map", "world simulation")):
            return PIPELINE_SIM
        return PIPELINE_GALLERY   # default to single-realm image production

    def run(self, intent_text: str, pipeline_kind: Optional[str] = None,
            on_stage: Optional[Callable[[str, PipelineRun], None]] = None,
            on_complete: Optional[Callable[[PipelineRun], None]] = None) -> PipelineRun:
        """Submit a pipeline run. Returns immediately; the run executes
        on a worker thread."""
        t0 = time.time()
        rid = f"pipe-{uuid.uuid4().hex[:10]}"
        kind = pipeline_kind or self.detect_pipeline(intent_text)
        run = PipelineRun(
            run_id=rid, pipeline_kind=kind,
            intent_text=intent_text or "",
            started_at=t0,
        )
        with self._lock:
            self._runs[rid] = run

        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
        except Exception as e:
            run.state = "FAILED"
            run.error = f"deferred_loader missing: {e}"
            if on_complete:
                on_complete(run)
            return run

        def _emit(stage_name: str, payload: dict):
            run.stages.append({
                "stage":     stage_name,
                "ts":        time.time(),
                "payload":   payload,
            })
            self._emit_receipt(run, stage_name)
            if on_stage:
                try: on_stage(stage_name, run)
                except Exception: pass

        def _pipeline():
            try:
                run.state = "RUNNING"
                _emit("started", {})

                # Stage 1 — intent analysis
                from engine.intent_cortex import IntentCortex
                ic = IntentCortex()
                enriched = ic.enrich(intent_text)
                _emit("intent_analyzed", {"style": enriched.style, "medium": enriched.medium})

                # Stage 2 — creative expansion
                from engine.creative_expansion import CreativeExpansionLayer
                from engine.personality_model import get_personality
                ce = CreativeExpansionLayer()
                spec = ce.expand(enriched, get_personality())
                _emit("expanded", {"intent_id": spec.intent_id,
                                    "palette": spec.color_palette,
                                    "ambition": spec.ambition})

                # Stage 3 — open production session
                from engine.production_core import get_production_core
                core = get_production_core()
                primary_realm = spec.medium if spec.medium in (
                    "image", "video", "audio", "game", "simulation"
                ) else "cast"
                psess = core.start_session(
                    intent_text=intent_text, realm=primary_realm,
                    spec_snapshot={"style": spec.style, "tone": spec.tone,
                                    "palette": spec.color_palette,
                                    "ambition": spec.ambition,
                                    "soundtrack": spec.soundtrack_profile,
                                    "architecture": spec.architecture_style},
                )
                run.production_session_id = psess.session_id
                core.claim(psess)
                _emit("production_session_opened",
                       {"session_id": psess.session_id, "realm": primary_realm})

                # Stage 4 — pipeline-specific realm calls
                stage_results = self._run_pipeline_kind(kind, intent_text, spec, psess, _emit)

                # Stage 5 — reflection over the whole run
                from engine.reflection_engine import ReflectionEngine
                rfl = ReflectionEngine()
                # Build a synthetic dispatch_results list from stage_results
                synthetic_dispatch = [
                    {"outcome": sr.get("outcome", "OK"),
                     "kind":    sr.get("stage", "unknown"),
                     "backend": sr.get("backend", "production_pipeline"),
                     "error":   sr.get("error", "")}
                    for sr in stage_results
                ]
                # ReflectionEngine wants spec, graph, dispatch_results;
                # we don't have a graph object here — synthesize a minimal one.
                class _FakeGraph:
                    graph_id = run.run_id
                    realm = primary_realm
                    def step_count(self): return len(stage_results)
                report = rfl.reflect(spec, _FakeGraph(), synthetic_dispatch)
                run.overall_score = report.overall_score
                _emit("reflected",
                       {"score": report.overall_score,
                        "suggestions": report.suggestions[:3]})

                # Stage 6 — optional refinement wave (if score low)
                if run.overall_score < 0.55 and len(stage_results) > 0:
                    core.schedule_refinement(psess, passes=1)
                    run.state = "REFINING"
                    _emit("refinement_scheduled", {"wave": psess.refinement_wave})

                # Stage 7 — export manifest
                manifest = core.export(psess)
                _emit("exported",
                       {"artifact_count": len(manifest.get("artifacts", [])),
                        "output_dir":     psess.output_dir})
                core.release(psess)
                run.state = "DONE"

            except Exception as e:
                run.state = "FAILED"
                run.error = str(e)
                _log.exception("pipeline run %s failed: %s", rid, e)
                try:
                    from engine.production_core import get_production_core
                    if run.production_session_id:
                        psess = get_production_core().get_session(run.production_session_id)
                        if psess is not None:
                            get_production_core().fail(psess, str(e))
                except Exception:
                    pass

            self._emit_receipt(run, "complete")
            if on_complete:
                try: on_complete(run)
                except Exception: pass

        DeferredWorkspaceLoader.run(_pipeline, on_done=None, name=f"pipeline-{rid}")
        return run

    def _run_pipeline_kind(self, kind: str, intent_text: str, spec, psess,
                            emit_fn) -> list:
        """Dispatch the realm pipelines per pipeline kind."""
        results: list[dict] = []

        if kind == PIPELINE_TRAILER:
            # Image (concept frames) → Audio (soundtrack) → Video (assemble)
            results.append(self._call_realm("image_generation", "synthesize",
                                              intent_text, spec, psess, emit_fn,
                                              params={"frames": 4}))
            results.append(self._call_realm("audio_engine", "soundtrack",
                                              intent_text, spec, psess, emit_fn))
            results.append(self._call_realm("video_production", "assemble",
                                              intent_text, spec, psess, emit_fn))
            return results

        if kind == PIPELINE_GAME:
            results.append(self._call_realm("game_creation", "scaffold",
                                              intent_text, spec, psess, emit_fn))
            results.append(self._call_realm("simulation", "bootstrap_world",
                                              intent_text, spec, psess, emit_fn))
            results.append(self._call_realm("image_generation", "concept_art",
                                              intent_text, spec, psess, emit_fn,
                                              params={"frames": 2}))
            return results

        if kind == PIPELINE_ALBUM:
            for i in range(3):
                results.append(self._call_realm("audio_engine", "soundtrack",
                                                  intent_text, spec, psess, emit_fn,
                                                  params={"track_index": i}))
            return results

        if kind == PIPELINE_GALLERY:
            results.append(self._call_realm("image_generation", "synthesize",
                                              intent_text, spec, psess, emit_fn,
                                              params={"frames": 3}))
            return results

        if kind == PIPELINE_SIM:
            results.append(self._call_realm("simulation", "bootstrap_world",
                                              intent_text, spec, psess, emit_fn))
            results.append(self._call_realm("simulation", "terrain_map",
                                              intent_text, spec, psess, emit_fn))
            return results

        # Default: gallery
        return self._run_pipeline_kind(PIPELINE_GALLERY, intent_text, spec, psess, emit_fn)

    def _call_realm(self, realm_pkg: str, kind: str, intent_text: str,
                     spec, psess, emit_fn, params: Optional[dict] = None) -> dict:
        """BUILD-023: invoke a realm via WorkerRouter (single canonical
        path). No more direct import of realms/*.pipeline — every
        production call goes through worker → ArtifactValidator →
        ArtifactRegistry."""
        params = dict(params or {})
        params.setdefault("intent_text", intent_text)
        try:
            from engine.worker_router import get_worker_router
            from engine.workers.base_worker import WorkerRequest
            # realm_pkg → realm name (image_generation→image, audio_engine→audio,
            # video_production→video, game_creation→game, simulation→simulation)
            realm = _PIPELINE_PKG_TO_REALM.get(realm_pkg, realm_pkg)
            req = WorkerRequest(
                intent_text=intent_text or "",
                spec=spec,
                kind=kind,
                params=params,
            )
            t0 = time.time()
            outcome_obj = get_worker_router().route(realm, req)
            dur_ms = (time.time() - t0) * 1000.0
            state = getattr(outcome_obj, "state", "FAIL")
            artifacts = [a.get("path") for a in
                         (getattr(outcome_obj, "artifacts", []) or [])
                         if isinstance(a, dict) and a.get("path")]
            emit_fn(f"{realm}.{kind}", {
                "outcome": ("OK" if state == "READY" else state),
                "duration_ms": round(dur_ms, 1),
                "artifacts": artifacts,
                "workspace": getattr(outcome_obj, "workspace", ""),
            })
            return {
                "stage":   f"{realm}.{kind}",
                "outcome": ("OK" if state == "READY" else state),
                "backend": getattr(outcome_obj, "backend", "") or realm,
                "duration_ms": dur_ms,
                "result":  {
                    "outcome":   ("OK" if state == "READY" else state),
                    "artifacts": artifacts,
                    "error":     getattr(outcome_obj, "error", ""),
                    "remediation": getattr(outcome_obj, "remediation", ""),
                },
            }
        except Exception as e:
            return {"stage": f"{realm_pkg}.{kind}", "outcome": "FAIL",
                    "backend": realm_pkg, "error": str(e)}

    def _emit_receipt(self, run: PipelineRun, outcome: str) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"production_pipeline:{outcome}",
                executor="ProductionPipelineEngine",
                duration_ms=(time.time() - run.started_at) * 1000.0,
                verified=(run.state in ("DONE", "RUNNING")),
                compute_sha256=False,
                failure_reason=(run.error if run.state == "FAILED" else None),
                evidence=run.to_dict(),
            )
        except Exception:
            pass


# BUILD-023 — translate the legacy realms_pkg names used in
# _run_pipeline_kind to the canonical realm names that WorkerRouter
# understands.
_PIPELINE_PKG_TO_REALM = {
    "image_generation":  "image",
    "audio_engine":      "audio",
    "video_production":  "video",
    "game_creation":     "game",
    "simulation":        "simulation",
    "code_generation":   "code",
    "cast_ensemble":     "cast",
}


_INSTANCE: Optional[ProductionPipelineEngine] = None


def get_production_pipeline() -> ProductionPipelineEngine:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ProductionPipelineEngine()
    return _INSTANCE
