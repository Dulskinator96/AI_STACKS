# memory_manager.py — Memory pipeline (Supabase backend)
from __future__ import annotations

import hashlib
import shutil
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

import db

SAVE_DIR    = Path.home() / "Documents" / "AI_Monitor"
HISTORY_DIR = SAVE_DIR / "history"

_lock = threading.Lock()


# ── Deduplication (proxy over Supabase content_hashes table) ─────────────────

class _DeupProxy:
    def is_duplicate(self, content: str) -> bool:
        return db.is_duplicate_hash(db.hash_content(content))

    def register(self, content: str, source: str = ""):
        h = db.hash_content(content)
        if not db.is_duplicate_hash(h):
            db.register_hash(h, source)

    def stats(self) -> dict:
        return db.hash_stats()


_dedup_proxy = _DeupProxy()


def get_dedup() -> _DeupProxy:
    return _dedup_proxy


# ── Memory compression ────────────────────────────────────────────────────────

def compress_old_entries(
    memory_path: str = "",
    older_than_days: int = 30,
    dry_run: bool = False,
) -> dict:
    """
    Compress entries older than N days in Supabase.
    Keeps first 200 chars + marker to save storage on cold entries.
    """
    cutoff = (datetime.utcnow() - timedelta(days=older_than_days)).isoformat()
    rows = db.entries_older_than(cutoff)

    compressed = 0
    bytes_saved = 0
    for row in rows:
        content = row.get("content") or ""
        if content and len(content) > 200 and not content.startswith("[COMPRESSED]"):
            original_size = len(content)
            summary = content[:200] + "…[COMPRESSED]"
            if not dry_run:
                db.update_entry_content(row["id"], summary)
            bytes_saved += original_size - len(summary)
            compressed += 1

    return {
        "compressed":  compressed,
        "bytes_saved": bytes_saved,
        "kb_saved":    round(bytes_saved / 1024, 1),
        "dry_run":     dry_run,
        "cutoff_date": cutoff[:10],
    }


# ── Residue scanner ───────────────────────────────────────────────────────────

def scan_residue(report_only: bool = True) -> dict:
    """Scan for and optionally clean local residue (temp files, pycache, empty history)."""
    found = {
        "temp_files":     [],
        "empty_files":    [],
        "duplicate_txts": [],
        "pycache_dirs":   [],
    }
    cleaned = {k: 0 for k in found}

    # Orphaned temp files older than 1 day
    temp_dir = Path(tempfile.gettempdir())
    for pattern in ["*.tmp", "comtypes_cache"]:
        for f in temp_dir.glob(pattern):
            if f.is_file():
                age_days = (datetime.now().timestamp() - f.stat().st_mtime) / 86400
                if age_days > 1:
                    found["temp_files"].append(str(f))
                    if not report_only:
                        try:
                            f.unlink()
                            cleaned["temp_files"] += 1
                        except Exception:
                            pass

    # Zero-byte history files
    if HISTORY_DIR.exists():
        for f in HISTORY_DIR.glob("*.txt"):
            if f.stat().st_size == 0:
                found["empty_files"].append(f.name)
                if not report_only:
                    try:
                        f.unlink()
                        cleaned["empty_files"] += 1
                    except Exception:
                        pass

    # Duplicate .txt history files
    if HISTORY_DIR.exists():
        seen_hashes: dict[str, str] = {}
        for f in sorted(HISTORY_DIR.glob("*.txt")):
            try:
                h = hashlib.md5(f.read_bytes()).hexdigest()
                if h in seen_hashes:
                    found["duplicate_txts"].append(f.name)
                    if not report_only:
                        try:
                            f.unlink()
                            cleaned["duplicate_txts"] += 1
                        except Exception:
                            pass
                else:
                    seen_hashes[h] = f.name
            except Exception:
                pass

    # __pycache__ dirs in project
    _HERE = Path(__file__).resolve().parent
    for d in _HERE.rglob("__pycache__"):
        if d.is_dir():
            found["pycache_dirs"].append(str(d))
            if not report_only:
                try:
                    shutil.rmtree(d)
                    cleaned["pycache_dirs"] += 1
                except Exception:
                    pass

    return {
        "found":       {k: len(v) if isinstance(v, list) else v for k, v in found.items()},
        "cleaned":     cleaned if not report_only else None,
        "report_only": report_only,
        "details":     found,
    }


# ── Data efficiency report ────────────────────────────────────────────────────

def efficiency_report(memory_path: str = "") -> dict:
    report: dict = {}

    try:
        report["remote"] = {
            "entries":    db.count_entries(),
            "sessions":   db.count_sessions(),
            "connected":  db.available(),
        }
    except Exception as exc:
        report["remote"] = {"error": str(exc)}

    try:
        report["deduplication"] = get_dedup().stats()
    except Exception:
        pass

    try:
        from harvester import get_stats as _harvest_stats
        report["captures"] = _harvest_stats()
    except Exception:
        pass

    recs = []
    if not report.get("remote", {}).get("connected"):
        recs.append("Set SUPABASE_URL and SUPABASE_KEY to enable remote memory")
    if report.get("deduplication", {}).get("duplicates_prevented", 0) > 100:
        recs.append("Deduplication active — duplicates prevented")
    report["recommendations"] = recs

    return report


# ── Auto-clean scheduler ──────────────────────────────────────────────────────

def schedule_cleanup(memory_path: str = "", interval_hours: int = 24):
    import time

    def _run():
        while True:
            try:
                compress_old_entries(older_than_days=30)
                scan_residue(report_only=False)
            except Exception:
                pass
            time.sleep(interval_hours * 3600)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
