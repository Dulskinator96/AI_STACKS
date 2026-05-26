"""omega.paths — frozen-aware path resolution (single source of truth).

REALITY LAW (build-030): persistent files MUST live next to the .exe when
frozen, NEVER under sys._MEIPASS — otherwise telemetry/ledger paths vaporize
when the temp bundle is purged on exit, leaving a dangling ledger. Mirrors
engine/artifact_lineage.py::_telemetry_dir and engine/mem_palace/memory_store.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent          # .../<root>/omega
_SRC_ROOT = _PKG_DIR.parent                          # .../<root> (ai-monitor in dev)


def project_root() -> Path:
    """Frozen: directory holding the .exe. Dev: the source root."""
    try:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
    except Exception:
        pass
    return _SRC_ROOT


def telemetry_root() -> Path:
    d = project_root() / "telemetry"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def omega_telemetry_dir() -> Path:
    """Where omega writes run telemetry (telemetry/omega/<run_id>.json)."""
    d = telemetry_root() / "omega"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def anomalies_dir() -> Path:
    d = telemetry_root() / "anomalies"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def ledger_db() -> Path:
    """Display-only mirror of the engine MemPalace ledger location."""
    return telemetry_root() / "mem_palace.db"


def ensure_src_on_path() -> None:
    """Dev only: make engine.*/runtime.* importable. Frozen bundles everything,
    so this is a no-op there (and must not shadow bundled modules)."""
    if getattr(sys, "frozen", False):
        return
    p = str(_SRC_ROOT)
    if p not in sys.path:
        sys.path.insert(0, p)
