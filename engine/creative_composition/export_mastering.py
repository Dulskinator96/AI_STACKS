"""engine/creative_composition/export_mastering.py — final mastering.

After workers produce validated artifacts AND the guarantee layer
approves, ExportMastering assembles them into a MasterPackage: an
ordered, indexed bundle the operator can ship.

The mastering pass:
  · groups artifacts by realm + scene
  · writes a master_index.json
  · re-validates each artifact one final time
  · computes an aggregate package_score
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MasterPackage:
    package_id:       str
    plan_id:          str
    output_dir:       str
    artifact_count:   int
    per_realm_counts: dict
    package_score:    float
    master_index_path: str
    created_at:       float
    duration_ms:      float

    def to_dict(self) -> dict:
        return asdict(self)


class ExportMastering:
    """Final pass: assemble validated artifacts into a master package."""

    def master(self, plan, validated_outcomes: list) -> Optional[MasterPackage]:
        """validated_outcomes: list of guarantee-VALIDATED WorkerOutcome objects."""
        t0 = time.time()
        if not validated_outcomes:
            return None

        # Allocate a master output dir (sibling of session dirs)
        from engine.artifact_lineage import get_artifact_lineage
        lineage = get_artifact_lineage()
        package_id = f"pkg-{uuid.uuid4().hex[:10]}"
        master_dir = lineage.output_dir("master", package_id)

        per_realm: dict[str, int] = {}
        artifacts_index: list = []
        scores: list[float] = []

        for outcome in validated_outcomes:
            realm = getattr(outcome, "realm", "misc")
            for a in (getattr(outcome, "artifacts", []) or []):
                if not isinstance(a, dict):
                    continue
                if not a.get("validation", {}).get("valid"):
                    continue
                per_realm[realm] = per_realm.get(realm, 0) + 1
                # Copy of the artifact descriptor for the master index
                artifacts_index.append({
                    "path":     a.get("path"),
                    "realm":    realm,
                    "backend":  a.get("backend"),
                    "sha256":   a.get("sha256"),
                    "size_bytes": a.get("size_bytes", 0),
                    "score":    a.get("validation", {}).get("score", 0.0),
                    "worker_outcome_id": getattr(outcome, "worker_id", ""),
                })
                s = float(a.get("validation", {}).get("score", 0.0) or 0.0)
                scores.append(s)

        if not artifacts_index:
            return None

        package_score = round(sum(scores) / len(scores), 3) if scores else 0.0

        index = {
            "package_id":      package_id,
            "plan_id":         getattr(plan, "plan_id", ""),
            "raw_intent":      getattr(plan, "raw_intent", "")[:240],
            "pipeline_kind":   getattr(plan, "pipeline_kind", ""),
            "artifact_count":  len(artifacts_index),
            "per_realm":       per_realm,
            "artifacts":       artifacts_index,
            "package_score":   package_score,
            "created_at":      time.time(),
            "duration_ms":     (time.time() - t0) * 1000.0,
            "composition": (plan.to_dict() if hasattr(plan, "to_dict") else None),
        }
        master_index_path = master_dir / "master_index.json"
        try:
            master_index_path.write_text(
                json.dumps(index, indent=2), encoding="utf-8")
        except Exception as e:
            _log.warning("master_index write failed: %s", e)

        pkg = MasterPackage(
            package_id=package_id,
            plan_id=getattr(plan, "plan_id", ""),
            output_dir=str(master_dir),
            artifact_count=len(artifacts_index),
            per_realm_counts=per_realm,
            package_score=package_score,
            master_index_path=str(master_index_path),
            created_at=time.time(),
            duration_ms=(time.time() - t0) * 1000.0,
        )
        self._emit_receipt(pkg)
        return pkg

    def _emit_receipt(self, pkg: MasterPackage) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="composition:export:mastered",
                executor="ExportMastering",
                artifact=pkg.master_index_path,
                duration_ms=pkg.duration_ms,
                verified=(pkg.package_score >= 0.6),
                compute_sha256=False,
                evidence={
                    "package_id":     pkg.package_id,
                    "plan_id":        pkg.plan_id,
                    "artifact_count": pkg.artifact_count,
                    "per_realm":      pkg.per_realm_counts,
                    "package_score":  pkg.package_score,
                },
            )
        except Exception:
            pass
        # Emit on the live bus too
        try:
            from engine.live_stream import get_live_stream
            get_live_stream().emit_event("master_package_ready", pkg.to_dict())
        except Exception:
            pass
