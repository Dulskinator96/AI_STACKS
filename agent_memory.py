"""
agent_memory.py — Per-Agent Memory Hubs for STRATUM.

Each agent has three memory types that persist across sessions:

  Episodic Memory
    Specific notable events — moments this agent found something important,
    surprising, or wrong. Tagged and retrievable by similarity.
    Analogy: "I remember when we hit this exact problem in the auth module last month."

  Semantic Memory
    Generalized facts and patterns the system has learned.
    Not tied to a specific session — accumulated wisdom.
    Analogy: "Ollama returns empty response when context exceeds 4096 tokens."

  Working Memory
    The current session's accumulated context. Cleared between sessions.
    Analogy: "What I know so far in this conversation."

Expert Knowledge Anchors (read-only)
    Grounded reasoning frameworks derived from ExpertFramework constants.
    Not stored — injected from config.py. Cannot be overwritten or hallucinated.

Public API:
    AgentMemory(agent_id)
    memory.store_episodic(content, tags)
    memory.store_semantic(key, value, source)
    memory.recall_episodic(query, limit) → list[dict]
    memory.recall_semantic(query, limit) → list[dict]
    memory.set_working(content)
    memory.get_context_block(query) → str  ← for prompt injection
    get_memory(agent_id) → AgentMemory singleton
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from config import (
    MEMORY_DB,
    MEMORY_EPISODIC_LIMIT,
    MEMORY_SEMANTIC_LIMIT,
    MEMORY_DECAY_DAYS,
    AgentID,
    ExpertFramework,
)

_log = logging.getLogger("stratum.memory")

# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS episodic (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    tags        TEXT    DEFAULT '[]',
    importance  REAL    DEFAULT 0.5,
    recall_count INTEGER DEFAULT 0,
    ts          REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS semantic (
    key         TEXT    PRIMARY KEY,
    value       TEXT    NOT NULL,
    source      TEXT    DEFAULT '',
    confidence  REAL    DEFAULT 0.7,
    access_count INTEGER DEFAULT 0,
    ts          REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_episodic_agent ON episodic(agent_id);
CREATE INDEX IF NOT EXISTS idx_episodic_ts    ON episodic(ts);
"""

# ── Expert knowledge anchors ──────────────────────────────────────────────────

_EXPERT_ANCHORS: dict[str, str] = {
    AgentID.VALIDATION:     ExpertFramework.VALIDATION,
    AgentID.IMPLEMENTATION: ExpertFramework.IMPLEMENTATION,
    AgentID.PLANNER:        ExpertFramework.PLANNER,
    AgentID.STRATEGIST:     ExpertFramework.STRATEGIST,
    AgentID.SYNTHESIS:      ExpertFramework.SYNTHESIS,
}


# ── Memory store ──────────────────────────────────────────────────────────────

class MemoryStore:
    """Shared SQLite store. Thread-safe. One instance per process."""

    _instance: Optional["MemoryStore"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self, db_path: Path = MEMORY_DB):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()
        self._write_lock = threading.Lock()

    @classmethod
    def get(cls) -> "MemoryStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = MemoryStore()
        return cls._instance

    # ── Episodic ─────────────────────────────────────────────────────────────

    def store_episodic(self, agent_id: str, content: str,
                       tags: list[str], importance: float = 0.5) -> None:
        with self._write_lock:
            self._conn.execute(
                "INSERT INTO episodic (agent_id, content, tags, importance, ts)"
                " VALUES (?,?,?,?,?)",
                (agent_id, content[:800], json.dumps(tags), importance, time.time()),
            )
            # Trim to limit
            self._conn.execute("""
                DELETE FROM episodic WHERE agent_id=? AND id NOT IN (
                    SELECT id FROM episodic WHERE agent_id=?
                    ORDER BY importance DESC, ts DESC LIMIT ?
                )
            """, (agent_id, agent_id, MEMORY_EPISODIC_LIMIT))
            self._conn.commit()

    def recall_episodic(self, agent_id: str, query: str,
                        limit: int = 5) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM episodic WHERE agent_id=? ORDER BY importance DESC, ts DESC LIMIT 40",
            (agent_id,),
        ).fetchall()
        if not rows:
            return []
        scored = [
            (dict(r), _similarity(query, r["content"]))
            for r in rows
        ]
        scored.sort(key=lambda x: -x[1])
        results = [r for r, _ in scored[:limit]]
        # Update recall count
        ids = [r["id"] for r in results]
        if ids:
            with self._write_lock:
                self._conn.execute(
                    f"UPDATE episodic SET recall_count = recall_count + 1"
                    f" WHERE id IN ({','.join('?' for _ in ids)})",
                    ids,
                )
                self._conn.commit()
        return results

    # ── Semantic ─────────────────────────────────────────────────────────────

    def store_semantic(self, key: str, value: str, source: str = "",
                       confidence: float = 0.7) -> None:
        with self._write_lock:
            self._conn.execute("""
                INSERT INTO semantic (key, value, source, confidence, ts)
                VALUES (?,?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value, source=excluded.source,
                    confidence=excluded.confidence, ts=excluded.ts
            """, (key[:200], value[:1000], source[:200], confidence, time.time()))
            # Trim
            self._conn.execute("""
                DELETE FROM semantic WHERE key NOT IN (
                    SELECT key FROM semantic ORDER BY confidence DESC, ts DESC LIMIT ?
                )
            """, (MEMORY_SEMANTIC_LIMIT,))
            self._conn.commit()

    def recall_semantic(self, query: str, limit: int = 5) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM semantic ORDER BY confidence DESC, ts DESC LIMIT 60"
        ).fetchall()
        if not rows:
            return []
        # Decay score for old entries
        now = time.time()
        decay_threshold = MEMORY_DECAY_DAYS * 86400
        scored: list[tuple[dict, float]] = []
        for r in rows:
            age_factor = max(0.3, 1.0 - (now - r["ts"]) / (decay_threshold * 3))
            sim = _similarity(query, r["key"] + " " + r["value"])
            scored.append((dict(r), sim * age_factor))
        scored.sort(key=lambda x: -x[1])
        return [r for r, _ in scored[:limit]]

    def stats(self, agent_id: str) -> dict:
        ep = self._conn.execute(
            "SELECT COUNT(*) FROM episodic WHERE agent_id=?", (agent_id,)
        ).fetchone()[0]
        sem = self._conn.execute(
            "SELECT COUNT(*) FROM semantic"
        ).fetchone()[0]
        return {"episodic": ep, "semantic": sem}


