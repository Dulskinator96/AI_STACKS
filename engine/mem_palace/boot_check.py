"""engine/mem_palace/boot_check.py — MANDATORY MEMORY BOOT GATE.

On startup this proves the full reality loop AND that memory survives a
restart:

  1. execute a real worker intent (canonical path)
  2. produce a real file on disk
  3. validate file exists + size > 0
  4. the WorkerRouter hook writes the execution into MemPalace
  5. RELOAD MemPalace from disk via a FRESH connection (simulates restart)
  6. compare persisted record vs the live execution — hash MUST match

FAIL CONDITIONS: memory mismatch · missing file · missing worker trace ·
missing validation · persisted hash ≠ on-disk hash · any fake/sim entry.

`run_boot_check(strict=True)` raises MemPalaceBootFailure on any failure.
Writes telemetry/mem_palace_boot_check.json. CLI: python -m engine.mem_palace.boot_check
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _telemetry_dir() -> Path:
    try:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            base = Path(__file__).resolve().parent.parent.parent
        d = base / "telemetry"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return Path.home() / ".stratum" / "telemetry"


TELEMETRY = _telemetry_dir()

_PROBE_INTENT = "generate audio: a short calm ambient drone for 2 seconds"


class MemPalaceBootFailure(RuntimeError):
    pass


def run_boot_check(strict: bool = True) -> dict:
    t0 = time.time()
    checks: dict = {}
    failures: list = []

    real_file = None
    exec_id = None
    persisted = None
    try:
        from engine.mem_palace.memory_store import (
            MemPalace, get_mem_palace, _sha256_of_file)

        # 1. Real execution through the canonical path (WorkerRouter hook
        #    records it into MemPalace as a side effect).
        from engine.closed_loop import get_closed_loop_engine
        outcome = get_closed_loop_engine().run(_PROBE_INTENT, candidate_count=1)
        wo = getattr(outcome, "worker_outcome", None)

        # 2-3. real file on disk
        if getattr(outcome, "final_artifacts", None):
            real_file = outcome.final_artifacts[0].get("path")
        checks["loop_state"] = getattr(outcome, "state", "?")
        checks["real_file_on_disk"] = bool(real_file and os.path.isfile(real_file)
                                            and os.path.getsize(real_file) > 0)
        if not checks["real_file_on_disk"]:
            failures.append("missing file: no real artifact on disk")

        # 5. worker trace
        checks["worker_trace_present"] = bool(getattr(wo, "worker_id", ""))
        if not checks["worker_trace_present"]:
            failures.append("missing worker trace")

        # 4. execution recorded in MemPalace (by the router hook)
        exec_id = getattr(wo, "_mem_execution_id", None)
        checks["execution_recorded"] = bool(exec_id)
        if not exec_id:
            failures.append("execution not recorded in MemPalace")

        # 6. RELOAD from disk via a FRESH connection (restart simulation)
        if exec_id:
            fresh = MemPalace(get_mem_palace().db_path)
            persisted = fresh.get_execution(exec_id)
            fresh.close()
            checks["reloaded_from_disk"] = persisted is not None
            if persisted is None:
                failures.append("memory mismatch: execution not found after reload")
            else:
                # persisted file_path must exist and match the live file
                pf = persisted.get("file_path")
                checks["persisted_path_matches"] = (pf == real_file)
                checks["persisted_file_exists"] = bool(pf and os.path.isfile(pf))
                if pf != real_file:
                    failures.append("memory mismatch: persisted path != live path")
                if not checks["persisted_file_exists"]:
                    failures.append("missing file: persisted path not on disk")
                # hash integrity: persisted artifact hash == on-disk hash
                disk_hash = _sha256_of_file(real_file) if real_file else None
                arts = persisted.get("artifacts", [])
                persisted_hash = arts[0].get("file_hash") if arts else None
                checks["hash_matches"] = bool(disk_hash and disk_hash == persisted_hash)
                if not checks["hash_matches"]:
                    failures.append("hash mismatch: persisted != on-disk")
                # no fake/sim entry: success flag must be real True
                checks["no_fake_entry"] = bool(persisted.get("success") == 1)
                if not checks["no_fake_entry"]:
                    failures.append("fake entry: success flag not set by real execution")
    except Exception as e:
        failures.append(f"boot_check exception: {type(e).__name__}: {e}")

    verdict = "PASS_MEMORY_PERSISTED" if not failures else "FAILED"
    report = {
        "mem_palace_boot_check": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "execution_id": exec_id,
        "real_file": real_file,
        "checks": checks,
        "failures": failures,
        "duration_ms": round((time.time() - t0) * 1000, 1),
    }
    try:
        TELEMETRY.mkdir(exist_ok=True)
        (TELEMETRY / "mem_palace_boot_check.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass

    if strict and failures:
        raise MemPalaceBootFailure("; ".join(failures))
    return report


if __name__ == "__main__":
    import logging
    logging.disable(logging.CRITICAL)
    try:
        r = run_boot_check(strict=False)
        print(json.dumps({k: r[k] for k in
                          ("verdict", "execution_id", "real_file",
                           "checks", "failures")}, indent=2))
        raise SystemExit(0 if r["verdict"].startswith("PASS") else 1)
    except SystemExit:
        raise
    except Exception as e:
        print("MEM_PALACE_BOOT_CHECK ERROR:", e)
        raise SystemExit(1)
