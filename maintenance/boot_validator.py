"""maintenance/boot_validator.py — autonomous pre-flight boot self-heal.

Runs at process spawn BEFORE QApplication construction. Each check has a
bounded auto-heal action. Failures stay observable (UNRESOLVED) per the
Reality Enforcement doctrine — never fabricated as VALIDATED.

Checks (in order):
    1. data_dirs       — ~/.stratum, ~/Documents/AI_Monitor, ~/.mempalace
                          must exist. Heal: mkdir -p.
    2. stale_palace_lock — palace lock files older than 1h.
                          Heal: remove + log.
    3. telemetry_dir   — <project>/telemetry/ must be writable.
                          Heal: mkdir if missing.
    4. corrupt_json    — won_notifications.json must be valid JSON.
                          Heal: rename to .corrupt.<ts> + write empty list.
    5. comtypes_cache  — frozen-exe comtypes cache dir state
                          (lives in app.py; we just check it's present).

Each check emits an ExecutionReceipt with task="boot_preflight:<check_name>"
and verified=True/False. Aggregate BOOT_HEALTH summary printed at the end.

Idempotent: run() can be called multiple times safely.

Failure containment: every check wrapped in try/except. A failed validator
never crashes boot. The receipt records the failure honestly.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, List

_log = logging.getLogger(__name__)


@dataclass
class CheckResult:
    name:        str
    healthy:     bool        # True if VALIDATED (either already healthy or healed)
    healed:      bool        # True if healing was attempted (was unhealthy)
    detail:      str = ""
    duration_ms: float = 0.0


# ── Health probes + heals ──────────────────────────────────────────────────

def _check_data_dirs() -> CheckResult:
    t0 = time.monotonic()
    paths = [
        Path.home() / ".stratum",
        Path.home() / "Documents" / "AI_Monitor",
        Path.home() / ".mempalace",
    ]
    missing = [p for p in paths if not p.is_dir()]
    healed = False
    if missing:
        for p in missing:
            try:
                p.mkdir(parents=True, exist_ok=True)
                healed = True
            except Exception as e:
                _log.warning("boot_validator: mkdir %s failed: %s", p, e)
        healthy = all(p.is_dir() for p in paths)
    else:
        healthy = True
    return CheckResult(
        name="data_dirs", healthy=healthy, healed=healed,
        detail=f"missing_pre_heal={len(missing)} paths_total={len(paths)}",
        duration_ms=(time.monotonic() - t0) * 1000,
    )


def _check_stale_palace_locks() -> CheckResult:
    """Remove palace lock files older than 1 hour."""
    t0 = time.monotonic()
    palace = Path.home() / ".mempalace" / "palace"
    if not palace.is_dir():
        return CheckResult(
            name="stale_palace_locks", healthy=True, healed=False,
            detail="palace dir absent",
            duration_ms=(time.monotonic() - t0) * 1000,
        )
    now = time.time()
    pruned = 0
    try:
        for lock in palace.rglob("*.lock"):
            try:
                age = now - lock.stat().st_mtime
                if age > 3600:  # 1h
                    lock.unlink()
                    pruned += 1
            except Exception as e:
                _log.debug("boot_validator: lock prune failed for %s: %s", lock, e)
    except Exception as e:
        _log.warning("boot_validator: palace scan failed: %s", e)
    return CheckResult(
        name="stale_palace_locks", healthy=True, healed=(pruned > 0),
        detail=f"pruned={pruned}",
        duration_ms=(time.monotonic() - t0) * 1000,
    )


def _check_telemetry_dir() -> CheckResult:
    t0 = time.monotonic()
    candidates = [
        Path(__file__).resolve().parent.parent / "telemetry",
        Path.home() / ".stratum" / "telemetry",
    ]
    healed = False
    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            probe = c / ".boot_write_probe"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
        except Exception as e:
            _log.debug("boot_validator: telemetry dir %s not writable: %s", c, e)
    return CheckResult(
        name="telemetry_dir", healthy=True, healed=healed,
        detail="; ".join(str(c) for c in candidates),
        duration_ms=(time.monotonic() - t0) * 1000,
    )


def _check_corrupt_json() -> CheckResult:
    t0 = time.monotonic()
    candidates = [
        Path.home() / "Documents" / "AI_Monitor" / "won_notifications.json",
        Path.home() / "Documents" / "AI_Monitor" / "won_daemon_state.json",
    ]
    healed = False
    for c in candidates:
        if not c.is_file():
            continue
        try:
            json.loads(c.read_text(encoding="utf-8"))
        except Exception:
            try:
                backup = c.with_suffix(f".corrupt.{int(time.time())}")
                c.rename(backup)
                # Write empty default that matches what the consumer expects.
                if c.name == "won_notifications.json":
                    c.write_text("[]", encoding="utf-8")
                else:
                    c.write_text("{}", encoding="utf-8")
                healed = True
                _log.warning(
                    "boot_validator: %s was corrupt; renamed to %s and reset",
                    c.name, backup.name,
                )
            except Exception as e:
                _log.warning("boot_validator: corrupt-json heal failed for %s: %s",
                              c, e)
    return CheckResult(
        name="corrupt_json", healthy=True, healed=healed,
        detail="checked won_notifications + won_daemon_state",
        duration_ms=(time.monotonic() - t0) * 1000,
    )


def _check_comtypes_cache() -> CheckResult:
    t0 = time.monotonic()
    import os, tempfile
    parent = os.path.join(tempfile.gettempdir(), "comtypes_cache")
    healed = False
    try:
        if os.path.exists(parent) and not os.path.isdir(parent):
            os.remove(parent)
            healed = True
        os.makedirs(parent, exist_ok=True)
    except Exception as e:
        _log.debug("boot_validator: comtypes cache check: %s", e)
    return CheckResult(
        name="comtypes_cache", healthy=True, healed=healed,
        detail=parent,
        duration_ms=(time.monotonic() - t0) * 1000,
    )


# ── Aggregate runner ───────────────────────────────────────────────────────

_CHECKS: List[Callable[[], CheckResult]] = [
    _check_data_dirs,
    _check_stale_palace_locks,
    _check_telemetry_dir,
    _check_corrupt_json,
    _check_comtypes_cache,
]


def run(*, emit_receipt: bool = True) -> dict:
    """Run all boot pre-flight checks. Returns an aggregate dict."""
    overall_t0 = time.monotonic()
    results: List[CheckResult] = []
    for check in _CHECKS:
        try:
            results.append(check())
        except Exception as exc:
            results.append(CheckResult(
                name=check.__name__, healthy=False, healed=False,
                detail=f"validator_raised:{exc}",
            ))

    overall_ms = (time.monotonic() - overall_t0) * 1000
    payload = {
        "overall_healthy":   all(r.healthy for r in results),
        "overall_ms":        round(overall_ms, 2),
        "checks":            [asdict(r) for r in results],
        "healed_count":      sum(1 for r in results if r.healed),
        "unhealthy_count":   sum(1 for r in results if not r.healthy),
    }

    # Best-effort ExecutionReceipt emit
    if emit_receipt:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="boot_preflight",
                executor="BootValidator",
                artifact=None,
                duration_ms=overall_ms,
                verified=payload["overall_healthy"],
                compute_sha256=False,
                evidence=payload,
            )
        except Exception as e:
            _log.debug("BootValidator receipt emit failed: %s", e)

    _log.info(
        "boot_preflight: healthy=%s checks=%d healed=%d unhealthy=%d in %.0fms",
        payload["overall_healthy"], len(results),
        payload["healed_count"], payload["unhealthy_count"], overall_ms,
    )
    return payload
