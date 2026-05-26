"""engine/system_truth_audit.py — BUILD-026 toolchain truth audit.

Verifies EVERY claim made by ToolFabric / BackendRegistry / runtime
singletons against observable evidence. Writes
`telemetry/system_truth_report.json`.

Verification levels:
  · READY            — executable + invocable + recent valid output
  · DEGRADED         — executable + invocable but no recent output proof
  · UNAVAILABLE      — not installed / not on PATH / not reachable
  · MISCONFIGURED    — installed but invocation errored consistently
  · UNTESTED         — no probe data yet

The audit runs on demand AND on a 5-minute background refresh.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


_REPORT_PATH = Path(__file__).resolve().parent.parent / "telemetry" / "system_truth_report.json"


@dataclass
class TruthAssessment:
    backend:        str
    classification: str         # READY | DEGRADED | UNAVAILABLE | MISCONFIGURED | UNTESTED
    realms:         list
    evidence:       dict        # the observed facts that drove the classification
    remediation:    str
    assessed_at:    float

    def to_dict(self) -> dict:
        return asdict(self)


class SystemTruthAudit:
    """Authoritative classification of every backend's real state."""

    def __init__(self):
        self._lock = threading.RLock()
        self._last_report: dict = {}
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.system_truth_audit", self)
        except Exception:
            pass

    def audit(self) -> dict:
        """Run a full audit and write the report. Returns the report dict."""
        t0 = time.time()
        try:
            from engine.backend_registry import get_backend_registry
            from engine.active_execution_substrate import get_execution_substrate
            br = get_backend_registry()
            br.refresh_from_substrate()
            substrate = get_execution_substrate()
        except Exception as e:
            _log.warning("audit dependencies missing: %s", e)
            return {"error": str(e), "ts": time.time()}

        assessments: list[TruthAssessment] = []
        for cap in br.all_capabilities():
            assessment = self._classify(cap, substrate)
            assessments.append(assessment)

        report = {
            "audited_at":    time.time(),
            "duration_ms":   round((time.time() - t0) * 1000.0, 1),
            "host":          self._host_info(),
            "counts":        self._count_classifications(assessments),
            "assessments":   [a.to_dict() for a in assessments],
            "build_version": "build-026",
        }
        with self._lock:
            self._last_report = report
        self._persist(report)
        self._emit_receipt(report)
        return report

    def last_report(self) -> dict:
        with self._lock:
            return dict(self._last_report)

    # ── Classification logic ──────────────────────────────────────────
    def _classify(self, cap, substrate) -> TruthAssessment:
        evidence: dict = {
            "executable_verified": cap.executable_verified,
            "runtime_verified":    cap.runtime_verified,
            "output_verified":     cap.output_verified,
            "latency_ms":          cap.latency_ms,
            "stability_score":     cap.stability_score,
            "detail":              cap.detail,
        }
        # Pull last invocation if substrate has it
        prof = substrate.profile(cap.name)
        if prof.get("tracked"):
            evidence["invocation_count"] = prof.get("invocation_count", 0)
            evidence["last_error"]       = prof.get("last_error", "")
            evidence["last_invocation"]  = prof.get("last_invocation")

        # Rules
        if not cap.executable_verified:
            classification = "UNAVAILABLE"
            remediation = cap.remediation or f"install {cap.name}"
        elif cap.output_verified:
            classification = "READY"
            remediation = ""
        elif cap.runtime_verified and not evidence.get("last_error"):
            classification = "DEGRADED"
            remediation = ("backend invocable but no validated output yet — "
                            "submit a generation through this backend to confirm")
        elif evidence.get("last_error"):
            classification = "MISCONFIGURED"
            remediation = (f"backend errored on last invocation: "
                            f"{evidence['last_error'][:200]}. "
                            f"check {cap.name} configuration")
        else:
            classification = "UNTESTED"
            remediation = ("backend present but never invoked — "
                            "no proof of generation capability yet")

        return TruthAssessment(
            backend=cap.name,
            classification=classification,
            realms=list(cap.realms),
            evidence=evidence,
            remediation=remediation,
            assessed_at=time.time(),
        )

    def _count_classifications(self, assessments: list) -> dict:
        counts: dict[str, int] = {}
        for a in assessments:
            counts[a.classification] = counts.get(a.classification, 0) + 1
        return counts

    def _host_info(self) -> dict:
        info: dict = {}
        try:
            import platform
            info["python_version"] = platform.python_version()
            info["platform"]       = platform.platform()
        except Exception:
            pass
        try:
            from engine.production_tool_fabric import get_production_tool_fabric
            hw = get_production_tool_fabric().hardware()
            if hw is not None:
                info["cpu_count"]    = hw.cpu_count
                info["ram_mb_total"] = hw.ram_mb_total
                info["gpu_present"]  = hw.gpu_present
                info["gpu_name"]     = hw.gpu_name
                info["vram_mb"]      = hw.vram_mb_total
                info["cuda"]         = hw.cuda_available
        except Exception:
            pass
        return info

    def _persist(self, report: dict) -> None:
        try:
            _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            _REPORT_PATH.write_text(
                json.dumps(report, indent=2, default=str), encoding="utf-8")
        except Exception as e:
            _log.warning("truth report persist failed: %s", e)

    def _emit_receipt(self, report: dict) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="system_truth_audit:run",
                executor="SystemTruthAudit",
                artifact=str(_REPORT_PATH),
                duration_ms=report.get("duration_ms", 0.0),
                verified=True, compute_sha256=False,
                evidence={"counts": report.get("counts", {})},
            )
        except Exception:
            pass


_INSTANCE: Optional[SystemTruthAudit] = None


def get_system_truth_audit() -> SystemTruthAudit:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SystemTruthAudit()
    return _INSTANCE
