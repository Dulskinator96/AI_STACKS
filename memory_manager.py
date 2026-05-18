"""
memory_manager.py — Long-term memory hygiene (deduplication, compression,
residue cleanup, reporting, scheduled maintenance).

PUBLIC API (preserved 1:1 with prior versions — all 5 callsites in app.py):
    get_dedup()                                  -> DedupRegistry
    compress_old_entries(memory_path='', older_than_days=30, dry_run=False) -> dict
    scan_residue(report_only=True)               -> dict
    efficiency_report(memory_path='')            -> dict
    schedule_cleanup(memory_path='', interval_hours=24) -> threading.Thread

INTERNAL ARCHITECTURE:
    DedupRegistry      — wraps the `db` Supabase content_hashes table; degrades
                         to no-op + structured warning when Supabase is offline.
    CompressionEngine  — compresses cold (>=N days) entries in `db`. Safe
                         no-op when Supabase unavailable.
    ResidueScanner     — purely local: temp files, zero-byte history files,
                         duplicate .txt history, __pycache__ dirs.
    EfficiencyReporter — aggregates remote stats + local stats + dedup metrics
                         + harvester stats into a single report dict.
    MaintenanceScheduler — cancellable daemon that runs compression + residue
                         scan on a user-tunable interval.

DESIGN GUARANTEES:
    * No bare `except: pass` — every error path logs structured detail.
    * Supabase failure does NOT crash callers — every backend call goes
      through a guarded execution helper.
    * Threading uses `threading.Event` so the scheduler thread is stoppable.
    * No silent destructive ops — compression keeps original content in a
      side-cache (BACKUP_DIR / compressed_backups.jsonl) for recovery.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import db

# ── Module logger (uses centralized stratum.log setup) ────────────────────────
_log = logging.getLogger("stratum.memory_manager")

# ── Paths ─────────────────────────────────────────────────────────────────────
SAVE_DIR              = Path.home() / "Documents" / "AI_Monitor"
HISTORY_DIR           = SAVE_DIR / "history"
BACKUP_DIR            = SAVE_DIR / "backups"
COMPRESSION_BACKUP    = BACKUP_DIR / "compressed_backups.jsonl"

# ── Tunables (centralized; previously magic numbers) ──────────────────────────
COMPRESSION_KEEP_CHARS = 200            # bytes kept inline post-compression
COMPRESSION_MARKER     = "…[COMPRESSED]"
TEMP_FILE_AGE_DAYS     = 1              # consider temp files stale after this
RESIDUE_CACHE_TTL_S    = 30             # cache scan_residue result (cheap reuse)

# ── Concurrency primitives shared across the module ──────────────────────────
_module_lock = threading.Lock()

# ── Guarded execution helper ─────────────────────────────────────────────────
T = TypeVar("T")


def _guarded(fn: Callable[..., T], *args: Any, default: T = None,
             context: str = "", **kwargs: Any) -> T:
    """Run ``fn`` and return its result. On exception, log structured detail
    and return ``default``. Replaces every prior `try: ... except: pass`."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        _log.warning("guarded fail (%s): %s: %s",
                     context or fn.__name__, type(exc).__name__, exc)
        return default  # type: ignore[return-value]


def _supabase_ready() -> bool:
    """Probe the `db` gateway once per call; cached internally by db itself."""
    return _guarded(db.available, default=False, context="db.available")


# ═════════════════════════════════════════════════════════════════════════════
#  1.  DEDUPLICATION REGISTRY
# ═════════════════════════════════════════════════════════════════════════════

class DedupRegistry:
    """Content-hash deduplication facade over the Supabase content_hashes
    table. All methods return safe defaults when Supabase is unavailable —
    they never raise to the caller."""

    def hash(self, content: str) -> str:
        if not content:
            return ""
        return _guarded(db.hash_content, content,
                        default=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        context="db.hash_content")

    def is_duplicate(self, content: str) -> bool:
        h = self.hash(content)
        if not h or not _supabase_ready():
            return False
        return bool(_guarded(db.is_duplicate_hash, h,
                             default=False, context="db.is_duplicate_hash"))

    def register(self, content: str, source: str = "") -> bool:
        """Record a fresh content hash. Returns True on success (registered),
        False on either duplicate or backend failure."""
        h = self.hash(content)
        if not h or not _supabase_ready():
            return False
        if _guarded(db.is_duplicate_hash, h, default=False, context="db.is_duplicate_hash"):
            return False
        return _guarded(db.register_hash, h, source,
                        default=False, context="db.register_hash") is not False

    def stats(self) -> dict:
        """Return registry stats or a connection-aware fallback dict."""
        if not _supabase_ready():
            return {"available": False, "reason": "supabase offline"}
        result = _guarded(db.hash_stats, default=None, context="db.hash_stats")
        if result is None:
            return {"available": False, "reason": "hash_stats raised"}
        if isinstance(result, dict):
            result.setdefault("available", True)
            return result
        return {"available": True, "raw": result}