# ── Per-agent memory facade ───────────────────────────────────────────────────

class AgentMemory:
    """
    Per-agent memory interface. Wraps the shared MemoryStore.
    Each agent gets its own episodic space + shared semantic space.
    Expert knowledge anchors are always available — cannot be overwritten.
    """

    def __init__(self, agent_id: str):
        self.agent_id   = agent_id
        self._store     = MemoryStore.get()
        self._working:  str = ""  # current session context

    def store_episodic(self, content: str, tags: Optional[list[str]] = None,
                       importance: float = 0.5) -> None:
        """Store a notable event in this agent's episodic memory."""
        self._store.store_episodic(self.agent_id, content, tags or [], importance)

    def store_semantic(self, key: str, value: str,
                       source: str = "", confidence: float = 0.7) -> None:
        """Store a generalized fact in shared semantic memory."""
        self._store.store_semantic(key, value, source, confidence)

    def recall_episodic(self, query: str, limit: int = 4) -> list[dict]:
        return self._store.recall_episodic(self.agent_id, query, limit)

    def recall_semantic(self, query: str, limit: int = 4) -> list[dict]:
        return self._store.recall_semantic(query, limit)

    def set_working(self, content: str) -> None:
        """Replace current working memory (session context)."""
        self._working = content[:2000]

    def append_working(self, content: str) -> None:
        """Append to working memory without replacing."""
        self._working = (self._working + "\n" + content)[-2000:]

    def get_context_block(self, query: str = "") -> str:
        """
        Build a prompt-ready memory context block for this agent.
        Includes: expert framework anchor + episodic recalls + semantic recalls + working memory.
        """
        sections: list[str] = []

        # Expert framework — read-only, always first
        anchor = _EXPERT_ANCHORS.get(self.agent_id, "")
        if anchor:
            sections.append(anchor.strip())

        # Episodic recall
        if query:
            episodes = self.recall_episodic(query, limit=3)
            if episodes:
                ep_lines = ["## Relevant Past Experiences"]
                for ep in episodes:
                    tags = json.loads(ep.get("tags", "[]"))
                    tag_str = f"  [{', '.join(tags)}]" if tags else ""
                    ep_lines.append(f"- {ep['content'][:200]}{tag_str}")
                sections.append("\n".join(ep_lines))

        # Semantic recall
        if query:
            facts = self.recall_semantic(query, limit=3)
            if facts:
                fact_lines = ["## Relevant Known Facts"]
                for f in facts:
                    conf = f.get("confidence", 0.7)
                    src  = f"  (src: {f['source'][:40]})" if f.get("source") else ""
                    fact_lines.append(
                        f"- [{conf:.0%}] {f['key']}: {f['value'][:200]}{src}"
                    )
                sections.append("\n".join(fact_lines))

        # Working memory
        if self._working:
            sections.append(f"## Working Memory (this session)\n{self._working}")

        return "\n\n".join(sections)

    def stats(self) -> dict:
        return self._store.stats(self.agent_id)


# ── Utility ───────────────────────────────────────────────────────────────────

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower()[:300], b.lower()[:300]).ratio()


# ── Singletons ────────────────────────────────────────────────────────────────

_memories: dict[str, AgentMemory] = {}


def get_memory(agent_id: str) -> AgentMemory:
    if agent_id not in _memories:
        _memories[agent_id] = AgentMemory(agent_id)
    return _memories[agent_id]


def all_memories() -> dict[str, AgentMemory]:
    """Ensure all standard agents have memory instances."""
    for aid in (
        AgentID.VALIDATION, AgentID.IMPLEMENTATION,
        AgentID.PLANNER, AgentID.STRATEGIST, AgentID.SYNTHESIS,
    ):
        get_memory(aid)
    return _memories
