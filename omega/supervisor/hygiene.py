"""omega.supervisor.hygiene — entropy cleanup (BUILD-035 §9, charter §6 E2/E3).

Process hygiene  (E3 ORPHAN RUNTIME): detect + kill stray DBOMBLOCAL / api
                  children / port-8077 holders left by crashed sessions.
Telemetry hygiene (E2 STALE STATE):   detect stale omega_boot.json / scan_mode
                  divergence / orphaned _MEIPASS dirs that contaminate runs.

Real probes only. Read-only by default; killing/clearing requires apply=True.
"""
from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

from omega.paths import project_root, telemetry_root

_EXE_NAMES = ("DBOMBLOCAL.exe",)
_API_PORT = 8077


# ── process hygiene (E3) ────────────────────────────────────────────────────
def _tasklist(image: str) -> list[int]:
    """PIDs of a running image (Windows). Empty on failure / non-Windows."""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=15).stdout
        pids = []
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[0].lower() == image.lower():
                try:
                    pids.append(int(parts[1]))
                except ValueError:
                    pass
        return pids
    except Exception:
        return []


def _port_busy(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def scan_processes() -> dict:
    found = {img: _tasklist(img) for img in _EXE_NAMES}
    total = sum(len(v) for v in found.values())
    return {"images": found, "orphan_count": total,
            "api_port": _API_PORT, "api_port_busy": _port_busy(_API_PORT)}


def clean_processes(*, apply: bool = False) -> dict:
    """Detect (and optionally kill) orphan runtime processes."""
    scan = scan_processes()
    killed = []
    if apply and scan["orphan_count"] and os.name == "nt":
        for img in _EXE_NAMES:
            try:
                subprocess.run(["taskkill", "/IM", img, "/F"],
                               capture_output=True, text=True, timeout=15)
                killed.append(img)
            except Exception:
                pass
        time.sleep(1.5)
    return {"before": scan, "applied": apply, "killed": killed,
            "after": scan_processes() if apply else None}


# ── telemetry hygiene (E2) ───────────────────────────────────────────────────
def scan_stale_telemetry() -> dict:
    findings: list[dict] = []
    tel = telemetry_root()

    # 1. omega_boot.json scan_mode vs current runtime + age
    ob = tel / "omega_boot.json"
    if ob.is_file():
        age_h = (time.time() - ob.stat().st_mtime) / 3600.0
        if age_h > 24:
            findings.append({"kind": "stale_boot_record", "path": str(ob),
                             "age_hours": round(age_h, 1)})

    # 2. backend_scan scan_mode mismatch with current runtime
    bs = tel / "backend_scan.json"
    if bs.is_file():
        import json
        try:
            mode = json.loads(bs.read_text(encoding="utf-8")).get("scan_mode")
            cur = "FROZEN_RUNTIME" if getattr(__import__("sys"), "frozen", False) else "DEV_RUNTIME"
            if mode and mode != cur:
                findings.append({"kind": "scan_mode_divergence", "recorded": mode, "current": cur})
        except Exception:
            pass

    # 3. orphaned PyInstaller _MEIxxxxx temp dirs (crashed frozen unpacks)
    try:
        tmp = Path(os.environ.get("TEMP", "")) if os.name == "nt" else Path("/tmp")
        mei = list(tmp.glob("_MEI*"))[:50] if tmp.exists() else []
        if len(mei) > 3:
            findings.append({"kind": "orphan_meipass_dirs", "count": len(mei),
                             "note": "crashed frozen unpack dirs accumulating"})
    except Exception:
        pass

    # 4. excessive omega run telemetry (unbounded growth)
    try:
        runs = list((tel / "omega").glob("run-*.json"))
        if len(runs) > 200:
            findings.append({"kind": "run_telemetry_bloat", "count": len(runs)})
    except Exception:
        pass

    return {"telemetry_root": str(tel), "findings": findings, "clean": not findings}
