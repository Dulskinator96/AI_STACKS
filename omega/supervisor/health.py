"""omega.supervisor.health — the single verified system-reality snapshot.

BUILD-035 (2/?) LAYER-1: "make the system capable of understanding itself."

COMPOSES (never reimplements) already-verified sources into ONE snapshot:
  supervisor.status        — orphan procs, stale telemetry, env readiness, known-good
  engine.system_synopsis   — static code/capability truth
  omega.tracing drift scan — duplication/shadow/lineage entropy
  omega.evolution.diagnose — ranked runtime issues
  boot gates + backend CTES — frozen execution verdicts

REALITY LAW: every sub-probe is degrade-safe → a failure yields verdict
UNKNOWN (never omitted, never fabricated). The composite verdict is CAPPED by
the worst component — it can NEVER read OK while any component is BLOCKED.
Writes telemetry/system_health_snapshot.json.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from omega.paths import telemetry_root

# verdict severity (lower = worse)
_SEV = {"BLOCKED": 0, "DEGRADED": 1, "UNKNOWN": 2, "OK": 3}
_SCORE = {"BLOCKED": 0.0, "DEGRADED": 0.4, "UNKNOWN": 0.6, "OK": 1.0}


def _component(probe: Callable[[], dict]) -> dict:
    """Run a probe; never raise. Probe returns {'verdict':..., ...}."""
    try:
        out = probe() or {}
        v = out.get("verdict", "UNKNOWN")
        if v not in _SEV:
            v = "UNKNOWN"
        out["verdict"] = v
        return out
    except Exception as e:
        return {"verdict": "UNKNOWN", "error": f"{type(e).__name__}: {e}"}


# ── per-source probes (each maps a verified source → a component verdict) ────
def _p_processes() -> dict:
    from omega.supervisor.hygiene import scan_processes
    s = scan_processes()
    return {"verdict": "DEGRADED" if s["orphan_count"] else "OK",
            "orphan_count": s["orphan_count"], "api_port_busy": s["api_port_busy"]}


def _p_stale() -> dict:
    from omega.supervisor.hygiene import scan_stale_telemetry
    s = scan_stale_telemetry()
    return {"verdict": "OK" if s["clean"] else "DEGRADED",
            "findings": s["findings"]}


def _p_environment() -> dict:
    from omega.supervisor.environment import verify_environment
    e = verify_environment()
    return {"verdict": "OK" if e["ready_to_build"] else "BLOCKED",
            "missing_required": e["missing_required"],
            "backends": e["checks"].get("backends")}


def _p_synopsis() -> dict:
    from engine.system_synopsis import generate_synopsis
    syn = generate_synopsis()
    sh = syn.get("system_health", {}) if isinstance(syn, dict) else {}
    score = sh.get("composite") or sh.get("composite_health") or sh.get("score")
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = None
    verdict = ("OK" if (score is None or score >= 0.8)
               else "DEGRADED" if score >= 0.5 else "BLOCKED")
    return {"verdict": verdict, "composite_health": score, "system_health": sh}


def _p_drift() -> dict:
    from omega.tracing import run_drift_scan
    d = run_drift_scan(persist=False)
    bs = d.get("by_severity", {})
    verdict = ("BLOCKED" if bs.get("HIGH") else "DEGRADED" if (bs.get("MEDIUM") or bs.get("LOW")) else "OK")
    return {"verdict": verdict, "total_findings": d.get("total_findings", 0),
            "by_severity": bs}


def _p_evolution() -> dict:
    from omega.evolution import diagnose
    diag = diagnose()
    h = diag.get("health")
    verdict = {"HEALTHY": "OK", "DEGRADED": "DEGRADED", "CRITICAL": "BLOCKED"}.get(h, "UNKNOWN")
    return {"verdict": verdict, "health": h, "issue_count": diag.get("issue_count"),
            "by_severity": diag.get("by_severity")}


def _p_boot_gates() -> dict:
    """Frozen boot verdicts. Absent in a dev run → UNKNOWN (not BLOCKED)."""
    tel = telemetry_root()
    gates = {}
    for name, key in (("boot_self_check.json", "verdict"),
                      ("mem_palace_boot_check.json", "verdict"),
                      ("omega_boot.json", "substrate_truth")):
        p = tel / name
        if p.is_file():
            try:
                gates[name] = json.loads(p.read_text(encoding="utf-8")).get(key)
            except Exception:
                gates[name] = "UNREADABLE"
        else:
            gates[name] = None
    present = [v for v in gates.values() if v]
    if not present:
        return {"verdict": "UNKNOWN", "gates": gates, "note": "no boot gate records (dev runtime)"}
    bad = any(v and "PASS" not in str(v) and v not in ("RESOLVED",) for v in present)
    return {"verdict": "BLOCKED" if bad else "OK", "gates": gates}


def _p_known_good() -> dict:
    # Read the supervisor's known-good record DIRECTLY from disk (L0 telemetry)
    # instead of importing build_supervisor — breaks the health<->build_supervisor
    # import cycle (§2: no cross-layer circular dependency).
    p = telemetry_root() / "supervisor" / "known_good.json"
    if not p.is_file():
        return {"verdict": "UNKNOWN", "known_good": None,
                "note": "no supervised known-good baseline yet"}
    try:
        kg = json.loads(p.read_text(encoding="utf-8"))
        summary = {"exe_sha256": kg.get("exe_sha256"), "verdict": kg.get("verdict"),
                   "when": kg.get("finished_at")}
        return {"verdict": "OK" if kg.get("verdict") else "UNKNOWN", "known_good": summary}
    except Exception as e:
        return {"verdict": "UNKNOWN", "known_good": None, "error": f"{type(e).__name__}: {e}"}


_PROBES = {
    "processes":   _p_processes,
    "stale_telemetry": _p_stale,
    "environment": _p_environment,
    "code_truth":  _p_synopsis,
    "drift":       _p_drift,
    "runtime_diagnosis": _p_evolution,
    "boot_gates":  _p_boot_gates,
    "known_good":  _p_known_good,
}


def health_snapshot(*, persist: bool = True) -> dict:
    components = {name: _component(p) for name, p in _PROBES.items()}
    verdicts = [c["verdict"] for c in components.values()]

    # composite verdict — capped by worst; OK only if ALL ok
    if any(v == "BLOCKED" for v in verdicts):
        composite = "BLOCKED"
    elif any(v == "DEGRADED" for v in verdicts):
        composite = "DEGRADED"
    elif any(v == "UNKNOWN" for v in verdicts):
        composite = "PARTIAL"
    else:
        composite = "OK"
    score = round(sum(_SCORE[v] for v in verdicts) / len(verdicts), 3)

    snapshot = {
        "generated_at": time.time(),
        "composite_verdict": composite,
        "composite_score": score,
        "component_verdicts": {n: c["verdict"] for n, c in components.items()},
        "attention": [n for n, c in components.items() if c["verdict"] in ("BLOCKED", "DEGRADED")],
        "components": components,
    }
    if persist:
        try:
            (telemetry_root() / "system_health_snapshot.json").write_text(
                json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass
    return snapshot
