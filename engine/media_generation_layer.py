"""engine/media_generation_layer.py — BUILD-020 SECTION 8.

Unified generation coordination. Queue + batch + refinement loops over
the RealmOrchestrator. Tracks:
  · pending generation jobs
  · in-flight jobs (by realm)
  · completed artifacts
  · refinement passes per artifact

Capabilities exposed:
  · enqueue(job) — adds to queue
  · run_next() — pops + dispatches
  · refine(artifact, pass_kind) — submits a refinement pass
  · status() — current queue snapshot

This layer is deliberately ADDITIVE — RealmOrchestrator does the actual
dispatch; MediaGenerationLayer adds queueing + refinement coordination
on top.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


@dataclass
class GenerationJob:
    job_id:        str
    realm:         str
    intent_text:   str
    spec:          Any = None
    graph:         Any = None
    state:         str = "QUEUED"   # QUEUED|RUNNING|REFINING|DONE|FAILED
    enqueued_at:   float = 0.0
    started_at:    float = 0.0
    completed_at:  float = 0.0
    artifacts:     list = field(default_factory=list)
    refinement_passes: int = 0
    overall_score: float = 0.0
    error:         str = ""

    def to_dict(self) -> dict:
        return {
            "job_id":           self.job_id,
            "realm":            self.realm,
            "intent_text":      self.intent_text[:200],
            "state":            self.state,
            "enqueued_at":      self.enqueued_at,
            "started_at":       self.started_at,
            "completed_at":     self.completed_at,
            "artifact_count":   len(self.artifacts),
            "refinement_passes": self.refinement_passes,
            "overall_score":    self.overall_score,
            "error":            self.error,
        }


class MediaGenerationLayer:
    """Generation queue + refinement coordinator."""

    def __init__(self, max_in_flight: int = 2):
        self._queue: deque[GenerationJob] = deque()
        self._in_flight: dict[str, GenerationJob] = {}
        self._completed: deque[GenerationJob] = deque(maxlen=100)
        self._lock = threading.RLock()
        self._max_in_flight = int(max_in_flight)
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.media_generation", self)
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────
    def enqueue(self, intent_text: str, realm: str = "",
                 spec: Any = None, graph: Any = None) -> GenerationJob:
        """Add a job to the queue. Returns the job (state=QUEUED)."""
        job = GenerationJob(
            job_id=f"gen-{uuid.uuid4().hex[:10]}",
            realm=realm or "cast",
            intent_text=intent_text or "",
            spec=spec, graph=graph,
            enqueued_at=time.time(),
        )
        with self._lock:
            self._queue.append(job)
        self._emit_receipt("enqueued", job)
        self._maybe_dispatch()
        return job

    def _maybe_dispatch(self) -> None:
        with self._lock:
            if len(self._in_flight) >= self._max_in_flight:
                return
            if not self._queue:
                return
            job = self._queue.popleft()
            self._in_flight[job.job_id] = job
        self._dispatch_job(job)

    def _dispatch_job(self, job: GenerationJob) -> None:
        job.state = "RUNNING"
        job.started_at = time.time()
        self._emit_receipt("running", job)
        try:
            from runtime.singleton_registry import get_registry
            from runtime.deferred_loader import DeferredWorkspaceLoader
            engine = get_registry().get("engine.pyramid")
            if engine is None:
                raise RuntimeError("PyramidEngine singleton not present")
        except Exception as e:
            job.state = "FAILED"
            job.error = str(e)
            self._complete(job)
            return

        def _on_complete(session):
            try:
                if session.state == "DONE":
                    job.spec = session.spec
                    job.graph = session.graph
                    job.overall_score = (session.reflection.overall_score
                                         if session.reflection is not None else 0.0)
                    # Collect any artifact paths from dispatch results
                    for r in session.dispatch_results or []:
                        payload = getattr(r, "payload", None)
                        if isinstance(payload, str) and ("/" in payload or "\\" in payload):
                            job.artifacts.append(payload)
                    # Decide refinement: auto-refine if overall < 0.55 and we
                    # haven't already refined this job
                    if job.overall_score < 0.55 and job.refinement_passes == 0:
                        self._refine_in_place(job)
                    else:
                        job.state = "DONE"
                        self._complete(job)
                else:
                    job.state = "FAILED"
                    job.error = session.error or "engine FAILED"
                    self._complete(job)
            except Exception as e:
                job.state = "FAILED"
                job.error = str(e)
                self._complete(job)

        engine.process_intent(job.intent_text, on_complete=_on_complete)

    def _refine_in_place(self, job: GenerationJob) -> None:
        """Submit a refinement pass on a low-scoring job. Reuses the
        engine with the same intent — for v1 this is just a re-roll
        with a tagged intent. Future builds can apply targeted refinement
        recipes (sharpen color, add cinematic palette, etc)."""
        job.refinement_passes += 1
        job.state = "REFINING"
        self._emit_receipt("refining", job)
        try:
            from runtime.singleton_registry import get_registry
            engine = get_registry().get("engine.pyramid")
            if engine is None:
                raise RuntimeError("PyramidEngine missing")
            refined_intent = f"[refine pass {job.refinement_passes}] {job.intent_text}"

            def _on_refined(session):
                try:
                    new_score = (session.reflection.overall_score
                                 if session.reflection is not None else 0.0)
                    if new_score > job.overall_score:
                        job.overall_score = new_score
                        job.spec = session.spec
                        job.graph = session.graph
                    job.state = "DONE"
                    self._complete(job)
                except Exception as e:
                    job.state = "FAILED"
                    job.error = str(e)
                    self._complete(job)

            engine.process_intent(refined_intent, on_complete=_on_refined)
        except Exception as e:
            job.state = "FAILED"
            job.error = str(e)
            self._complete(job)

    def _complete(self, job: GenerationJob) -> None:
        job.completed_at = time.time()
        with self._lock:
            self._in_flight.pop(job.job_id, None)
            self._completed.append(job)
        self._emit_receipt(job.state.lower(), job)
        # Dispatch next from queue
        self._maybe_dispatch()

    # ── Query API ─────────────────────────────────────────────────────
    def status(self) -> dict:
        with self._lock:
            return {
                "queued":      len(self._queue),
                "in_flight":   len(self._in_flight),
                "completed":   len(self._completed),
                "max_in_flight": self._max_in_flight,
                "in_flight_ids": list(self._in_flight.keys()),
            }

    def recent_completed(self, n: int = 10) -> list:
        with self._lock:
            return [j.to_dict() for j in list(self._completed)[-n:]]

    def _emit_receipt(self, outcome: str, job: GenerationJob) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"media_generation:{outcome}",
                executor="MediaGenerationLayer",
                duration_ms=(time.time() - job.enqueued_at) * 1000.0,
                verified=(outcome in ("done", "running")),
                compute_sha256=False,
                failure_reason=(job.error if outcome == "failed" else None),
                evidence=job.to_dict(),
            )
        except Exception:
            pass


_INSTANCE: Optional[MediaGenerationLayer] = None


def get_media_generation_layer() -> MediaGenerationLayer:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = MediaGenerationLayer()
    return _INSTANCE
