"""omega.supervisor.environment — build/runtime environment verification.

Confirms the toolchain needed to build + run OMEGAFORGE is actually present.
Real probes; absence reported honestly.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from omega.paths import project_root


def _cmd_version(args, timeout=10):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else None
    except Exception:
        return None


def verify_environment() -> dict:
    root = project_root()
    checks: dict = {}

    # python + build toolchain
    checks["python"] = sys.version.split()[0]
    checks["pyinstaller"] = _cmd_version([sys.executable, "-m", "PyInstaller", "--version"])
    for mod in ("fastapi", "uvicorn", "starlette", "pydantic", "numpy", "PIL"):
        try:
            m = __import__(mod)
            checks[mod] = getattr(m, "__version__", "present")
        except Exception:
            checks[mod] = None

    # build inputs
    checks["spec_present"] = (root / "ai_monitor.spec").is_file()
    checks["app_present"] = (root / "app.py").is_file()
    checks["omega_present"] = (root / "omega").is_dir()
    checks["service_present"] = (root / "service").is_dir()

    # backends (delegate to verified probe)
    try:
        from engine.tool_fabric import scan_now
        scan = scan_now()
        checks["backends"] = {k: getattr(v, "status", None) for k, v in scan.items()}
    except Exception as e:
        checks["backends"] = {"error": f"{type(e).__name__}: {e}"}

    checks["git"] = _cmd_version(["git", "--version"]) if shutil.which("git") else None

    required = ["pyinstaller", "fastapi", "uvicorn", "numpy"]
    missing = [r for r in required if not checks.get(r)]
    return {"checks": checks, "missing_required": missing,
            "ready_to_build": not missing and checks["spec_present"] and checks["app_present"]}
