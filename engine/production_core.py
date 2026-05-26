"""engine/production_core.py — BUILD-021 SECTION 1: PRODUCTION CORE.

Central production execution authority. Sits BETWEEN MediaGenerationLayer
(queue-only) and the new realms/* pipelines (which produce real
artifacts). Responsibilities:
  · production session lifecycle
  · output directory allocation
  · refinement wave scheduling
  · resource budgeting (max concurrent generations per realm)
  · export orchestration (gather realm artifacts → output package)
  · artifact lineage emission

The realms/* pipelines call back through this core to write their
artifacts; the core wraps the call with provenance tracking and
receipts.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


@dataclass
class ProductionSession:
    session_id:        str
    intent_text:       str
    realm:             str
    started_at:        float
    state:             str = "INITIATED"   # INITIATED|RUNNING|REFINING|EXPORTED|FAILED
    output_dir:        str = ""
    artifacts:         list = field(default_factory=list)   # Artifact objects
    refinement_wave:   int = 0
    spec_snapshot:     dict = field(default_factory=dict)
    error:             str = ""

    def to_dict(self) -> dict:
        return {
            "session_id":       self.session_id,
            "intent_text":      self.intent_text[:200],
            "realm":            self.realm,
            "started_at":       self.started_at,
            "state":            self.state,
            "output_dir":       self.output_dir,
            "artifact_count":   len(self.artifacts),
            "refinement_wave":  self.refinement_wave,
            "error":            self.error,
        }


# Per-realm concurrency budget (Section 12 — never block UI; control
# resource pressure)
_REALM_BUDGET = {
    "image":      2,
    "video":      1,
    "audio":      2,
    "game":       1,
    "simulation": 2,
    "cast":       2,
    "code":       2,
}


class ProductionCore:
    """Central production execution authority."""

    def __init__(self):
        self._sessions: dict[str, ProductionSession] = {}
        self._in_flight_per_realm: dict[str, int] = {}
        self._lock = threading.RLock()
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.production_core", self)
        except Exception:
            pass
        # Build artifact_lineage eagerly so the registry has it before
        # any pipeline tries to register an artifact.
        try:
            from engine.artifact_lineage import get_artifact_lineage
            get_artifact_lineage()
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────
    def start_session(self, intent_text: str, realm: str,
                       spec_snapshot: Optional[dict] = None) -> ProductionSession:
        """Open a production session for a realm. Allocates an output
        directory. Realm-budgeted — if the realm already has its max in
        flight, returns the session in state=INITIATED but caller should
        check `can_run(session)` before dispatching."""
        sid = f"prod-{uuid.uuid4().hex[:10]}"
        from engine.artifact_lineage import get_artifact_lineage
        lineage = get_artifact_lineage()
        out_dir = str(lineage.output_dir(realm, sid))
        session = ProductionSession(
            session_id=sid, intent_text=intent_text or "",
            realm=realm or "misc",
            started_at=time.time(), output_dir=out_dir,
            spec_snapshot=dict(spec_snapshot or {}),
        )
        with self._lock:
            self._sessions[sid] = session
        self._emit_receipt("started", session)
        return session

    def can_run(self, session: ProductionSession) -> bool:
        """Check if the realm's budget permits another concurrent run."""
        budget = _REALM_BUDGET.get(session.realm, 2)
        with self._lock:
            current = self._in_flight_per_realm.get(session.realm, 0)
            return current < budget

    def claim(self, session: ProductionSession) -> bool:
        """Reserve a slot in the realm budget. Returns False if budget
        is exhausted (caller should defer)."""
        with self._lock:
            budget = _REALM_BUDGET.get(session.realm, 2)
            current = self._in_flight_per_realm.get(session.realm, 0)
            if current >= budget:
                return False
            self._in_flight_per_realm[session.realm] = current + 1
            session.state = "RUNNING"
        self._emit_receipt("running", session)
        return True

    def release(self, session: ProductionSession) -> None:
        with self._lock:
            current = self._in_flight_per_realm.get(session.realm, 0)
            self._in_flight_per_realm[session.realm] = max(0, current - 1)

    def register_artifact(self, session: ProductionSession,
                            path: str, backend: str) -> Any:
        """Register an artifact written by the realm pipeline. Returns
        the Artifact instance from ArtifactLineageTracker."""
        try:
            from engine.artifact_lineage import get_artifact_lineage
            art = get_artifact_lineage().register(
                path=path, realm=session.realm,
                session_id=session.session_id,
                intent_text=session.intent_text,
                backend=backend,
                spec_snapshot=session.spec_snapshot,
            )
            session.artifacts.append(art)
            return art
        except Exception as e:
            _log.warning("register_artifact failed: %s", e)
            return None

    def schedule_refinement(self, session: ProductionSession,
                              passes: int = 1) -> None:
        """Mark a session for refinement wave. Caller's pipeline picks
        this up and re-runs with refined parameters."""
        with self._lock:
            session.refinement_wave += passes
            session.state = "REFINING"
        self._emit_receipt("refining", session)

    def export(self, session: ProductionSession) -> dict:
        """Package the session's artifacts into a manifest. Writes
        manifest.json to the output directory. Returns the manifest."""
        manifest = {
            "session_id":     session.session_id,
            "intent_text":    session.intent_text,
            "realm":          session.realm,
            "spec_snapshot":  session.spec_snapshot,
            "artifacts":      [a.to_dict() if hasattr(a, "to_dict") else a
                                for a in session.artifacts],
            "refinement_wave": session.refinement_wave,
            "exported_at":    time.time(),
        }
        try:
            import json
            manifest_path = Path(session.output_dir) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2),
                                      encoding="utf-8")
        except Exception as e:
            _log.warning("manifest write failed: %s", e)
        session.state = "EXPORTED"
        self._emit_receipt("exported", session)
        return manifest

    def fail(self, session: ProductionSession, error: str) -> None:
        session.state = "FAILED"
        session.error = error
        self.release(session)
        self._emit_receipt("failed", session)

    # ── Query API ─────────────────────────────────────────────────────
    def get_session(self, sid: str) -> Optional[ProductionSession]:
        with self._lock:
            return self._sessions.get(sid)

    def stats(self) -> dict:
        with self._lock:
            return {
                "total_sessions":    len(self._sessions),
                "in_flight_per_realm": dict(self._in_flight_per_realm),
                "budgets":            dict(_REALM_BUDGET),
            }

    def _emit_receipt(self, outcome: str, session: ProductionSession) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"production:session:{outcome}",
                executor="ProductionCore",
                duration_ms=(time.time() - session.started_at) * 1000.0,
                verified=(outcome in ("started", "running", "exported")),
                compute_sha256=False,
                failure_reason=(session.error if outcome == "failed" else None),
                evidence=session.to_dict(),
            )
        except Exception:
            pass


_INSTANCE: Optional[ProductionCore] = None


def get_production_core() -> ProductionCore:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ProductionCore()
    return _INSTANCE
