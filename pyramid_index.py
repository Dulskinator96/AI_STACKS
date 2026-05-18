"""
pyramid_index.py — Base Layer: Persistent code index with real-time watching.

Content-addressable SQLite store. Tracks every file in a project, storing
metadata, symbols, cross-references, and detected patterns. Only re-parses
files whose SHA-256 changed since last run. Background polling thread
reindexes dirty files automatically.

Public API
----------
    get_index(root) -> PyramidIndex
    PyramidIndex.scan(progress_cb, force) -> dict
    PyramidIndex.watch(interval_s, on_change)
    PyramidIndex.stop()
    PyramidIndex.query_files(pattern, lang) -> list[FileRecord]
    PyramidIndex.symbols_for_file(path)    -> list[SymbolRecord]
    PyramidIndex.query_symbols(name, lang, kind) -> list[SymbolRecord]
    PyramidIndex.xrefs_of(path)            -> list[XRefRecord]
    PyramidIndex.patterns_in(path)         -> list[PatternRecord]
    PyramidIndex.dependency_graph(path)    -> dict[str, list[str]]
    PyramidIndex.stats()                   -> dict
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from pyramid_parser import ParseResult, parse_file as _parse_file
import logging
_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

DB_PATH = Path.home() / ".stratum" / "pyramid_index.db"

_SKIP_DIRS = frozenset({
    "__pycache__", ".git", ".venv", "venv", "env", "node_modules",
    ".mypy_cache", "dist", "build", ".eggs", ".pytest_cache",
    ".vs", "target", ".idea", ".tox",
})
_TEXT_EXTS = frozenset({
    ".py", ".pyw",
    ".js", ".mjs", ".cjs", ".jsx",
    ".ts", ".tsx",
    ".go", ".rs", ".java", ".cs",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp",
    ".rb", ".php", ".swift", ".kt", ".scala",
    ".md", ".txt", ".rst",
    ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".sql", ".sh", ".bat", ".ps1",
})

# ── Records ────────────────────────────────────────────────────────────────────

@dataclass
class FileRecord:
    path:          str
    hash:          str
    lang:          str
    mtime:         float
    line_count:    int
    size_bytes:    int
    symbol_count:  int   = 0
    xref_count:    int   = 0
    pattern_count: int   = 0
    indexed_at:    float = 0.0
    dirty:         int   = 0


@dataclass
class SymbolRecord:
    file:       str
    name:       str
    kind:       str
    line_start: int
    line_end:   int
    signature:  str = ""
    docstring:  str = ""


@dataclass
class XRefRecord:
    from_file:   str
    to_file:     str
    from_symbol: str
    to_symbol:   str
    kind:        str


@dataclass
class PatternRecord:
    file:       str
    pattern:    str
    confidence: float
    evidence:   str


# ── Schema ─────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS files (
    path          TEXT PRIMARY KEY,
    hash          TEXT,
    lang          TEXT,
    mtime         REAL,
    line_count    INTEGER,
    size_bytes    INTEGER,
    symbol_count  INTEGER DEFAULT 0,
    xref_count    INTEGER DEFAULT 0,
    pattern_count INTEGER DEFAULT 0,
    indexed_at    REAL,
    dirty         INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS symbols (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    file       TEXT,
    name       TEXT,
    kind       TEXT,
    line_start INTEGER,
    line_end   INTEGER,
    signature  TEXT DEFAULT '',
    docstring  TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS xrefs (
    from_file   TEXT,
    to_file     TEXT,
    from_symbol TEXT DEFAULT '',
    to_symbol   TEXT DEFAULT '',
    kind        TEXT
);
CREATE TABLE IF NOT EXISTS patterns (
    file       TEXT,
    pattern    TEXT,
    confidence REAL,
    evidence   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_xrefs_from   ON xrefs(from_file);
CREATE INDEX IF NOT EXISTS idx_xrefs_to     ON xrefs(to_file);
CREATE INDEX IF NOT EXISTS idx_patterns_file ON patterns(file);
"""


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _open_conn(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _sha256(path: str) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:24]
    except OSError:
        return ""


# ── File walker ────────────────────────────────────────────────────────────────

def _walk(root: Path) -> list[Path]:
    results: list[Path] = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs
                   if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            p = Path(dirpath) / fname
            if p.suffix.lower() in _TEXT_EXTS:
                results.append(p)
    return results


# ── Index engine ──────────────────────────────────────────────────────────────

ProgressCallback = Callable[[str, int, int], None]


