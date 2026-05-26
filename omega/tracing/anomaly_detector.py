"""omega.tracing.anomaly_detector — drift detection + anomaly indexing.

Section 3D/3E. Real filesystem + runtime probes, never fabricated. Emits
telemetry/DRIFT_REPORT.json and persists anomaly signatures under
telemetry/anomalies/. Every probe is degrade-safe.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from omega.paths import project_root, telemetry_root, anomalies_dir


def _finding(kind, severity, subsystem, detail, remediation, confidence) -> dict:
    return {"kind": kind, "severity": severity, "subsystem": subsystem,
            "detail": detail, "remediation": remediation, "confidence": confidence}


# ── Section 3D probes ────────────────────────────────────────────────────────
def _probe_duplicated_packages() -> list[dict]:
    """A top-level package name resolvable from >1 root = collision risk (the
    kernel/omega class of bug). Scans the source root + its parent."""
    out: list[dict] = []
    roots = []
    try:
        src = project_root()
        roots = [src, src.parent]
    except Exception:
        return out
    seen: dict[str, list[str]] = {}
    for r in roots:
        try:
            for child in r.iterdir():
                if child.is_dir() and (child / "__init__.py").is_file():
                    seen.setdefault(child.name, []).append(str(child))
        except Exception:
            continue
    for name, locs in seen.items():
        if len(locs) > 1:
            out.append(_finding(
                "duplicated_package", "HIGH", name,
                f"package '{name}' present in {len(locs)} roots: {locs}",
                f"disambiguate '{name}' (rename one) — bundling resolves to one only",
                0.9))
    return out


def _probe_shadow_imports() -> list[dict]:
    """A key module resolving to a file outside its expected root = shadow."""
    out: list[dict] = []
    try:
        src = os.path.normcase(str(project_root()))
    except Exception:
        return out
    for name in ("omega", "engine", "service", "runtime", "truth", "kernel"):
        try:
            mod = importlib.import_module(name)
        except Exception as e:
            out.append(_finding("import_failure", "MEDIUM", name,
                                f"{name} failed to import: {type(e).__name__}: {e}",
                                "verify package present + on path", 0.8))
            continue
        f = getattr(mod, "__file__", None) or getattr(mod, "__path__", [None])
        floc = os.path.normcase(str(f if isinstance(f, str) else (f[0] if f else "")))
        # frozen: everything under _MEIPASS — that's expected, skip
        if getattr(sys, "frozen", False):
            continue
        if floc and src not in floc and "kernel" != name:
            out.append(_finding("shadow_import", "MEDIUM", name,
                                f"{name} resolves to {floc} (outside {src})",
                                "check sys.path ordering / duplicate package", 0.6))
    return out


def _probe_frozen_dev_divergence() -> list[dict]:
    out: list[dict] = []
    bs = telemetry_root() / "backend_scan.json"
    if not bs.is_file():
        return [_finding("telemetry_gap", "MEDIUM", "tool_fabric",
                         "backend_scan.json absent", "run engine.tool_fabric.scan_now()", 0.7)]
    try:
        data = json.loads(bs.read_text(encoding="utf-8"))
        scan_mode = data.get("scan_mode")
        frozen = bool(getattr(sys, "frozen", False))
        expected = "FROZEN_RUNTIME" if frozen else "DEV_RUNTIME"
        if scan_mode != expected:
            out.append(_finding("frozen_dev_divergence", "LOW", "tool_fabric",
                                f"backend_scan scan_mode={scan_mode} but runtime={expected}",
                                "stale scan from other runtime; rescan", 0.5))
    except Exception as e:
        out.append(_finding("telemetry_corrupt", "MEDIUM", "tool_fabric",
                            f"backend_scan unreadable: {e}", "regenerate scan", 0.6))
    return out


def _probe_unresolved_workers() -> list[dict]:
    out: list[dict] = []
    try:
        from engine.workers import get_worker_for_realm
    except Exception as e:
        return [_finding("worker_substrate_down", "HIGH", "engine.workers",
                         f"cannot import workers: {e}", "verify engine.workers", 0.9)]
    for realm in ("image", "video", "audio", "game", "simulation", "code", "cast"):
        try:
            w = get_worker_for_realm(realm)
            if w is None:
                out.append(_finding("unresolved_worker", "MEDIUM", realm,
                                    f"no worker for realm '{realm}'",
                                    f"register a worker for '{realm}'", 0.8))
        except Exception as e:
            out.append(_finding("unresolved_worker", "MEDIUM", realm,
                                f"worker probe raised: {e}", "inspect worker init", 0.7))
    return out


def _probe_missing_artifact_lineage(sample: int = 10) -> list[dict]:
    """Dangling ledger: a recorded execution whose artifact file is gone
    (the build-030 bug class). Samples recent successful executions."""
    out: list[dict] = []
    try:
        import sqlite3
        from omega.paths import ledger_db
        db = ledger_db()
        if not db.is_file():
            return [_finding("telemetry_gap", "MEDIUM", "mem_palace",
                             "ledger db absent", "run an execution to create it", 0.5)]
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT execution_id, file_path FROM executions "
            "WHERE success=1 ORDER BY rowid DESC LIMIT ?", (sample,)).fetchall()
        for r in rows:
            fp = r["file_path"]
            if fp and not Path(fp).is_file():
                out.append(_finding("dangling_lineage", "HIGH", "mem_palace",
                                    f"execution {r['execution_id']} → missing file {fp}",
                                    "frozen path bug? ensure non-_MEIPASS output dir", 0.85))
    except Exception as e:
        out.append(_finding("lineage_probe_error", "LOW", "mem_palace",
                            f"{type(e).__name__}: {e}", "inspect ledger schema", 0.4))
    return out


def _probe_circular_imports() -> list[dict]:
    """Light runtime probe: importing the omega + service surface should not
    raise. Full static circular analysis is out of scope (reported honestly)."""
    out: list[dict] = []
    for name in ("omega.orchestrator", "omega.agents", "omega.rooms", "service.api"):
        try:
            importlib.import_module(name)
        except Exception as e:
            msg = str(e).lower()
            kind = "circular_import" if "circular" in msg or "partially initialized" in msg \
                   else "import_failure"
            out.append(_finding(kind, "HIGH", name,
                                f"{type(e).__name__}: {e}", "resolve import order", 0.8))
    return out


# ── Section 3E anomaly indexing ──────────────────────────────────────────────
def _index_anomaly(f: dict) -> None:
    try:
        sig = hashlib.sha1(f"{f['kind']}|{f['subsystem']}".encode()).hexdigest()[:12]
        path = anomalies_dir() / f"{sig}.json"
        if path.is_file():
            rec = json.loads(path.read_text(encoding="utf-8"))
            rec["frequency_count"] = int(rec.get("frequency_count", 0)) + 1
            rec["last_seen"] = time.time()
            rec["reproducibility_score"] = min(1.0, round(rec["frequency_count"] / 5.0, 2))
        else:
            rec = {
                "signature": sig, "kind": f["kind"], "originating_subsystem": f["subsystem"],
                "first_seen": time.time(), "last_seen": time.time(),
                "frequency_count": 1, "reproducibility_score": 0.2,
                "recommended_remediation": f["remediation"],
                "confidence_score": f["confidence"], "severity": f["severity"],
                "detail": f["detail"],
            }
        path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    except Exception:
        pass


def run_drift_scan(*, persist: bool = True) -> dict:
    """Run all probes, write DRIFT_REPORT.json + anomaly signatures."""
    findings: list[dict] = []
    for probe in (_probe_duplicated_packages, _probe_shadow_imports,
                  _probe_frozen_dev_divergence, _probe_unresolved_workers,
                  _probe_missing_artifact_lineage, _probe_circular_imports):
        try:
            findings.extend(probe() or [])
        except Exception as e:
            findings.append(_finding("probe_error", "LOW", probe.__name__,
                                     f"{type(e).__name__}: {e}", "inspect probe", 0.3))
    sev_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    findings.sort(key=lambda f: sev_rank.get(f["severity"], 0), reverse=True)
    report = {
        "generated_at": time.time(),
        "runtime": "FROZEN" if getattr(sys, "frozen", False) else "DEV",
        "total_findings": len(findings),
        "by_severity": {s: sum(1 for f in findings if f["severity"] == s)
                        for s in ("HIGH", "MEDIUM", "LOW")},
        "clean": len(findings) == 0,
        "findings": findings,
    }
    if persist:
        try:
            (telemetry_root() / "DRIFT_REPORT.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8")
        except Exception:
            pass
        for f in findings:
            _index_anomaly(f)
    return report