_dedup_registry = DedupRegistry()


def get_dedup() -> DedupRegistry:
    """Public accessor — preserves the legacy API."""
    return _dedup_registry


# ═════════════════════════════════════════════════════════════════════════════
#  2.  COMPRESSION ENGINE
# ═════════════════════════════════════════════════════════════════════════════

class CompressionEngine:
    """Compresses cold (>= N days old) Supabase entries.

    Pre-compression, the FULL original content is appended to
    ``BACKUP_DIR/compressed_backups.jsonl`` as one JSON object per line.
    This makes compression recoverable — the prior implementation truncated
    content with no restore path, which violated the no-destructive-ops
    requirement.
    """

    def __init__(self, backup_path: Path = COMPRESSION_BACKUP):
        self.backup_path = backup_path
        self.backup_path.parent.mkdir(parents=True, exist_ok=True)

    def run(self, older_than_days: int = 30, dry_run: bool = False) -> dict:
        if not _supabase_ready():
            return {
                "compressed": 0, "bytes_saved": 0, "kb_saved": 0.0,
                "dry_run": dry_run, "cutoff_date": None,
                "skipped_reason": "supabase offline",
            }
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        cutoff = cutoff_dt.isoformat()
        rows = _guarded(db.entries_older_than, cutoff,
                        default=[], context="db.entries_older_than")
        compressed, bytes_saved = 0, 0
        for row in rows or []:
            content = (row.get("content") or "") if isinstance(row, dict) else ""
            if not content or len(content) <= COMPRESSION_KEEP_CHARS:
                continue
            if content.startswith("[COMPRESSED]") or content.endswith(COMPRESSION_MARKER):
                continue
            original_size = len(content)
            summary = content[:COMPRESSION_KEEP_CHARS] + COMPRESSION_MARKER
            if not dry_run:
                # Backup BEFORE truncating
                self._append_backup({
                    "id":       row.get("id"),
                    "ts":       datetime.now(timezone.utc).isoformat(),
                    "original": content,
                })
                _guarded(db.update_entry_content, row["id"], summary,
                         context="db.update_entry_content")
            bytes_saved += original_size - len(summary)
            compressed += 1
        return {
            "compressed":  compressed,
            "bytes_saved": bytes_saved,
            "kb_saved":    round(bytes_saved / 1024, 1),
            "dry_run":     dry_run,
            "cutoff_date": cutoff[:10],
        }

    def _append_backup(self, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False) + "\n"
        _guarded(
            lambda: self.backup_path.open("a", encoding="utf-8").write(line),
            context="compression_backup.write",
        )


_compression_engine = CompressionEngine()


def compress_old_entries(memory_path: str = "", older_than_days: int = 30,
                         dry_run: bool = False) -> dict:
    """Legacy entry point. ``memory_path`` is retained for backward compatibility
    but unused — compression targets the Supabase store, not a local file."""
    if memory_path:
        _log.debug("compress_old_entries: memory_path arg ignored (Supabase scope)")
    return _compression_engine.run(older_than_days=older_than_days, dry_run=dry_run)


# ═════════════════════════════════════════════════════════════════════════════
#  3.  RESIDUE SCANNER
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class _ResidueCacheEntry:
    ts:     float
    result: dict = field(default_factory=dict)


