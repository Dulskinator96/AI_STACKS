"""omega.evolution.self_diagnosis — aggregate health → ranked issues.

Read-only. Composes runtime_inspector + dependency_health + the drift scanner
+ trace pressure into a single diagnosis with severity-ranked issues. This is
the system's self-awareness surface (for AI + in-app fix rendering). It never
mutates; it only describes.
"""
from __future__ import annotations

import time

from omega.evolution.runtime_inspector import inspect_runtime
from omega.evolution.dependency_health import check_dependencies


def _issue(iid, severity, subsystem, symptom, evidence, fix, confidence) -> dict:
    return {"id": iid, "severity": severity, "subsystem": subsystem,
            "symptom": symptom, "evidence": evidence, "suggested_fix": fix,
            "confidence": confidence}


def diagnose() -> dict:
    runtime = inspect_runtime()
    deps = check_dependencies()
    issues: list[dict] = []

    # 1. unreachable subsystems → CRITICAL (would crash room/agent actions)
    for name, state in runtime.get("subsystems", {}).items():
        if state != "REACHABLE":
            issues.append(_issue(
                f"subsystem.{name}", "CRITICAL", name,
                "subsystem failed to import", state,
                "fix the import error before relying on this subsystem", 0.9))

    # 2. trace pressure → failures/drift accumulating
    tp = runtime.get("trace_pressure", {})
    if isinstance(tp, dict):
        if tp.get("failures", 0) > 0:
            issues.append(_issue(
                "trace.failures", "HIGH", "tracing",
                f"{tp['failures']} FAILURE/CRITICAL traces recorded",
                tp, "inspect failure traces (omega.tracing.lookup) for origin file/line", 0.7))
        if tp.get("orphans", 0) > 0:
            issues.append(_issue(
                "trace.orphans", "LOW", "tracing",
                f"{tp['orphans']} orphan (unlinked) trace events",
                tp, "wrap emitters in trace_context so every line is link-tagged", 0.5))

    # 3. recent run failures
    if runtime.get("recent_failures", 0) >= 3:
        issues.append(_issue(
            "runs.failrate", "MEDIUM", "orchestrator",
            f"{runtime['recent_failures']} of last runs FAILED/BLOCKED",
            runtime.get("recent_run_truths"),
            "check backend availability / intent classification for failing realms", 0.6))

    # 4. drift findings (duplicated packages, dangling lineage, etc.)
    try:
        from omega.tracing import run_drift_scan
        drift = run_drift_scan(persist=False)
        for f in drift.get("findings", []):
            issues.append(_issue(
                f"drift.{f['kind']}.{f['subsystem']}", f["severity"], f["subsystem"],
                f["kind"], f["detail"], f["remediation"], f["confidence"]))
    except Exception as e:
        issues.append(_issue("drift.scanner", "LOW", "anomaly_detector",
                             "drift scan failed", str(e), "inspect anomaly_detector", 0.3))

    rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    issues.sort(key=lambda i: rank.get(i["severity"], 0), reverse=True)

    health = "HEALTHY" if not issues else \
             "DEGRADED" if not any(i["severity"] == "CRITICAL" for i in issues) else "CRITICAL"
    return {
        "generated_at": time.time(),
        "health": health,
        "issue_count": len(issues),
        "by_severity": {s: sum(1 for i in issues if i["severity"] == s)
                        for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")},
        "issues": issues,
        "runtime": runtime,
        "dependencies": deps,
    }
