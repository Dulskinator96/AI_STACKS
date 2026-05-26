"""engine/boot_self_check.py — REAL-EXECUTION BOOT VALIDATOR.

Self-bootstrap integrity check. At startup (or on demand) it runs ONE real
worker execution through the canonical path and proves — against the
filesystem — that the system produces real artifacts and contains no
simulation fallback.

It NEVER trusts a state string. A PASS requires a real file on disk whose
size > 0 that passed validation. Anything else is UNAVAILABLE_REAL_EXECUTION
or a CRITICAL_SIMULATION violation. Safe to call at boot — returns a verdict
dict and writes telemetry/boot_self_check.json; raises only if invoked with
strict=True and a CRITICAL_SIMULATION is detected.

Usage:
    from engine.boot_self_check import run_boot_self_check
    verdict = run_boot_self_check()          # returns dict
    verdict = run_boot_self_check(strict=True)  # raises on CRITICAL_SIMULATION

CLI:
    python -m engine.boot_self_check
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _telemetry_dir() -> Path:
    try:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            base = Path(__file__).resolve().parent.parent
        d = base / "telemetry"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return Path.home() / ".stratum" / "telemetry"


ROOT = Path(__file__).resolve().parent.parent
TELEMETRY = _telemetry_dir()

# A trivially-routable, backend-guaranteed intent (audio has a real
# procedural numpy synthesis fallback that needs no external backend).
_PROBE_INTENT = "generate audio: a short calm ambient drone for 2 seconds"


class CriticalSimulation(RuntimeError):
    """Raised (strict mode) when a completion is claimed without a real file."""


def run_boot_self_check(strict: bool = False) -> dict:
    t0 = time.time()
    checks: dict = {}
    violations: list = []

    # ── 0. Anti-simulation static guard: the FakeOutcome shim must be gone.
    fake_present = _fake_outcome_present()
    checks["fake_outcome_removed"] = not fake_present
    if fake_present:
        violations.append("CRITICAL_SIMULATION: _FakeOutcome shim still present in loop_engine")

    # ── 1. Run ONE real execution through the canonical path.
    state = "UNKNOWN"
    real_files: list = []
    dispatch_delta = None
    try:
        from engine.worker_router import get_worker_router
        router = get_worker_router()
        before = router.stats().get("dispatch_count", 0)

        from engine.closed_loop import get_closed_loop_engine
        outcome = get_closed_loop_engine().run(_PROBE_INTENT, candidate_count=1)
        state = getattr(outcome, "state", "UNKNOWN")

        after = router.stats().get("dispatch_count", 0)
        dispatch_delta = after - before

        # Verify EVERY claimed artifact against the real filesystem.
        for a in (getattr(outcome, "final_artifacts", []) or []):
            p = a.get("path", "")
            if p and os.path.isfile(p) and os.path.getsize(p) > 0 \
                    and a.get("validation", {}).get("valid"):
                real_files.append({"path": p, "bytes": os.path.getsize(p)})

        # ── 2. Routing integrity: the worker MUST have been dispatched.
        checks["worker_router_dispatched"] = bool(dispatch_delta and dispatch_delta >= 1)
        if not checks["worker_router_dispatched"]:
            violations.append("BROKEN_ROUTING: WorkerRouter.route did not dispatch a worker")

        # ── 3. Anti-simulation dynamic guard: COMPLETED ⇒ real file on disk.
        if state == "COMPLETED":
            checks["completion_backed_by_file"] = bool(real_files)
            if not real_files:
                violations.append(
                    "CRITICAL_SIMULATION: state=COMPLETED with no real file on disk")
        else:
            checks["completion_backed_by_file"] = None  # not claimed

        # ── 4. CQI is post-hoc: a CQI may exist ONLY when a real file exists.
        cqi = getattr(outcome, "final_cqi", None)
        checks["cqi_only_with_artifact"] = (cqi is None) or bool(real_files)
        if cqi is not None and not real_files:
            violations.append("CRITICAL_SIMULATION: CQI computed without a real artifact")

        checks["real_artifact_produced"] = bool(real_files)

    except Exception as e:
        state = "ERROR"
        checks["execution_error"] = f"{type(e).__name__}: {e}"

    # ── Verdict ────────────────────────────────────────────────────────
    critical = [v for v in violations if v.startswith("CRITICAL")]
    if critical:
        verdict = "CRITICAL_SIMULATION"
    elif real_files and checks.get("worker_router_dispatched"):
        verdict = "PASS_REAL_EXECUTION"
    elif state in ("UNAVAILABLE", "FAILED"):
        verdict = "UNAVAILABLE_REAL_EXECUTION"
    else:
        verdict = "UNVERIFIED"

    report = {
        "boot_self_check": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "probe_intent": _PROBE_INTENT,
        "loop_state": state,
        "real_files": real_files,
        "dispatch_delta": dispatch_delta,
        "checks": checks,
        "violations": violations,
        "duration_ms": round((time.time() - t0) * 1000, 1),
    }
    try:
        TELEMETRY.mkdir(exist_ok=True)
        (TELEMETRY / "boot_self_check.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass

    if strict and verdict == "CRITICAL_SIMULATION":
        raise CriticalSimulation("; ".join(critical))
    return report


def _fake_outcome_present() -> bool:
    try:
        import engine.closed_loop.loop_engine as le
        return hasattr(le, "_FakeOutcome")
    except Exception:
        return False


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    r = run_boot_self_check()
    print(json.dumps({k: r[k] for k in
                      ("verdict", "loop_state", "dispatch_delta",
                       "real_files", "checks", "violations")}, indent=2))
    raise SystemExit(0 if r["verdict"] == "PASS_REAL_EXECUTION" else 1)
