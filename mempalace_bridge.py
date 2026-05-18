"""
mempalace_bridge.py — Canonical AI_MONITOR entry point for the MemPalace.

Wraps the external `mempalace` ChromaDB package so the rest of STRATUM never
imports it directly. Centralizes path resolution, error containment, and
the lightweight palace-health surface used by the UI panel and MemoryAgent.

Single source of truth:
  - palace path  → env PALACE_PATH or ~/.mempalace/palace
  - wing         → env PALACE_WING or "dbombcentral"
  - locks dir    → ~/.mempalace/locks (stale-lock pruning lives here)

Public API:
  is_available()                     → bool — palace + module both importable
  health()                           → dict — counts, palace size, lock count, last mine
  search(query, n=8, wing=None)      → list[dict] — semantic recall
  mine_text(text, source=...)        → bool — drop a transcript into the palace
  mine_directory(directory, ...)     → dict — mine an entire directory tree
  prune_stale_locks(older_than_s=...) → int   — drop abandoned mining locks
  capitalize_topic(text)             → str   — normalize a tag string for storage

  set_status_callback(fn)            — optional UI hook for live mining status
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

_log = logging.getLogger("stratum.mempalace")

# ── Paths ────────────────────────────────────────────────────────────────────
PALACE_PATH = Path(os.environ.get("PALACE_PATH", str(Path.home() / ".mempalace" / "palace")))
PALACE_WING = os.environ.get("PALACE_WING", "dbombcentral")
LOCKS_DIR   = Path.home() / ".mempalace" / "locks"

# ── State ────────────────────────────────────────────────────────────────────
_available: Optional[bool] = None       # None = unknown, True/False after probe
_load_lock = threading.Lock()
_last_mine_ts: float = 0.0
_status_cb: Optional[Callable[[str], None]] = None


def set_status_callback(fn: Callable[[str], None]) -> None:
    """Wire a UI sink that receives short status strings ("mining…", "idle")."""
    global _status_cb
    _status_cb = fn


def _emit(msg: str) -> None:
    if _status_cb is not None:
        try:
            _status_cb(msg)
        except Exception:
            _log.warning("swallowed exception")


def is_available() -> bool:
    """Probe mempalace import once; subsequent calls are cached."""
    global _available
    if _available is not None:
        return _available
    with _load_lock:
        if _available is not None:
            return _available
        try:
            import warnings
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            logging.getLogger("opentelemetry").setLevel(logging.CRITICAL)
            from mempalace.miner import mine                 # noqa: F401
            from mempalace.searcher import search_memories   # noqa: F401
            _available = True
        except Exception as exc:
            _log.warning("MemPalace unavailable: %s", exc)
            _available = False
    return _available


# ── Search ────────────────────────────────────────────────────────────────────
def search(query: str, n: int = 8, wing: Optional[str] = None) -> list[dict]:
    """Semantic recall. Returns [] on failure (never raises).

    Each result: {"text", "similarity", "source_file", "wing", "room"}.
    """
    if not query or not is_available():
        return []
    try:
        from mempalace.searcher import search_memories
        raw = search_memories(
            query, str(PALACE_PATH),
            wing=wing or PALACE_WING,
            n_results=max(1, int(n)),
        )
        hits = raw.get("results", []) if isinstance(raw, dict) else []
        out: list[dict] = []
        for h in hits[:n]:
            out.append({
                "text":        (h.get("text") or "")[:1200],
                "similarity":  float(h.get("similarity") or 0.0),
                "source_file": h.get("source_file") or "palace",
                "wing":        h.get("wing") or "",
                "room":        h.get("room") or "",
            })
        return out
    except Exception as exc:
        _log.warning("MemPalace search failed: %s", exc)
        return []


# ── Mining ────────────────────────────────────────────────────────────────────
def mine_text(
    text: str,
    source: str = "ai-monitor",
    wing: Optional[str] = None,
    agent: str = "ai-monitor",
) -> bool:
    """Drop a text blob into the palace via a temp directory.

    Suitable for transcripts, briefs, session captures, journal lines.
    Returns True on success, False on failure (never raises).
    """
    global _last_mine_ts
    if not text or not is_available():
        return False
    try:
        from mempalace.miner import mine
        _emit("mining…")
        ts_tag = datetime.now().strftime("%Y%m%d-%H%M%S")
        with tempfile.TemporaryDirectory(prefix=f"mp_{ts_tag}_") as tmpdir:
            fpath = Path(tmpdir) / f"{source}_{ts_tag}.md"
            fpath.write_text(text, encoding="utf-8")
            mine(
                project_dir=tmpdir,
                palace_path=str(PALACE_PATH),
                wing_override=wing or PALACE_WING,
                agent=agent,
            )
        _last_mine_ts = time.time()
        _emit("idle")
        return True
    except Exception as exc:
        _log.warning("MemPalace mine_text failed: %s", exc)
        _emit(f"error: {exc}")
        return False


def mine_directory(
    directory: str | Path,
    wing: Optional[str] = None,
    agent: str = "ai-monitor",
    dry_run: bool = False,
) -> dict:
    """Mine an entire directory tree. Returns {"ok": bool, "mined": int, "error": str|None}."""
    global _last_mine_ts
    if not is_available():
        return {"ok": False, "mined": 0, "error": "mempalace unavailable"}
    d = Path(directory)
    if not d.is_dir():
        return {"ok": False, "mined": 0, "error": f"not a directory: {d}"}
    try:
        from mempalace.miner import mine
        _emit(f"mining {d.name}…")
        result = mine(
            project_dir=str(d),
            palace_path=str(PALACE_PATH),
            wing_override=wing or PALACE_WING,
            agent=agent,
            dry_run=dry_run,
        )
        _last_mine_ts = time.time()
        _emit("idle")
        mined = 0
        if isinstance(result, dict):
            mined = int(result.get("files_processed", 0) or result.get("mined", 0))
        return {"ok": True, "mined": mined, "error": None}
    except Exception as exc:
        _log.warning("MemPalace mine_directory failed: %s", exc)
        _emit(f"error: {exc}")
        return {"ok": False, "mined": 0, "error": str(exc)}


# ── Health & maintenance ─────────────────────────────────────────────────────
def health() -> dict:
    """Lightweight palace-health snapshot for the UI panel."""
    info: dict = {
        "available":   is_available(),
        "palace_path": str(PALACE_PATH),
        "wing":        PALACE_WING,
        "last_mine":   _last_mine_ts,
    }
    # Palace size (chroma.sqlite3) + count
    try:
        if PALACE_PATH.is_dir():
            total = 0
            chroma_db = PALACE_PATH / "chroma.sqlite3"
            if chroma_db.is_file():
                info["chroma_size"] = chroma_db.stat().st_size
            for f in PALACE_PATH.rglob("*"):
                if f.is_file():
                    try: total += f.stat().st_size
                    except Exception: _log.warning("swallowed exception")
            info["palace_bytes"] = total
            info["palace_mb"]    = round(total / (1024 * 1024), 1)
        else:
            info["palace_bytes"] = 0
            info["palace_mb"]    = 0.0
    except Exception as exc:
        info["size_error"] = str(exc)

    # Lock-dir health: count + stale (>1h) candidates
    try:
        info["locks"]        = 0
        info["stale_locks"]  = 0
        if LOCKS_DIR.is_dir():
            cutoff = time.time() - 3600
            for lock in LOCKS_DIR.glob("*.lock"):
                info["locks"] += 1
                try:
                    if lock.stat().st_mtime < cutoff:
                        info["stale_locks"] += 1
                except Exception:
                    _log.warning("swallowed exception")
    except Exception as exc:
        info["locks_error"] = str(exc)

    # Drawer count (rough — entries in default collection via direct sqlite peek)
    try:
        if is_available():
            import sqlite3
            chroma_db = PALACE_PATH / "chroma.sqlite3"
            if chroma_db.is_file():
                conn = sqlite3.connect(f"file:{chroma_db}?mode=ro", uri=True)
                try:
                    rows = conn.execute(
                        "SELECT COUNT(*) FROM embeddings"
                    ).fetchone()
                    info["embeddings"] = int(rows[0]) if rows else 0
                except sqlite3.OperationalError:
                    info["embeddings"] = None
                finally:
                    conn.close()
    except Exception as exc:
        info["embeddings_error"] = str(exc)

    return info


def prune_stale_locks(older_than_s: int = 3600) -> int:
    """Delete .lock files in LOCKS_DIR older than `older_than_s` seconds.

    Stale locks accumulate when miner processes crash mid-run; they
    don't block new operations but they waste inodes and clutter the
    folder. Returns count of pruned files.
    """
    if not LOCKS_DIR.is_dir():
        return 0
    cutoff = time.time() - max(60, older_than_s)
    pruned = 0
    for lock in LOCKS_DIR.glob("*.lock"):
        try:
            if lock.stat().st_mtime < cutoff and lock.stat().st_size == 0:
                lock.unlink()
                pruned += 1
        except Exception:
            _log.warning("swallowed exception")
    if pruned:
        _log.info("Pruned %d stale palace locks", pruned)
    return pruned


# ── Topic capitalization ─────────────────────────────────────────────────────
def capitalize_topic(text: str) -> str:
    """Normalize a tag/topic string to Title-Case-With-Hyphens for storage.

    "memory recall, ai monitor" → "Memory-Recall_Ai-Monitor"
    Ensures consistent tag taxonomy across stores so cross-recall works.
    """
    if not text:
        return ""
    raw = text.strip().lower()
    # Split on common separators
    parts = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Title-case each word, hyphen-join
        words = [w.capitalize() for w in chunk.replace("_", " ").split() if w]
        parts.append("-".join(words))
    return "_".join(parts)