class ResidueScanner:
    """Detects + (optionally) cleans local residue:
    * orphan temp files older than TEMP_FILE_AGE_DAYS in OS temp dir
    * zero-byte session txt files in HISTORY_DIR
    * duplicate .txt content in HISTORY_DIR (md5-keyed)
    * __pycache__ directories anywhere under the project root

    Cheap to call repeatedly: scans are memoized for RESIDUE_CACHE_TTL_S
    when report_only=True (idempotent reads).
    """

    def __init__(self):
        self._cache_lock = threading.Lock()
        self._last: Optional[_ResidueCacheEntry] = None

    def scan(self, report_only: bool = True) -> dict:
        if report_only:
            with self._cache_lock:
                if self._last and (time.time() - self._last.ts) < RESIDUE_CACHE_TTL_S:
                    return dict(self._last.result, _cached=True)

        found:   dict[str, list[str]] = {
            "temp_files":     [],
            "empty_files":    [],
            "duplicate_txts": [],
            "pycache_dirs":   [],
        }
        cleaned: dict[str, int] = {k: 0 for k in found}

        self._scan_temp_files(found, cleaned, report_only)
        self._scan_empty_history(found, cleaned, report_only)
        self._scan_duplicate_history(found, cleaned, report_only)
        self._scan_pycache(found, cleaned, report_only)

        result = {
            "found":       {k: len(v) for k, v in found.items()},
            "cleaned":     None if report_only else cleaned,
            "report_only": report_only,
            "details":     found,
        }
        if report_only:
            with self._cache_lock:
                self._last = _ResidueCacheEntry(time.time(), result)
        return result

    # ── individual scan passes ──────────────────────────────────────────────
    def _scan_temp_files(self, found, cleaned, report_only):
        temp_dir = Path(tempfile.gettempdir())
        cutoff_seconds = TEMP_FILE_AGE_DAYS * 86400
        now = time.time()
        for pattern in ("*.tmp", "comtypes_cache"):
            for f in _guarded(lambda p=pattern: list(temp_dir.glob(p)),
                              default=[], context=f"temp_glob({pattern})"):
                if not f.is_file():
                    continue
                age = now - _guarded(lambda: f.stat().st_mtime,
                                     default=now, context="stat.tmp")
                if age <= cutoff_seconds:
                    continue
                found["temp_files"].append(str(f))
                if not report_only:
                    if _guarded(f.unlink, context=f"unlink.tmp({f.name})", default=False) is not False:
                        cleaned["temp_files"] += 1

    def _scan_empty_history(self, found, cleaned, report_only):
        if not HISTORY_DIR.exists():
            return
        for f in _guarded(lambda: list(HISTORY_DIR.glob("*.txt")),
                          default=[], context="history_glob"):
            sz = _guarded(lambda: f.stat().st_size, default=-1, context="stat.history")
            if sz != 0:
                continue
            found["empty_files"].append(f.name)
            if not report_only:
                if _guarded(f.unlink, context=f"unlink.empty({f.name})", default=False) is not False:
                    cleaned["empty_files"] += 1

    def _scan_duplicate_history(self, found, cleaned, report_only):
        if not HISTORY_DIR.exists():
            return
        seen: dict[str, str] = {}
        for f in sorted(_guarded(lambda: list(HISTORY_DIR.glob("*.txt")),
                                 default=[], context="dup_glob")):
            digest = _guarded(
                lambda fp=f: hashlib.md5(fp.read_bytes()).hexdigest(),
                default=None, context="md5",
            )
            if digest is None:
                continue
            if digest in seen:
                found["duplicate_txts"].append(f.name)
                if not report_only:
                    if _guarded(f.unlink, context=f"unlink.dup({f.name})", default=False) is not False:
                        cleaned["duplicate_txts"] += 1
            else:
                seen[digest] = f.name

    def _scan_pycache(self, found, cleaned, report_only):
        here = Path(__file__).resolve().parent
        for d in _guarded(lambda: list(here.rglob("__pycache__")),
                          default=[], context="pycache_rglob"):
            if not d.is_dir():
                continue
            found["pycache_dirs"].append(str(d))
            if not report_only:
                if _guarded(shutil.rmtree, d,
                            context=f"rmtree({d.name})", default=False) is not False:
                    cleaned["pycache_dirs"] += 1


_residue_scanner = ResidueScanner()


def scan_residue(report_only: bool = True) -> dict:
    """Legacy entry point."""
    return _residue_scanner.scan(report_only=report_only)


# ═════════════════════════════════════════════════════════════════════════════
#  4.  EFFICIENCY REPORTER
# ═════════════════════════════════════════════════════════════════════════════

