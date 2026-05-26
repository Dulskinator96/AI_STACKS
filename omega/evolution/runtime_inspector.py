"""omega.evolution.runtime_inspector — live runtime snapshot.

Read-only. Captures what the runtime actually is right now: loaded subsystems,
trace error/warning pressure, recent run outcomes, frozen/dev mode. Feeds
self_diagnosis. Never mutates.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from omega.paths import omega_telemetry_dir, project_root


def inspect_runtime() -> dict:
    snap: dict = {"frozen": bool(getattr(sys, "frozen", False)),
                  "python": sys.version.split()[0],
                  "project_root": str(project_root())}

    # subsystem reachability
    subsystems = {}
    for name in ("omega.orchestrator", "omega.agents", "omega.rooms", "omega.tracing",
                 "engine.worker_router", "engine.mem_palace.memory_store",
                 "engine.tool_fabric", "service.api"):
        try:
            __import__(name)
            subsystems[name] = "REACHABLE"
        except Exception as e:
            subsystems[name] = f"UNREACHABLE: {type(e).__name__}: {e}"
    snap["subsystems"] = subsystems

    # trace pressure (error/warning signal)
    try:
        from omega.tracing import index
        idx = index()
        sc = idx["state_counts"]
        snap["trace_pressure"] = {
            "total": idx["total_events"],
            "failures": sc.get("FAILURE", 0) + sc.get("CRITICAL", 0),
            "warnings": sc.get("WARNING", 0),
            "drift": sc.get("DRIFT", 0),
            "orphans": len(idx["orphans"]),
        }
    except Exception as e:
        snap["trace_pressure"] = {"error": f"{type(e).__name__}: {e}"}

    # recent run outcomes
    runs = []
    try:
        files = sorted(omega_telemetry_dir().glob("run-*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:15]
        for p in files:
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
                runs.append(rec.get("overall_truth"))
            except Exception:
                continue
    except Exception:
        pass
    snap["recent_run_truths"] = runs
    snap["recent_failures"] = sum(1 for r in runs if r in ("FAILED", "BLOCKED"))
    return snap
