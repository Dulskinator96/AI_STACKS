"""engine/worker_router.py — BUILD-023 single dispatch entity.

The canonical pipeline becomes:

    IntentCortex
       ↓
    CognitiveCore
       ↓
    WorkerRouter   ← (this module — gate + select + dispatch)
       ↓
    WorkerExecution   (BaseWorker.execute — the 9-step contract)
       ↓
    ArtifactValidator (consolidated validation)
       ↓
    ArtifactRegistry  (lineage)
       ↓
    PreviewWall       (preview registry)

NO PARALLEL SIMULATION PATHS. Every production-realm dispatch goes
through `route(realm, request)` — no caller may import realm pipelines
directly. The router consults ToolFabric BEFORE invoking the worker;
if no backend is available AND no fallback exists, returns FAIL with
remediation.

This module replaces all of:
  · RealmDispatcher._try_realm_pipeline   (deprecated in build-023)
  · RealmDispatcher legacy per-backend handlers (deprecated in build-023)
  · ProductionPipelineEngine._call_realm direct realm imports (rewired)
  · MediaGenerationLayer._dispatch_job direct engine.process_intent
    (rewired through WorkerRouter)
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


def _has_real_artifact(worker_outcome) -> bool:
    """REALITY LAW: a real artifact is a file that EXISTS on disk with
    size > 0 and passed validation. No state string is trusted."""
    for a in (getattr(worker_outcome, "artifacts", []) or []):
        if not isinstance(a, dict):
            continue
        p = a.get("path", "")
        if p and os.path.isfile(p) and os.path.getsize(p) > 0 \
                and a.get("validation", {}).get("valid"):
            return True
    return False


# Fallback rules: when a realm's preferred backend is unavailable but
# we still have a way to produce a real artifact in the same family.
# Audio→audio (procedural numpy is always available); others FAIL hard.
_FALLBACK_REALM = {
    # No explicit cross-realm fallbacks. Audio worker handles its own
    # internal fallback chain (Bark → pyttsx3 → procedural) inside the
    # audio realm pipeline.
}


@dataclass
class RouteDecision:
    realm:           str
    decision:        str             # DISPATCH | FAIL_NO_BACKEND | FAIL_NO_WORKER
    fallback_realm:  Optional[str] = None
    available_backends: list = field(default_factory=list)
    missing_backends:   list = field(default_factory=list)
    remediation:     str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class WorkerRouter:
    """Single dispatch entity. Gates via ToolFabric, selects worker."""

    def __init__(self):
        self._route_count = 0
        self._dispatch_count = 0
        self._fail_count = 0
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.worker_router", self)
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────
    def decide(self, realm: str) -> RouteDecision:
        """Pre-flight decision: can we dispatch this realm? Consults
        ToolFabric for backend availability."""
        realm = (realm or "").lower()
        self._route_count += 1
        try:
            from runtime.singleton_registry import get_registry
            tf = get_registry().get("engine.tool_fabric")
        except Exception:
            tf = None

        if tf is None:
            return RouteDecision(realm=realm, decision="DISPATCH",
                                  remediation="ToolFabric unavailable — proceeding optimistically")

        # Per-realm: at least one canonical backend must be READY/DEGRADED.
        # The fallback chain inside each worker handles internal sub-backend
        # selection; the router only enforces the realm-level gate.
        gate = self._realm_gate(realm, tf)
        decision = self._evaluate_gate(realm, gate)
        return decision

    def route(self, realm: str, request) -> Any:
        """Single canonical dispatch entry. Runs the worker, then records
        the outcome into the MemPalace ledger (AFTER execution only). The
        ledger stores an EXECUTION/ARTIFACT entry ONLY when a real validated
        file exists — failures/unavailable record an INTENT row but no
        phantom execution."""
        outcome = self._route_impl(realm, request)
        self._record_to_mem_palace(realm, request, outcome)
        return outcome

    def _record_to_mem_palace(self, realm: str, request, outcome) -> None:
        """REALITY BINDING: persist to MemPalace after execution. Never
        breaks the execution path; stashes execution_id on the outcome so
        post-hoc metrics (CQI) can attach to a real entry."""
        try:
            from engine.mem_palace.memory_store import get_mem_palace
            intent_text = getattr(request, "intent_text", "") or ""
            result = get_mem_palace().record_execution(intent_text, realm, outcome)
            try:
                outcome._mem_execution_id = result.get("execution_id")
            except Exception:
                pass
        except Exception:
            pass

    def _route_impl(self, realm: str, request) -> Any:
        """Worker selection + gate + dispatch. Returns the WorkerOutcome
        (or a synthetic FAIL outcome when gate fails)."""
        from engine.workers import get_worker_for_realm
        from engine.workers.base_worker import WorkerOutcome
        import uuid

        worker = get_worker_for_realm(realm)
        if worker is None:
            self._fail_count += 1
            self._emit_receipt("fail_no_worker", realm, None)
            return self._synthetic_fail(realm, request,
                error=f"no worker registered for realm '{realm}'",
                remediation="add a worker class in engine/workers/")

        # Gate: check tool availability BEFORE invoking the worker.
        decision = self.decide(realm)
        self._emit_receipt(decision.decision.lower(), realm, decision)

        if decision.decision == "FAIL_NO_BACKEND":
            # If a fallback realm exists, redirect; otherwise FAIL.
            if decision.fallback_realm:
                fb_worker = get_worker_for_realm(decision.fallback_realm)
                if fb_worker is not None:
                    _log.info("router: %s unavailable → falling back to %s",
                               realm, decision.fallback_realm)
                    self._dispatch_count += 1
                    return fb_worker.execute(request)
            self._fail_count += 1
            return self._synthetic_fail(realm, request,
                error=f"UNAVAILABLE_REAL_EXECUTION: no backend for realm "
                       f"'{realm}': {decision.missing_backends}",
                remediation=decision.remediation)

        # DISPATCH — invoke the worker THROUGH the Production Guarantee
        # Engine. The engine compiles a contract, runs the worker,
        # scores against the contract, and auto-repairs on sub-threshold.
        self._dispatch_count += 1
        try:
            from engine.production_guarantee import get_production_guarantee
            guarantee = get_production_guarantee()
            g_outcome = guarantee.guarantee(realm, request,
                                              worker_fn=lambda: worker.execute(request))
            # Return the underlying worker outcome (for back-compat with
            # callers that expect a WorkerOutcome shape). The guarantee
            # outcome is recorded in receipts + emitted on the live bus.
            if g_outcome.worker_outcome is not None:
                wo = g_outcome.worker_outcome
                # Annotate with guarantee verdict as POST-HOC metadata only.
                try:
                    wo._guarantee_status = g_outcome.status
                    wo._guarantee_score = g_outcome.match_score
                except Exception:
                    pass
                # REALITY LAW §3: the guarantee may NOT replace execution.
                # If a REAL validated artifact exists on disk, the worker's
                # READY/DEGRADED state STANDS regardless of MatchScore — the
                # score is metadata. The guarantee may only downgrade to FAIL
                # when NO real file was produced.
                if g_outcome.status == "FAIL" and not _has_real_artifact(wo):
                    wo.state = "FAIL"
                    wo.error = wo.error or g_outcome.remediation
                return wo
            # REJECTED with no worker outcome should no longer occur for a
            # routable realm (compiler fails OPEN via realm_hint). If it does,
            # the realm is genuinely unroutable → declare it explicitly and
            # still attempt a direct worker dispatch before giving up.
            try:
                return worker.execute(request)
            except Exception:
                return self._synthetic_fail(realm, request,
                    error=f"UNAVAILABLE_REAL_EXECUTION: {g_outcome.diagnostics.get('reason','')}",
                    remediation=g_outcome.remediation)
        except Exception as e:
            _log.exception("guarantee layer failed: %s", e)
            # Fall back to direct worker invocation rather than total failure
            return worker.execute(request)

    def route_async(self, realm: str, request,
                     on_done: Optional[Callable] = None) -> None:
        """Async variant — submits to DeferredWorkspaceLoader."""
        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
            DeferredWorkspaceLoader.run(
                lambda: self.route(realm, request),
                on_done=on_done, name=f"router-{realm}",
            )
        except Exception as e:
            outcome = self._synthetic_fail(realm, request,
                error=f"deferred loader missing: {e}",
                remediation="ensure runtime/deferred_loader present")
            if on_done:
                on_done(outcome)

    def stats(self) -> dict:
        return {
            "route_count":    self._route_count,
            "dispatch_count": self._dispatch_count,
            "fail_count":     self._fail_count,
        }

    # ── Gate logic ────────────────────────────────────────────────────
    def _realm_gate(self, realm: str, tf) -> dict:
        """Query ToolFabric for realm backend availability. Returns
        {ready: [tool_names], missing: [tool_names]}."""
        relevant = tf.tools_for_realm(realm)
        ready: list[str] = []
        missing: list[str] = []
        for t in relevant:
            st = tf.status(t)
            if st == "READY":
                ready.append(t)
            elif st in ("UNAVAILABLE", "FAILED", "LIMITED"):
                missing.append(t)
            else:
                # DEGRADED counts as conditionally usable
                ready.append(t)
        return {"realm": realm, "ready": ready, "missing": missing,
                "relevant": relevant}

    def _evaluate_gate(self, realm: str, gate: dict) -> RouteDecision:
        relevant = gate.get("relevant", [])
        ready    = gate.get("ready", [])
        missing  = gate.get("missing", [])
        decision = RouteDecision(
            realm=realm,
            decision="DISPATCH",
            available_backends=list(ready),
            missing_backends=list(missing),
        )
        # Audio realm has procedural numpy fallback inside the worker —
        # so even if no listed backend is READY, we can still dispatch
        # (the worker will pick procedural).
        if realm == "audio":
            decision.remediation = (
                "" if ready else
                "no listed audio backend ready — procedural numpy fallback "
                "will be used inside the worker"
            )
            return decision
        # Code realm: conv_programming is internal and always present —
        # always dispatch and let the worker decide.
        if realm in ("code", "simulation", "game"):
            return decision
        # Cast realm: pyramid_ensemble is internal.
        if realm == "cast":
            return decision
        # Image / Video realms: need at least one external backend ready.
        if not ready:
            decision.decision = "FAIL_NO_BACKEND"
            decision.fallback_realm = _FALLBACK_REALM.get(realm)
            decision.remediation = self._remediation_for(realm, missing)
        return decision

    def _remediation_for(self, realm: str, missing: list) -> str:
        if realm == "image":
            return ("start ComfyUI (port 8188) OR Automatic1111 (port 7860) "
                    "OR `pip install diffusers torch` with a local SD model")
        if realm == "video":
            return ("install ffmpeg and add to PATH "
                    "(ffmpeg is required for video assembly)")
        return f"install one of: {missing}"

    # ── Helpers ──────────────────────────────────────────────────────
    def _synthetic_fail(self, realm: str, request, error: str, remediation: str):
        from engine.workers.base_worker import WorkerOutcome
        import uuid
        t = time.time()
        return WorkerOutcome(
            worker_id=f"router-fail-{uuid.uuid4().hex[:6]}",
            worker_name="WorkerRouter",
            realm=realm,
            state="FAIL",
            intent_text=getattr(request, "intent_text", "") or "",
            started_at=t,
            finished_at=t,
            duration_ms=0.0,
            workspace="",
            manifest_path=None,
            error=error,
            remediation=remediation,
        )

    def _emit_receipt(self, outcome: str, realm: str,
                      decision: Optional[RouteDecision]) -> None:
        try:
            from truth.receipt_engine import record_execution
            evidence: dict = {"realm": realm}
            if decision is not None:
                evidence.update(decision.to_dict())
            record_execution(
                task=f"worker_router:{outcome}",
                executor="WorkerRouter",
                duration_ms=0.0,
                verified=(outcome in ("dispatch",)),
                compute_sha256=False,
                evidence=evidence,
            )
        except Exception:
            pass


_INSTANCE: Optional[WorkerRouter] = None


def get_worker_router() -> WorkerRouter:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = WorkerRouter()
    return _INSTANCE
