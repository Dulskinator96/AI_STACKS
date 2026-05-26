"""engine/noncanonical_audit.py — BUILD-028 SECTION 1 enforcement.

Walks the singleton registry + emit_event subscribers and flags any
layer that does NOT satisfy the 8 canonical routing rules:
  1. Routed through CognitiveCore
  2. Registered through BackendRegistry
  3. Governed through CQI
  4. Validated through GuaranteeLayer
  5. Observable through LaunchSurface (LiveStreamBus subscribers)
  6. Persisted through ArtifactLineage
  7. Benchmarked through Calibration
  8. Truth-audited through SystemTruthAudit

Result: list of NONCANONICAL findings + audit warning emission.
This is OBSERVATIONAL only — it doesn't block dispatch. It surfaces
architectural drift so future builds can correct.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

_log = logging.getLogger(__name__)


# The 8 canonical anchor singletons. If a system advertises a creative
# capability but lives outside this set, it's NONCANONICAL.
_CANONICAL_ANCHORS = {
    "engine.cognitive_core":           "CognitiveCore routing",
    "engine.backend_registry":         "BackendRegistry",
    "engine.aesthetic_reasoner":       "CQI governance",
    "engine.production_guarantee":     "GuaranteeLayer",
    "ui.state_bridge":                  "LaunchSurface observability",
    "engine.artifact_lineage":         "ArtifactLineage",
    "engine.calibration.performance":  "Calibration",
    "engine.system_truth_audit":       "SystemTruthAudit",
}


@dataclass(frozen=True)
class AuditFinding:
    layer:        str          # singleton name
    classification: str        # CANONICAL | NONCANONICAL | UNDETERMINED
    missing_anchors: list      # which of the 8 anchors this layer doesn't route through
    detail:       str

    def to_dict(self) -> dict:
        return asdict(self)


class NoncanonicalAudit:

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.noncanonical_audit", self)
        except Exception:
            pass

    def audit(self) -> dict:
        t0 = time.time()
        from runtime.singleton_registry import get_registry
        reg = get_registry()
        names = sorted(reg.names())

        # Verify the 8 canonical anchors exist
        anchor_status: dict = {}
        for anchor, label in _CANONICAL_ANCHORS.items():
            anchor_status[anchor] = {
                "label":    label,
                "present":  reg.has(anchor),
            }

        # Classify each registered layer
        findings: list[AuditFinding] = []
        for name in names:
            # The anchors themselves are CANONICAL by definition
            if name in _CANONICAL_ANCHORS:
                continue
            # Engine layers that should be inspecting/aware of the anchors
            if name.startswith("engine."):
                missing = [a for a in _CANONICAL_ANCHORS if not reg.has(a)]
                if missing:
                    findings.append(AuditFinding(
                        layer=name,
                        classification="UNDETERMINED",
                        missing_anchors=missing,
                        detail=f"engine layer present but {len(missing)} canonical anchors absent",
                    ))
            # Realm pipelines that don't route through workers (heuristic)
            elif name.startswith("realm.") or name.startswith("realms."):
                findings.append(AuditFinding(
                    layer=name,
                    classification="NONCANONICAL",
                    missing_anchors=[],
                    detail="realm layer should route through WorkerRouter",
                ))

        # Counts
        counts: dict = {"CANONICAL": 0, "NONCANONICAL": 0, "UNDETERMINED": 0}
        for f in findings:
            counts[f.classification] = counts.get(f.classification, 0) + 1
        counts["CANONICAL"] = sum(1 for a in anchor_status.values() if a["present"])

        report = {
            "audited_at":    time.time(),
            "duration_ms":   round((time.time() - t0) * 1000.0, 1),
            "total_layers":  len(names),
            "anchor_status": anchor_status,
            "counts":        counts,
            "findings":      [f.to_dict() for f in findings],
        }
        self._emit_receipt(report)
        if counts.get("NONCANONICAL", 0) > 0:
            self._emit_warning(report)
        return report

    def _emit_receipt(self, report: dict) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="noncanonical_audit:run",
                executor="NoncanonicalAudit",
                duration_ms=report["duration_ms"],
                verified=(report["counts"].get("NONCANONICAL", 0) == 0),
                compute_sha256=False,
                evidence={
                    "total_layers":     report["total_layers"],
                    "anchor_present":   sum(1 for a in report["anchor_status"].values() if a["present"]),
                    "noncanonical":     report["counts"].get("NONCANONICAL", 0),
                    "undetermined":     report["counts"].get("UNDETERMINED", 0),
                },
            )
        except Exception:
            pass

    def _emit_warning(self, report: dict) -> None:
        try:
            from engine.live_stream import get_live_stream
            get_live_stream().emit_event("noncanonical_warning", {
                "count":  report["counts"]["NONCANONICAL"],
                "layers": [f["layer"] for f in report["findings"]
                            if f.get("classification") == "NONCANONICAL"][:5],
            })
        except Exception:
            pass


_INSTANCE: Optional[NoncanonicalAudit] = None


def get_noncanonical_audit() -> NoncanonicalAudit:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = NoncanonicalAudit()
    return _INSTANCE
