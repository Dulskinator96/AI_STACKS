"""engine/quality_gate.py — BUILD-022 QualityGate.

ReflectionEngine becomes QUALITY GATE ENFORCEMENT. Outputs scoring below
threshold AUTO-QUEUE refinement; reflection NEVER marks success without
validation.

This module sits between WorkerOutcome (from BaseWorker.execute) and any
downstream consumer that wants to know if the work is shippable.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

_log = logging.getLogger(__name__)


# Per-realm thresholds. Below these, refinement is auto-queued.
_REALM_THRESHOLDS = {
    "image":      0.60,
    "video":      0.60,
    "audio":      0.55,
    "game":       0.60,
    "simulation": 0.55,
    "code":       0.65,
    "cast":       0.55,
}

# Max refinement passes per intent (prevents runaway loops)
_MAX_REFINEMENT_PASSES = 2


@dataclass
class RefinementEntry:
    refine_id:        str
    worker_realm:     str
    intent_text:      str
    parent_artifact:  Optional[str]
    previous_score:   float
    pass_number:      int
    queued_at:        float
    state:            str = "QUEUED"      # QUEUED|DISPATCHED|DONE|ABANDONED


class QualityGate:
    """Enforce per-realm score thresholds + queue auto-refinement.

    The gate does NOT execute refinement itself — it queues entries and
    a separate consumer (the worker that produced the outcome, or a
    dedicated refinement pump) dispatches them.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._queue: deque[RefinementEntry] = deque()
        self._history: deque = deque(maxlen=200)
        self._stats = {"queued": 0, "dispatched": 0, "done": 0, "abandoned": 0}
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.quality_gate", self)
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────
    def threshold_for(self, realm: str) -> float:
        return _REALM_THRESHOLDS.get(realm, 0.55)

    def passes(self, outcome) -> bool:
        """Hard gate: True iff state==READY AND overall score >= threshold."""
        if getattr(outcome, "state", "") != "READY":
            return False
        score = float(getattr(outcome, "overall_validation_score", 0.0) or 0.0)
        return score >= self.threshold_for(getattr(outcome, "realm", ""))

    def should_refine(self, outcome) -> bool:
        """Whether a refinement pass should be queued. Yes iff worker
        completed (READY or DEGRADED), score < threshold, AND we haven't
        exceeded max passes."""
        state = getattr(outcome, "state", "")
        if state not in ("READY", "DEGRADED"):
            return False
        score = float(getattr(outcome, "overall_validation_score", 0.0) or 0.0)
        threshold = self.threshold_for(getattr(outcome, "realm", ""))
        if score >= threshold:
            return False
        if getattr(outcome, "refinement_pass", 0) >= _MAX_REFINEMENT_PASSES:
            return False
        return True

    def enqueue_refinement(self, outcome, request) -> bool:
        """Queue a refinement pass. Returns True if queued."""
        if not self.should_refine(outcome):
            return False
        # Pick the first valid artifact as parent (refinement is keyed off it)
        parent_path = None
        for a in (getattr(outcome, "artifacts", []) or []):
            if a.get("validation", {}).get("valid"):
                parent_path = a.get("path")
                break
        if parent_path is None:
            # No valid artifact — can't refine, mark abandoned
            with self._lock:
                self._stats["abandoned"] += 1
            return False
        entry = RefinementEntry(
            refine_id=f"refine-{uuid.uuid4().hex[:10]}",
            worker_realm=outcome.realm,
            intent_text=outcome.intent_text,
            parent_artifact=parent_path,
            previous_score=outcome.overall_validation_score,
            pass_number=outcome.refinement_pass + 1,
            queued_at=time.time(),
        )
        with self._lock:
            self._queue.append(entry)
            self._stats["queued"] += 1
        self._emit_receipt("queued", entry)

        # Async dispatch — pull the worker for the realm and re-run with
        # refinement_pass+1 + parent_artifact set.
        self._dispatch_async(entry, outcome, request)
        return True

    def _dispatch_async(self, entry: RefinementEntry, outcome, request) -> None:
        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
            from engine.workers import get_worker_for_realm
            from engine.workers.contracts import WorkerRequest
        except Exception as e:
            _log.debug("refinement dispatch wiring missing: %s", e)
            return

        worker = get_worker_for_realm(entry.worker_realm)
        if worker is None:
            with self._lock:
                self._stats["abandoned"] += 1
            entry.state = "ABANDONED"
            self._emit_receipt("abandoned", entry)
            return

        refined_request = WorkerRequest(
            intent_text=entry.intent_text,
            spec=getattr(request, "spec", None),
            kind=getattr(request, "kind", ""),
            params=dict(getattr(request, "params", {}) or {}),
            refinement_pass=entry.pass_number,
            parent_artifact=entry.parent_artifact,
        )

        def _do_refine():
            entry.state = "DISPATCHED"
            with self._lock:
                self._stats["dispatched"] += 1
            self._emit_receipt("dispatched", entry)
            r = worker.execute(refined_request)
            entry.state = "DONE"
            with self._lock:
                self._stats["done"] += 1
                self._history.append({
                    "refine_id":      entry.refine_id,
                    "realm":          entry.worker_realm,
                    "prev_score":     entry.previous_score,
                    "new_score":      getattr(r, "overall_validation_score", 0.0),
                    "new_state":      getattr(r, "state", ""),
                    "pass_number":    entry.pass_number,
                    "improved":       (getattr(r, "overall_validation_score", 0.0)
                                        > entry.previous_score),
                })
            self._emit_receipt("done", entry, refined_outcome=r)
            return r

        DeferredWorkspaceLoader.run(_do_refine, on_done=None,
                                     name=f"refine-{entry.refine_id}")

    # ── Query API ─────────────────────────────────────────────────────
    def stats(self) -> dict:
        with self._lock:
            return {
                **self._stats,
                "queue_depth": len(self._queue),
                "history_depth": len(self._history),
                "thresholds":  dict(_REALM_THRESHOLDS),
                "max_passes":  _MAX_REFINEMENT_PASSES,
            }

    def recent_history(self, n: int = 20) -> list:
        with self._lock:
            return list(self._history)[-n:]

    def _emit_receipt(self, outcome: str, entry: RefinementEntry,
                       refined_outcome=None) -> None:
        try:
            from truth.receipt_engine import record_execution
            evidence = {
                "refine_id":   entry.refine_id,
                "realm":       entry.worker_realm,
                "pass_number": entry.pass_number,
                "previous_score": entry.previous_score,
                "parent_artifact": entry.parent_artifact,
            }
            if refined_outcome is not None:
                evidence["new_score"] = getattr(refined_outcome, "overall_validation_score", 0.0)
                evidence["new_state"] = getattr(refined_outcome, "state", "")
            record_execution(
                task=f"quality_gate:refinement:{outcome}",
                executor="QualityGate",
                duration_ms=(time.time() - entry.queued_at) * 1000.0,
                verified=(outcome in ("queued", "dispatched", "done")),
                compute_sha256=False,
                evidence=evidence,
            )
        except Exception:
            pass


_INSTANCE: Optional[QualityGate] = None


def get_quality_gate() -> QualityGate:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = QualityGate()
    return _INSTANCE
