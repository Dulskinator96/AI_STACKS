"""engine/artifact_lineage.py — BUILD-021 SECTION 1 (substrate).

Track every artifact written to disk. Each artifact carries:
  · artifact_id (uuid)
  · path (real file on disk)
  · realm (image|audio|video|game|simulation|cast|code)
  · session_id (production session that wrote it)
  · intent_text (originating operator intent)
  · spec_snapshot (subset of ExpandedSpec at write time)
  · backend (which tool actually produced it)
  · sha256 (computed at registration)
  · size_bytes
  · created_at

Persisted to `telemetry/artifact_lineage.jsonl` (append-only). Queryable
via session_id, realm, sha256, or recent-window.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


def _telemetry_dir() -> Path:
    """Persistent telemetry dir next to the .exe (frozen) or project root
    (dev). NEVER _MEIPASS — artifacts must survive process exit, otherwise the
    MemPalace ledger records paths that vaporize when the temp bundle is
    purged. Mirrors engine/mem_palace/memory_store.py."""
    try:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            base = Path(__file__).resolve().parent.parent
        d = base / "telemetry"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return Path.home() / ".stratum" / "telemetry"


_TELEMETRY = _telemetry_dir()
_LINEAGE_PATH = _TELEMETRY / "artifact_lineage.jsonl"
_OUTPUTS_ROOT = _TELEMETRY / "outputs"


@dataclass(frozen=True)
class Artifact:
    artifact_id:   str
    path:          str
    realm:         str
    session_id:    str
    intent_text:   str
    backend:       str
    sha256:        Optional[str]
    size_bytes:    int
    created_at:    float
    spec_snapshot: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class ArtifactLineageTracker:
    """Provenance tracker for every artifact the production system writes."""

    def __init__(self):
        self._lock = threading.RLock()
        self._recent: list[Artifact] = []   # in-memory tail
        self._recent_cap = 200
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.artifact_lineage", self)
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────
    def output_dir(self, realm: str, session_id: str) -> Path:
        """Return the canonical directory for a realm/session's artifacts.
        Creates it on demand."""
        d = _OUTPUTS_ROOT / (realm or "misc") / (session_id or "default")
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            _log.warning("output_dir create failed: %s", e)
        return d

    def register(self, *, path: str, realm: str, session_id: str,
                  intent_text: str, backend: str,
                  spec_snapshot: Optional[dict] = None) -> Artifact:
        """Register an artifact AFTER it has been written. Computes
        sha256 + size. Persists to lineage log."""
        p = Path(path)
        sha = None
        size = 0
        try:
            if p.is_file():
                size = p.stat().st_size
                sha = self._sha256(p)
        except Exception as e:
            _log.debug("artifact stat/sha failed: %s", e)

        artifact = Artifact(
            artifact_id=f"art-{uuid.uuid4().hex[:10]}",
            path=str(p),
            realm=realm or "misc",
            session_id=session_id or "default",
            intent_text=(intent_text or "")[:240],
            backend=backend or "unknown",
            sha256=sha,
            size_bytes=int(size),
            created_at=time.time(),
            spec_snapshot=dict(spec_snapshot or {}),
        )
        with self._lock:
            self._recent.append(artifact)
            if len(self._recent) > self._recent_cap:
                del self._recent[:len(self._recent) - self._recent_cap]
        self._persist(artifact)
        self._emit_receipt(artifact)
        return artifact

    def recent(self, n: int = 20, realm: Optional[str] = None) -> list[Artifact]:
        with self._lock:
            items = list(self._recent)
        if realm:
            items = [a for a in items if a.realm == realm]
        return items[-n:]

    def for_session(self, session_id: str) -> list[Artifact]:
        with self._lock:
            return [a for a in self._recent if a.session_id == session_id]

    def stats(self) -> dict:
        with self._lock:
            counts: dict[str, int] = {}
            total_bytes = 0
            for a in self._recent:
                counts[a.realm] = counts.get(a.realm, 0) + 1
                total_bytes += a.size_bytes
            return {
                "recent_count": len(self._recent),
                "per_realm":    counts,
                "total_bytes":  total_bytes,
                "lineage_path": str(_LINEAGE_PATH),
            }

    # ── Internals ──────────────────────────────────────────────────────
    def _sha256(self, p: Path) -> Optional[str]:
        try:
            h = hashlib.sha256()
            with p.open("rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    def _persist(self, a: Artifact) -> None:
        try:
            _LINEAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _LINEAGE_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(a.to_dict()) + "\n")
        except Exception as e:
            _log.warning("lineage persist failed: %s", e)

    def _emit_receipt(self, a: Artifact) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"artifact:registered:{a.realm}",
                executor="ArtifactLineageTracker",
                artifact=a.path,
                duration_ms=0.0,
                verified=(a.sha256 is not None),
                compute_sha256=False,    # already computed
                evidence={
                    "artifact_id": a.artifact_id,
                    "realm":       a.realm,
                    "session_id":  a.session_id,
                    "backend":     a.backend,
                    "sha256":      a.sha256,
                    "size_bytes":  a.size_bytes,
                    "intent_text": a.intent_text[:120],
                },
            )
        except Exception:
            pass


_INSTANCE: Optional[ArtifactLineageTracker] = None


def get_artifact_lineage() -> ArtifactLineageTracker:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ArtifactLineageTracker()
    return _INSTANCE
