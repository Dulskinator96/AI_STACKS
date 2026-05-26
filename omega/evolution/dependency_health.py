"""omega.evolution.dependency_health — real dependency + backend probes.

Read-only. Reports what is actually importable / executable, with versions.
No fabricated availability — absence is reported as ABSENT honestly.
"""
from __future__ import annotations

import importlib


_PY_DEPS = ("numpy", "PIL", "fastapi", "uvicorn", "starlette", "pydantic",
            "h11", "anyio", "requests")


def _ver(modname: str):
    try:
        m = importlib.import_module(modname)
        return getattr(m, "__version__", "present")
    except Exception:
        return None


def check_dependencies() -> dict:
    py = {}
    for name in _PY_DEPS:
        v = _ver(name)
        py[name] = {"state": "PRESENT" if v else "ABSENT", "version": v}

    # backends via the verified tool_fabric (CTES v2 dual-layer)
    backends = {}
    try:
        from engine.tool_fabric import scan_now
        scan = scan_now()
        for k, v in scan.items():
            status = getattr(v, "status", None)
            backends[k] = {"status": status, "path": getattr(v, "path", None),
                           "state": "PRESENT" if status in ("READY", "DEGRADED") else "ABSENT"}
    except Exception as e:
        backends = {"error": f"{type(e).__name__}: {e}"}

    # AI heavy stack — explicitly DEFERRED, reported honestly
    heavy = {name: ("PRESENT" if _ver(name) else "ABSENT")
             for name in ("torch", "diffusers", "transformers", "audiocraft")}

    present = sum(1 for d in py.values() if d["state"] == "PRESENT")
    return {"python": py, "backends": backends, "ai_heavy": heavy,
            "python_present": present, "python_total": len(py)}