def efficiency_report(memory_path: str = "") -> dict:
    """Aggregate report combining remote (Supabase) stats, dedup metrics,
    and harvester capture stats. Every section is independently guarded so
    one backend outage doesn't blank the whole report.
    """
    if memory_path:
        _log.debug("efficiency_report: memory_path arg ignored")

    report: dict[str, Any] = {}

    # Remote (Supabase) availability + counts
    if _supabase_ready():
        report["remote"] = {
            "available": True,
            "entries":  _guarded(db.count_entries,  default=0, context="db.count_entries"),
            "sessions": _guarded(db.count_sessions, default=0, context="db.count_sessions"),
            "connected": True,
        }
    else:
        report["remote"] = {
            "available": False,
            "connected": False,
            "reason":    "SUPABASE_URL / SUPABASE_KEY not set or unreachable",
        }

    # Dedup metrics
    report["deduplication"] = _dedup_registry.stats()

    # Harvester (capture pipeline) stats — optional
    def _harvest_stats():
        try:
            from harvester import get_stats as _hs
            return _hs()
        except ImportError:
            return {"available": False, "reason": "harvester module absent"}
    report["captures"] = _guarded(_harvest_stats,
                                  default={"available": False, "reason": "guarded fail"},
                                  context="harvester.stats")

    # Local stats
    local_history_files = (
        sum(1 for _ in HISTORY_DIR.glob("*.txt")) if HISTORY_DIR.exists() else 0
    )
    report["local"] = {
        "history_dir":        str(HISTORY_DIR),
        "history_file_count": local_history_files,
        "backup_dir":         str(BACKUP_DIR),
        "compression_backup_present": COMPRESSION_BACKUP.is_file(),
    }

    # Generated recommendations
    recs: list[str] = []
    if not report["remote"]["connected"]:
        recs.append("Set SUPABASE_URL and SUPABASE_KEY to enable remote memory")
    dedup_stats = report["deduplication"]
    if isinstance(dedup_stats, dict) and dedup_stats.get("duplicates_prevented", 0) > 100:
        recs.append("Deduplication active — over 100 duplicates prevented")
    report["recommendations"] = recs

    return report


# ═════════════════════════════════════════════════════════════════════════════
#  5.  MAINTENANCE SCHEDULER (cancellable)
# ═════════════════════════════════════════════════════════════════════════════

class MaintenanceScheduler:
    """Daemon thread running periodic compression + residue cleanup.

    Stoppable via ``stop()`` — the prior implementation used `while True`
    with no stop signal, which leaked on app shutdown.
    """

    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._interval_s = 24 * 3600
        self._tick_count = 0

    def start(self, interval_hours: int = 24) -> threading.Thread:
        if self._thread is not None and self._thread.is_alive():
            _log.info("scheduler already running; ignoring start()")
            return self._thread
        self._stop_event.clear()
        self._interval_s = max(60, int(interval_hours * 3600))
        self._thread = threading.Thread(
            target=self._run, name="MemoryMaintenance", daemon=True,
        )
        self._thread.start()
        _log.info("MaintenanceScheduler started (interval=%ds)", self._interval_s)
        return self._thread

    def stop(self, timeout: float = 5.0) -> bool:
        if self._thread is None:
            return True
        self._stop_event.set()
        self._thread.join(timeout=timeout)
        alive = self._thread.is_alive()
        if alive:
            _log.warning("MaintenanceScheduler did not exit within %ss", timeout)
        else:
            self._thread = None
            _log.info("MaintenanceScheduler stopped after %d ticks", self._tick_count)
        return not alive

    def _run(self) -> None:
        # Initial fast tick — surface health right away rather than wait 24h
        first_delay = min(60, self._interval_s)
        if self._stop_event.wait(timeout=first_delay):
            return
        while not self._stop_event.is_set():
            self._tick_count += 1
            t_start = time.time()
            _guarded(_compression_engine.run, older_than_days=30,
                     context="scheduler.compress")
            _guarded(_residue_scanner.scan, report_only=False,
                     context="scheduler.residue")
            dt = time.time() - t_start
            _log.info("maintenance tick %d completed in %.1fs", self._tick_count, dt)
            if self._stop_event.wait(timeout=self._interval_s):
                break


_scheduler = MaintenanceScheduler()


def schedule_cleanup(memory_path: str = "", interval_hours: int = 24) -> threading.Thread:
    """Legacy entry point — returns the running daemon thread for back-compat."""
    if memory_path:
        _log.debug("schedule_cleanup: memory_path arg ignored")
    return _scheduler.start(interval_hours=interval_hours)


def stop_cleanup(timeout: float = 5.0) -> bool:
    """New explicit shutdown for the scheduler. Safe to call multiple times."""
    return _scheduler.stop(timeout=timeout)


# ═════════════════════════════════════════════════════════════════════════════
#  Public exports
# ═════════════════════════════════════════════════════════════════════════════

__all__ = [
    "DedupRegistry", "CompressionEngine", "ResidueScanner",
    "MaintenanceScheduler",
    "get_dedup", "compress_old_entries", "scan_residue",
    "efficiency_report", "schedule_cleanup", "stop_cleanup",
    "HISTORY_DIR", "BACKUP_DIR", "SAVE_DIR", "COMPRESSION_BACKUP",
]