class PyramidIndex:
    def __init__(self, project_root: str, db_path: Optional[Path] = None):
        self.root     = str(Path(project_root).resolve())
        self.db_path  = db_path or DB_PATH
        self._conn    = _open_conn(self.db_path)
        self._conn.executescript(_DDL)
        self._conn.commit()
        self._lock         = threading.Lock()
        self._watch_thread: Optional[threading.Thread] = None
        self._stop_event   = threading.Event()
        self._pending:      list[str] = []
        self._pending_lock  = threading.Lock()
        self._on_change:    Optional[Callable[[str], None]] = None

    # ── Public control ─────────────────────────────────────────────────────────

    def scan(
        self,
        progress_cb: Optional[ProgressCallback] = None,
        force: bool = False,
    ) -> dict:
        files = _walk(Path(self.root))
        total = len(files)
        added = updated = skipped = 0

        with self._lock:
            for i, path in enumerate(files):
                if progress_cb and i % 5 == 0:
                    progress_cb(path.name, i, total)
                result = self._index_file(path, force=force)
                if result == "added":
                    added += 1
                elif result == "updated":
                    updated += 1
                else:
                    skipped += 1

            # Remove stale records
            known = {row[0] for row in
                     self._conn.execute("SELECT path FROM files")}
            current = {str(p.resolve()) for p in files}
            for sp in known - current:
                self._delete_file(sp)
            self._conn.commit()

        return {
            "total": total,
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "stale_removed": len(known - current) if 'known' in dir() else 0,
        }

    def watch(
        self,
        interval_s: float = 6.0,
        on_change: Optional[Callable[[str], None]] = None,
    ) -> None:
        if self._watch_thread and self._watch_thread.is_alive():
            return
        self._on_change = on_change
        self._stop_event.clear()
        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            args=(interval_s,),
            daemon=True,
            name="pyramid-watcher",
        )
        self._watch_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def flush_pending(self) -> list[str]:
        """Drain and return any files changed since last call (for UI polling)."""
        with self._pending_lock:
            changed, self._pending = self._pending[:], []
        return changed

    # ── Queries ────────────────────────────────────────────────────────────────

    def query_files(self, pattern: str = "", lang: str = "") -> list[FileRecord]:
        clauses, params = ["path LIKE ?"], [f"%{self.root}%"]
        if pattern:
            clauses.append("path LIKE ?")
            params.append(f"%{pattern}%")
        if lang:
            clauses.append("lang = ?")
            params.append(lang)
        sql = ("SELECT * FROM files WHERE " + " AND ".join(clauses)
               + " ORDER BY indexed_at DESC LIMIT 500")
        rows = self._conn.execute(sql, params).fetchall()
        return [FileRecord(**dict(r)) for r in rows]

    def symbols_for_file(self, path: str) -> list[SymbolRecord]:
        abs_path = self._abs(path)
        rows = self._conn.execute(
            "SELECT file,name,kind,line_start,line_end,signature,docstring"
            " FROM symbols WHERE file=? ORDER BY line_start",
            (abs_path,),
        ).fetchall()
        return [SymbolRecord(**dict(r)) for r in rows]

    def query_symbols(
        self,
        name: str = "",
        lang: str = "",
        kind: str = "",
        limit: int = 200,
    ) -> list[SymbolRecord]:
        clauses, params = [], []
        if name:
            clauses.append("name LIKE ?")
            params.append(f"%{name}%")
        if lang:
            clauses.append(
                "file IN (SELECT path FROM files WHERE lang=?)"
            )
            params.append(lang)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        sql = ("SELECT file,name,kind,line_start,line_end,signature,docstring"
               " FROM symbols")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" ORDER BY name LIMIT {limit}"
        rows = self._conn.execute(sql, params).fetchall()
        return [SymbolRecord(**dict(r)) for r in rows]

    def xrefs_of(self, path: str) -> list[XRefRecord]:
        abs_path = self._abs(path)
        rows = self._conn.execute(
            "SELECT * FROM xrefs WHERE from_file=? OR to_file=?",
            (abs_path, abs_path),
        ).fetchall()
        return [XRefRecord(**dict(r)) for r in rows]

    def patterns_in(self, path: str) -> list[PatternRecord]:
        abs_path = self._abs(path)
        rows = self._conn.execute(
            "SELECT * FROM patterns WHERE file=? ORDER BY confidence DESC",
            (abs_path,),
        ).fetchall()
        return [PatternRecord(**dict(r)) for r in rows]

    def dependency_graph(self, path: Optional[str] = None) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {}
        if path:
            abs_path = self._abs(path)
            rows = self._conn.execute(
                "SELECT from_file, to_file FROM xrefs WHERE kind='import'"
                " AND (from_file=? OR to_file=?)",
                (abs_path, abs_path),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT from_file, to_file FROM xrefs"
                " WHERE kind='import' LIMIT 2000",
            ).fetchall()
        for row in rows:
            src, dst = row[0], row[1]
            graph.setdefault(src, [])
            if dst not in graph[src]:
                graph[src].append(dst)
        return graph

    def stats(self) -> dict:
        def _n(t, w=""):
            q = f"SELECT COUNT(*) FROM {t}"
            if w:
                q += f" WHERE {w}"
            return self._conn.execute(q).fetchone()[0]
        return {
            "files":    _n("files"),
            "symbols":  _n("symbols"),
            "xrefs":    _n("xrefs"),
            "patterns": _n("patterns"),
            "dirty":    _n("files", "dirty=1"),
        }

    # ── Internal ───────────────────────────────────────────────────────────────

    def _abs(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        return str(Path(self.root) / path)

    def _index_file(self, path: Path, force: bool = False) -> str:
        abs_path = str(path.resolve())
        try:
            stat = path.stat()
        except OSError:
            return "skip"

        new_hash = _sha256(abs_path)
        if not new_hash:
            return "skip"

        existing = self._conn.execute(
            "SELECT hash FROM files WHERE path=?", (abs_path,)
        ).fetchone()

        if existing and existing["hash"] == new_hash and not force:
            return "skipped"

        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "skip"

        result: ParseResult = _parse_file(abs_path, source)

        self._conn.execute("""
            INSERT OR REPLACE INTO files
            (path,hash,lang,mtime,line_count,size_bytes,
             symbol_count,xref_count,pattern_count,indexed_at,dirty)
            VALUES (?,?,?,?,?,?,?,?,?,?,0)
        """, (
            abs_path, new_hash, result.lang,
            stat.st_mtime, result.line_count, stat.st_size,
            len(result.symbols), len(result.xrefs), len(result.patterns),
            time.time(),
        ))

        self._conn.execute("DELETE FROM symbols WHERE file=?", (abs_path,))
        if result.symbols:
            self._conn.executemany(
                "INSERT INTO symbols"
                " (file,name,kind,line_start,line_end,signature,docstring)"
                " VALUES (?,?,?,?,?,?,?)",
                [(abs_path, s.name, s.kind, s.line_start, s.line_end,
                  s.signature, s.docstring)
                 for s in result.symbols],
            )

        self._conn.execute("DELETE FROM xrefs WHERE from_file=?", (abs_path,))
        if result.xrefs:
            resolved = []
            for x in result.xrefs:
                to = x.to_file
                if to and not os.path.isabs(to):
                    candidate = str(Path(self.root) / to)
                    to = candidate if os.path.exists(candidate) else to
                resolved.append((abs_path, to, x.from_symbol, x.to_symbol, x.kind))
            self._conn.executemany(
                "INSERT INTO xrefs"
                " (from_file,to_file,from_symbol,to_symbol,kind)"
                " VALUES (?,?,?,?,?)",
                resolved,
            )

        self._conn.execute("DELETE FROM patterns WHERE file=?", (abs_path,))
        if result.patterns:
            self._conn.executemany(
                "INSERT INTO patterns (file,pattern,confidence,evidence)"
                " VALUES (?,?,?,?)",
                [(abs_path, p.name, p.confidence, p.evidence)
                 for p in result.patterns],
            )

        return "updated" if existing else "added"

    def _delete_file(self, path: str) -> None:
        for tbl, col in [("files", "path"), ("symbols", "file"),
                         ("xrefs", "from_file"), ("patterns", "file")]:
            self._conn.execute(f"DELETE FROM {tbl} WHERE {col}=?", (path,))

    def _watch_loop(self, interval_s: float) -> None:
        known_mtimes: dict[str, float] = {}
        while not self._stop_event.is_set():
            try:
                files = _walk(Path(self.root))
                changed: list[Path] = []
                for p in files:
                    try:
                        mt = p.stat().st_mtime
                    except OSError:
                        continue
                    key = str(p)
                    if known_mtimes.get(key) != mt:
                        known_mtimes[key] = mt
                        changed.append(p)

                if changed:
                    with self._lock:
                        for p in changed:
                            self._index_file(p)
                        self._conn.commit()
                    with self._pending_lock:
                        self._pending.extend(str(p) for p in changed)
                    if self._on_change:
                        for p in changed:
                            try:
                                self._on_change(str(p))
                            except Exception:
                                pass
            except Exception as e:
                _log.warning(f'caught exception: {e}')
            self._stop_event.wait(interval_s)


# ── Singleton registry ─────────────────────────────────────────────────────────

_instances:  dict[str, PyramidIndex] = {}
_inst_lock   = threading.Lock()


def get_index(project_root: str) -> PyramidIndex:
    root = str(Path(project_root).resolve())
    with _inst_lock:
        if root not in _instances:
            _instances[root] = PyramidIndex(root)
        return _instances[root]
