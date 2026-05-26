"""engine/diagnostics_layer.py — BUILD-020 SECTION (organism architecture).

Unified diagnostic surface. Wraps existing maintenance + convergence
infrastructure into a single query interface:
  · maintenance.cortex observers (11 of them, build-018)
  · kernel.convergence_engine (Doctrine §9 ledger)
  · kernel.constraint_engine (RSS ceiling, fabrication markers)
  · tool_fabric status
  · workspace_spawner / workspace_fabric stats
  · pyramid_engine session stats
  · cognitive_core cycle stats

Pull, not push. Tabs and external surfaces call `diagnostics.report()`
to get a snapshot. The layer never spawns its own observers — it
aggregates what's already running.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

_log = logging.getLogger(__name__)


class DiagnosticsLayer:
    """Unified read-only diagnostic aggregator."""

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.diagnostics", self)
        except Exception:
            pass

    def report(self) -> dict:
        """One-shot diagnostic snapshot. Cheap (<10ms). Never raises."""
        t0 = time.time()
        report = {
            "ts":              t0,
            "maintenance":     self._maintenance_section(),
            "convergence":     self._convergence_section(),
            "constraints":     self._constraint_section(),
            "tool_fabric":     self._tool_fabric_section(),
            "workspace":       self._workspace_section(),
            "engine":          self._engine_section(),
            "cognitive_core":  self._cognitive_core_section(),
            "simulation":      self._simulation_section(),
            "media_generation":self._media_section(),
            "adaptive":        self._adaptive_section(),
            "duration_ms":     0.0,
        }
        report["duration_ms"] = (time.time() - t0) * 1000.0
        self._emit_receipt(report)
        return report

    # ── Section builders ──────────────────────────────────────────────
    def _maintenance_section(self) -> dict:
        try:
            from runtime.singleton_registry import get_registry
            cortex = get_registry().get("maintenance.cortex")
            if cortex is None:
                return {"available": False}
            return {
                "available": True,
                "observers": len(getattr(cortex.runtime, "last_outcomes", {}) or {})
                              if hasattr(cortex, "runtime") else 0,
                "outcomes":  dict(getattr(cortex.runtime, "last_outcomes", {}) or {})
                              if hasattr(cortex, "runtime") else {},
            }
        except Exception:
            return {"available": False, "error": "section build failed"}

    def _convergence_section(self) -> dict:
        try:
            from kernel.convergence_engine import get_convergence_engine
            ce = get_convergence_engine()
            if hasattr(ce, "snapshot"):
                return {"available": True, "snapshot": ce.snapshot()}
            return {"available": True, "snapshot": None}
        except Exception:
            return {"available": False}

    def _constraint_section(self) -> dict:
        try:
            from kernel.constraint_engine import get_constraint_engine
            cn = get_constraint_engine()
            if hasattr(cn, "snapshot"):
                return {"available": True, "snapshot": cn.snapshot()}
            return {"available": True}
        except Exception:
            return {"available": False}

    def _tool_fabric_section(self) -> dict:
        try:
            from runtime.singleton_registry import get_registry
            tf = get_registry().get("engine.tool_fabric")
            if tf is None:
                return {"available": False}
            snap = tf.snapshot()
            counts = {"READY": 0, "DEGRADED": 0, "UNAVAILABLE": 0, "FAILED": 0}
            for entry in snap.values():
                counts[entry["status"]] = counts.get(entry["status"], 0) + 1
            return {"available": True, "counts": counts,
                    "ready_tools": tf.ready_tools()}
        except Exception:
            return {"available": False}

    def _workspace_section(self) -> dict:
        out: dict = {}
        try:
            from runtime.workspace_spawner import get_workspace_spawner
            out["spawner"] = get_workspace_spawner().stats()
        except Exception:
            out["spawner"] = {"available": False}
        try:
            from runtime.singleton_registry import get_registry
            wf = get_registry().get("engine.workspace_fabric")
            if wf is not None:
                out["fabric"] = wf.stats()
            else:
                out["fabric"] = {"available": False}
        except Exception:
            out["fabric"] = {"available": False}
        return out

    def _engine_section(self) -> dict:
        try:
            from runtime.singleton_registry import get_registry
            e = get_registry().get("engine.pyramid")
            if e is None:
                return {"available": False}
            return {"available": True, "stats": e.stats()}
        except Exception:
            return {"available": False}

    def _cognitive_core_section(self) -> dict:
        try:
            from runtime.singleton_registry import get_registry
            c = get_registry().get("engine.cognitive_core")
            if c is None:
                return {"available": False}
            return {"available": True, "stats": c.stats(),
                    "context": c.recent_context(5)}
        except Exception:
            return {"available": False}

    def _simulation_section(self) -> dict:
        try:
            from runtime.singleton_registry import get_registry
            s = get_registry().get("engine.simulation")
            if s is None:
                return {"available": False}
            return {"available": True, "stats": s.stats()}
        except Exception:
            return {"available": False}

    def _media_section(self) -> dict:
        try:
            from runtime.singleton_registry import get_registry
            m = get_registry().get("engine.media_generation")
            if m is None:
                return {"available": False}
            return {"available": True, "status": m.status()}
        except Exception:
            return {"available": False}

    def _adaptive_section(self) -> dict:
        try:
            from runtime.singleton_registry import get_registry
            a = get_registry().get("engine.adaptive_learning")
            if a is None:
                return {"available": False}
            return {"available": True, "snapshot": a.snapshot()}
        except Exception:
            return {"available": False}

    def _emit_receipt(self, report: dict) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="diagnostics:report",
                executor="DiagnosticsLayer",
                duration_ms=report.get("duration_ms", 0.0),
                verified=True,
                compute_sha256=False,
                evidence={
                    "sections_available": [
                        k for k, v in report.items()
                        if isinstance(v, dict) and v.get("available", False)
                    ],
                    "duration_ms": report.get("duration_ms"),
                },
            )
        except Exception:
            pass


_INSTANCE: Optional[DiagnosticsLayer] = None


def get_diagnostics() -> DiagnosticsLayer:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = DiagnosticsLayer()
    return _INSTANCE
