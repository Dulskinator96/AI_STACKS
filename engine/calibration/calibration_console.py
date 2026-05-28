"""engine/calibration/calibration_console.py — BUILD-028 SECTION 11.

Aggregates the 5 existing calibrators (performance/latency/memory/render/
artifact_consistency) into one CalibrationReport. Continuous self-measurement.
Persists to telemetry/calibration_report.json.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)


from omega.paths import telemetry_root
_PATH = telemetry_root() / "calibration_report.json"


class CalibrationConsole:

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.calibration.console", self)
        except Exception:
            pass

    def report(self) -> dict:
        """Run all 5 calibrators, produce one report. Cheap (<100ms)."""
        t0 = time.time()
        snapshots: dict = {}
        try:
            from engine.calibration.performance_calibrator import get_performance_calibrator
            snapshots["performance"] = get_performance_calibrator().snapshot()
        except Exception as e:
            snapshots["performance"] = {"error": str(e)}
        try:
            from engine.calibration.latency_calibrator import get_latency_calibrator
            snapshots["latency"] = get_latency_calibrator().snapshot()
        except Exception as e:
            snapshots["latency"] = {"error": str(e)}
        try:
            from engine.calibration.memory_calibrator import get_memory_calibrator
            snapshots["memory"] = get_memory_calibrator().snapshot()
        except Exception as e:
            snapshots["memory"] = {"error": str(e)}
        try:
            from engine.calibration.render_calibrator import get_render_calibrator
            snapshots["render"] = get_render_calibrator().snapshot()
        except Exception as e:
            snapshots["render"] = {"error": str(e)}
        try:
            from engine.calibration.artifact_consistency import get_artifact_consistency
            snapshots["consistency"] = get_artifact_consistency().snapshot()
        except Exception as e:
            snapshots["consistency"] = {"error": str(e)}

        # Aggregate health
        health = self._aggregate_health(snapshots)

        report = {
            "report_id":     f"calib-{int(time.time()*1000):x}",
            "generated_at":  time.time(),
            "duration_ms":   round((time.time() - t0) * 1000.0, 1),
            "health":        health,
            "snapshots":     snapshots,
        }
        self._persist(report)
        self._emit_receipt(report)
        return report

    def _aggregate_health(self, snaps: dict) -> dict:
        """Single 0..1 health score across all calibrators."""
        scores: list = []
        # Performance: lower CPU + smaller RSS = better
        perf = snaps.get("performance", {})
        if "cpu_percent" in perf and "rss_mb" in perf:
            cpu_score = max(0.0, 1.0 - perf["cpu_percent"] / 200.0)
            rss_score = max(0.0, 1.0 - perf["rss_mb"] / 1024.0)   # < 1GB ideal
            scores.append((cpu_score + rss_score) / 2.0)
        # Memory: ram_available > 1GB = good
        mem = snaps.get("memory", {})
        if "ram_available_mb" in mem:
            mem_score = min(1.0, mem["ram_available_mb"] / 4096.0)
            scores.append(mem_score)
        # Render: p95 < 50ms = good
        rend = snaps.get("render", {})
        if "p95_ms" in rend:
            render_score = max(0.0, 1.0 - rend["p95_ms"] / 100.0)
            scores.append(render_score)
        # Consistency: avg backend score
        cons = snaps.get("consistency", {})
        backends = cons.get("backends", {})
        if backends:
            avg = sum(b.get("score", 0.0) for b in backends.values()) / len(backends)
            scores.append(avg)

        if not scores:
            return {"composite": 0.5, "sample_count": 0,
                    "note": "no calibrator data yet"}
        return {
            "composite":     round(sum(scores) / len(scores), 3),
            "sample_count":  len(scores),
        }

    def _persist(self, report: dict) -> None:
        try:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            _PATH.write_text(json.dumps(report, indent=2, default=str),
                              encoding="utf-8")
        except Exception as e:
            _log.warning("calibration report persist failed: %s", e)

    def _emit_receipt(self, report: dict) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="calibration_console:report",
                executor="CalibrationConsole",
                artifact=str(_PATH),
                duration_ms=report["duration_ms"],
                verified=True, compute_sha256=False,
                evidence={
                    "report_id":     report["report_id"],
                    "health_score":  report["health"].get("composite"),
                    "sample_count":  report["health"].get("sample_count"),
                },
            )
        except Exception:
            pass


_INSTANCE: Optional[CalibrationConsole] = None


def get_calibration_console() -> CalibrationConsole:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = CalibrationConsole()
    return _INSTANCE
