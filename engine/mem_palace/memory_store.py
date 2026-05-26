"""engine/mem_palace/memory_store.py — FILESYSTEM-BACKED EXECUTION LEDGER.

MemPalace is NOT a log / chat history / reasoning trace / CQI narrative.
It is a persistent SQLite ledger that records ONLY real execution outcomes.

GOVERNING LAW: a memory entry (EXECUTION + ARTIFACT) is created ONLY when a
real worker produced a real, validated file on disk. No phantom entries.

Storage rules (ALL must hold to record an EXECUTION):
  RULE 1  a worker was executed via WorkerRouter        (caller-guaranteed)
  RULE 2  a real file exists on disk (os.path.isfile)
  RULE 3  file size > 0
  RULE 4  ArtifactValidator returned VALID
  RULE 5  an execution trace exists (worker receipt/log)

INTENTS are always recorded (incl. FAILED / UNAVAILABLE) so the ledger can
answer "what was attempted". EXECUTIONS + ARTIFACTS are recorded ONLY for
real validated files. METRICS (CQI) are POST-HOC and optional, and may only
attach to an existing EXECUTION — never stand alone.

Output tokens (the ONLY things MemPalace emits):
  MEMORY_STORED · EXECUTION_RECORDED · ARTIFACT_VALIDATED · MEMORY_RELOADED
  · FAILED · UNAVAILABLE
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional


def _telemetry_dir() -> Path:
    """Persistent telemetry dir next to the .exe (frozen) or project root
    (dev). NEVER _MEIPASS — the ledger must survive process exit."""
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
DEFAULT_DB = TELEMETRY / "mem_palace.db"

STATUS_COMPLETED   = "COMPLETED"
STATUS_FAILED      = "FAILED"
STATUS_UNAVAILABLE = "UNAVAILABLE"


def _sha256_of_file(path: str) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


class MemPalace:
    """Disk-backed execution ledger (SQLite). Never an in-memory store."""

    def __init__(self, db_path: Optional[str] = None):
        TELEMETRY.mkdir(exist_ok=True)
        self.db_path = str(db_path or DEFAULT_DB)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._init_schema()
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.mem_palace", self)
        except Exception:
            pass

    # ── schema ──────────────────────────────────────────────────────────
    def _init_schema(self) -> None:
        with self._lock:
            self._db.executescript("""
            CREATE TABLE IF NOT EXISTS intents (
                intent_id  TEXT PRIMARY KEY,
                timestamp  REAL,
                raw_input  TEXT,
                realm      TEXT,
                status     TEXT
            );
            CREATE TABLE IF NOT EXISTS executions (
                execution_id TEXT PRIMARY KEY,
                intent_id    TEXT,
                worker_type  TEXT,
                start_time   REAL,
                end_time     REAL,
                file_path    TEXT NOT NULL,
                success      INTEGER
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id  TEXT PRIMARY KEY,
                execution_id TEXT,
                file_path    TEXT,
                file_size    INTEGER,
                file_hash    TEXT,
                validated    INTEGER
            );
            CREATE TABLE IF NOT EXISTS metrics (
                execution_id TEXT,
                cqi_score    REAL,
                atmos        REAL,
                emo          REAL,
                cinematic    REAL,
                harmony      REAL,
                memory       REAL
            );
            """)
            self._db.commit()

    # ── primary write path — called by WorkerRouter AFTER execution ──────
    def record_execution(self, intent_text: str, realm: str,
                          worker_outcome) -> dict:
        """Enforce the five rules. Always records the INTENT (with status);
        records EXECUTION + ARTIFACTS only when a real validated file exists.
        Returns {intent_id, execution_id|None, status, stored, tokens}."""
        t = time.time()
        intent_id = f"intent-{uuid.uuid4().hex[:12]}"
        tokens: list = []

        # RULE 2-4: gather artifacts that EXIST on disk, size>0, validated.
        real_arts = []
        for a in (getattr(worker_outcome, "artifacts", []) or []):
            if not isinstance(a, dict):
                continue
            p = a.get("path", "")
            if p and os.path.isfile(p) and os.path.getsize(p) > 0 \
                    and a.get("validation", {}).get("valid"):
                real_arts.append((p, os.path.getsize(p)))

        err = (getattr(worker_outcome, "error", "") or "")
        if real_arts:
            status = STATUS_COMPLETED
        elif "UNAVAILABLE_REAL_EXECUTION" in err:
            status = STATUS_UNAVAILABLE
        else:
            status = STATUS_FAILED

        # RULE 5: execution trace must exist (worker id present).
        has_trace = bool(getattr(worker_outcome, "worker_id", ""))

        execution_id = None
        with self._lock:
            self._db.execute(
                "INSERT INTO intents VALUES (?,?,?,?,?)",
                (intent_id, t, (intent_text or "")[:2000], realm, status))

            if status == STATUS_COMPLETED and has_trace:
                execution_id = f"exec-{uuid.uuid4().hex[:12]}"
                primary_path = real_arts[0][0]
                self._db.execute(
                    "INSERT INTO executions VALUES (?,?,?,?,?,?,?)",
                    (execution_id, intent_id,
                     getattr(worker_outcome, "worker_name", "worker"),
                     getattr(worker_outcome, "started_at", t),
                     getattr(worker_outcome, "finished_at", t),
                     primary_path, 1))
                tokens.append(f"EXECUTION_RECORDED: {execution_id}")
                for p, size in real_arts:
                    art_id = f"art-{uuid.uuid4().hex[:12]}"
                    file_hash = _sha256_of_file(p)   # hash from DISK (authoritative)
                    self._db.execute(
                        "INSERT INTO artifacts VALUES (?,?,?,?,?,?)",
                        (art_id, execution_id, p, size, file_hash, 1))
                    tokens.append(f"ARTIFACT_VALIDATED: {p}")
                tokens.append(f"MEMORY_STORED: {execution_id}")
            elif status == STATUS_UNAVAILABLE:
                tokens.append(f"UNAVAILABLE: {err[:160] or realm}")
            else:
                tokens.append(f"FAILED: {(getattr(worker_outcome,'remediation','') or err or 'no valid artifact')[:160]}")
            self._db.commit()

        self._emit(tokens, intent_id, execution_id, status)
        return {"intent_id": intent_id, "execution_id": execution_id,
                "status": status, "stored": execution_id is not None,
                "tokens": tokens}

    # ── post-hoc metrics — NEVER creates an execution ────────────────────
    def attach_metrics(self, execution_id: Optional[str], cqi) -> bool:
        """Attach post-hoc CQI to an EXISTING execution. No-op if the
        execution does not exist (cannot create a CQI-only entry)."""
        if not execution_id or cqi is None:
            return False
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM executions WHERE execution_id=?",
                (execution_id,)).fetchone()
            if row is None:
                return False   # REFUSE CQI-only entry
            self._db.execute(
                "INSERT INTO metrics VALUES (?,?,?,?,?,?,?)",
                (execution_id,
                 float(getattr(cqi, "composite", 0.0) or 0.0),
                 float(getattr(cqi, "atmosphere", 0.0) or 0.0),
                 float(getattr(cqi, "emotional_impact", 0.0) or 0.0),
                 float(getattr(cqi, "cinematic_intensity", 0.0) or 0.0),
                 float(getattr(cqi, "visual_harmony", 0.0) or 0.0),
                 float(getattr(cqi, "memorability", 0.0) or 0.0)))
            self._db.commit()
        return True

    # ── read path ────────────────────────────────────────────────────────
    def load_recent_executions(self, n: int = 10) -> list:
        """Reload the last N real executions from DISK (proves persistence)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM executions ORDER BY end_time DESC LIMIT ?",
                (int(n),)).fetchall()
        out = [dict(r) for r in rows]
        self._emit([f"MEMORY_RELOADED: {len(out)}"], None, None, "RELOAD")
        return out

    def get_execution(self, execution_id: str) -> Optional[dict]:
        with self._lock:
            r = self._db.execute(
                "SELECT * FROM executions WHERE execution_id=?",
                (execution_id,)).fetchone()
            if r is None:
                return None
            ex = dict(r)
            arts = self._db.execute(
                "SELECT * FROM artifacts WHERE execution_id=?",
                (execution_id,)).fetchall()
            ex["artifacts"] = [dict(a) for a in arts]
        return ex

    def counts(self) -> dict:
        with self._lock:
            c = {}
            for tbl in ("intents", "executions", "artifacts", "metrics"):
                c[tbl] = self._db.execute(
                    f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        return c

    # ── telemetry ────────────────────────────────────────────────────────
    def _emit(self, tokens: list, intent_id, execution_id, status) -> None:
        try:
            from engine.live_stream import get_live_stream
            get_live_stream().emit_event("mem_palace", {
                "tokens": tokens, "intent_id": intent_id,
                "execution_id": execution_id, "status": status})
        except Exception:
            pass
        try:
            from truth.receipt_engine import record_execution as _rec
            _rec(task=f"mem_palace:{(status or '').lower()}",
                 executor="MemPalace", duration_ms=0.0,
                 verified=(execution_id is not None),
                 compute_sha256=False,
                 evidence={"tokens": tokens, "execution_id": execution_id})
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._db.close()
        except Exception:
            pass


_INSTANCE: Optional[MemPalace] = None
_INSTANCE_LOCK = threading.Lock()


def get_mem_palace() -> MemPalace:
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = MemPalace()
    return _INSTANCE
