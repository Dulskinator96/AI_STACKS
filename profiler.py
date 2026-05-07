# profiler.py — STRATUM Operator Profiling Engine
# ──────────────────────────────────────────────────────────────────────────────
# High-tier behavioral profiling. Learns who Dan is as an operator across
# sessions, adapts prompt injection accordingly, scores agent outputs, and
# feeds fitness signals back to the procreation engine.
#
# Three layers:
#   OperatorProfile  — persistent identity + preferences + project state
#   SessionProfile   — per-session analytics (topics, quality, acceptance)
#   AgentScorecard   — which agent types produce accepted vs rejected outputs
#
# Thread-safe. All writes are atomic via _lock + temp-swap pattern.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import hashlib
import threading
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

SAVE_DIR     = Path.home() / "Documents" / "AI_Monitor"
PROFILE_FILE = SAVE_DIR / "operator_profile.json"
SESSION_LOG  = SAVE_DIR / "session_log.jsonl"


# ── Topic classifier ───────────────────────────────────────────────────────────

_TOPIC_PATTERNS: list[tuple[str, list[str]]] = [
    ("architecture",  ["architect", "design", "struct", "system", "layout", "pattern", "schema"]),
    ("code",          ["function", "class", "method", "debug", "refactor", "import", "module", "bug"]),
    ("agent",         ["agent", "spawn", "procrea", "daemon", "loop", "autonomou", "chaperone"]),
    ("memory",        ["memory", "remember", "recall", "vault", "obsidian", "chromadb", "mempalace"]),
    ("security",      ["security", "owasp", "vulnerab", "threat", "inject", "audit", "credential"]),
    ("strategy",      ["goal", "plan", "okr", "strategy", "priority", "eisenhow", "roadmap"]),
    ("pipeline",      ["pipeline", "capture", "harvest", "stream", "browser", "extension"]),
    ("research",      ["research", "source", "reference", "fact", "validat", "search", "wiki"]),
    ("ui",            ["ui", "interface", "widget", "tab", "button", "layout", "pyqt"]),
    ("deployment",    ["deploy", "build", "docker", "install", "mcp", "environment", "launch"]),
]

def classify_topic(text: str) -> str:
    low = text.lower()
    scores: dict[str, int] = defaultdict(int)
    for topic, keywords in _TOPIC_PATTERNS:
        for kw in keywords:
            if kw in low:
                scores[topic] += 1
    if not scores:
        return "general"
    return max(scores, key=scores.__getitem__)


# ── Query record ───────────────────────────────────────────────────────────────

class QueryRecord:
    __slots__ = ("ts", "query_hash", "topic", "confidence", "validated",
                 "accepted", "agent_type", "tokens_estimated")

    def __init__(
        self,
        query:      str,
        topic:      str,
        confidence: float,
        validated:  bool     = False,
        accepted:   Optional[bool] = None,
        agent_type: str      = "won",
    ):
        self.ts               = datetime.utcnow().isoformat()
        self.query_hash       = hashlib.sha256(query.encode()).hexdigest()[:12]
        self.topic            = topic
        self.confidence       = round(confidence, 3)
        self.validated        = validated
        self.accepted         = accepted
        self.agent_type       = agent_type
        self.tokens_estimated = len(query.split()) * 1.3

    def to_dict(self) -> dict:
        return {s: getattr(self, s) for s in self.__slots__}

    @classmethod
    def from_dict(cls, d: dict) -> "QueryRecord":
        obj = object.__new__(cls)
        for s in cls.__slots__:
            setattr(obj, s, d.get(s))
        return obj


# ── Session profile ─────────────────────────────────────────────────────────────

class SessionProfile:

    def __init__(self, session_id: str):
        self.session_id   = session_id
        self.started_at   = datetime.utcnow().isoformat()
        self.ended_at: Optional[str] = None
        self.queries:     list[QueryRecord] = []
        self.topic_counts: Counter = Counter()
        self.total_tokens_estimated: float = 0.0
        self._lock        = threading.Lock()

    def record(self, query: str, confidence: float = 0.8,
               validated: bool = False, accepted: Optional[bool] = None,
               agent_type: str = "won") -> QueryRecord:
        topic = classify_topic(query)
        qr    = QueryRecord(query, topic, confidence, validated, accepted, agent_type)
        with self._lock:
            self.queries.append(qr)
            self.topic_counts[topic] += 1
            self.total_tokens_estimated += qr.tokens_estimated
        return qr

    def close(self):
        self.ended_at = datetime.utcnow().isoformat()

    def acceptance_rate(self) -> float:
        judged = [q for q in self.queries if q.accepted is not None]
        if not judged:
            return 0.0
        return round(sum(1 for q in judged if q.accepted) / len(judged), 3)

    def avg_confidence(self) -> float:
        if not self.queries:
            return 0.0
        return round(sum(q.confidence for q in self.queries) / len(self.queries), 3)

    def dominant_topic(self) -> str:
        return self.topic_counts.most_common(1)[0][0] if self.topic_counts else "general"

    def to_dict(self) -> dict:
        return {
            "session_id":   self.session_id,
            "started_at":   self.started_at,
            "ended_at":     self.ended_at,
            "query_count":  len(self.queries),
            "topic_counts": dict(self.topic_counts),
            "acceptance_rate": self.acceptance_rate(),
            "avg_confidence":  self.avg_confidence(),
            "dominant_topic":  self.dominant_topic(),
            "tokens_estimated": round(self.total_tokens_estimated),
            "queries": [q.to_dict() for q in self.queries[-50:]],
        }


# ── Agent scorecard ─────────────────────────────────────────────────────────────

class AgentScorecard:
    """
    Tracks per-agent-type acceptance rates across all sessions.
    Feeds fitness signals back to ProcreationEngine for DNA weighting.
    """

    def __init__(self, data: dict | None = None):
        self._scores: dict[str, list[float]] = defaultdict(list)
        if data:
            for k, v in data.items():
                self._scores[k] = v
        self._lock = threading.Lock()

    def record(self, agent_type: str, score: float):
        with self._lock:
            self._scores[agent_type].append(round(max(0.0, min(1.0, score)), 3))
            # Rolling window of last 100 scores per agent
            if len(self._scores[agent_type]) > 100:
                self._scores[agent_type] = self._scores[agent_type][-100:]

    def avg_score(self, agent_type: str) -> float:
        scores = self._scores.get(agent_type, [])
        if not scores:
            return 0.5
        return round(sum(scores) / len(scores), 3)

    def ranked_agents(self) -> list[tuple[str, float]]:
        return sorted(
            ((k, self.avg_score(k)) for k in self._scores),
            key=lambda x: x[1], reverse=True
        )

    def to_dict(self) -> dict:
        return dict(self._scores)


# ── Operator profile ─────────────────────────────────────────────────────────────

class OperatorProfile:
    """
    Persistent, high-tier profile for the operator (Dan).

    Learns across sessions:
    - Topic affinity (what Dan works on most)
    - Query patterns (length, style, complexity)
    - Response preferences (dense/verbose, structured/freeform)
    - Agent performance (which agent types get accepted)
    - Time-of-day usage patterns

    All data persisted to operator_profile.json.
    """

    _instance: Optional["OperatorProfile"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "OperatorProfile":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._lock         = threading.RLock()
        self.current_session: Optional[SessionProfile] = None

        # Persistent data
        self.operator_name:   str   = "Dan"
        self.total_sessions:  int   = 0
        self.total_queries:   int   = 0
        self.topic_affinity:  Counter = Counter()
        self.agent_scorecard: AgentScorecard = AgentScorecard()
        self.response_prefs:  dict  = {
            "preferred_density": "dense",
            "preferred_structure": "structured",
            "preferred_length":   "medium",
        }
        self.session_history: list[dict] = []
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self):
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        if not PROFILE_FILE.exists():
            return
        try:
            d = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
            self.operator_name  = d.get("operator_name", "Dan")
            self.total_sessions = d.get("total_sessions", 0)
            self.total_queries  = d.get("total_queries", 0)
            self.topic_affinity = Counter(d.get("topic_affinity", {}))
            self.agent_scorecard = AgentScorecard(d.get("agent_scorecard", {}))
            self.response_prefs  = d.get("response_prefs", self.response_prefs)
            self.session_history = d.get("session_history", [])[-50:]
        except Exception:
            pass

    def _save(self):
        try:
            tmp = PROFILE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "operator_name":   self.operator_name,
                "total_sessions":  self.total_sessions,
                "total_queries":   self.total_queries,
                "topic_affinity":  dict(self.topic_affinity),
                "agent_scorecard": self.agent_scorecard.to_dict(),
                "response_prefs":  self.response_prefs,
                "session_history": self.session_history[-50:],
                "last_updated":    datetime.utcnow().isoformat(),
            }, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(PROFILE_FILE)
        except Exception:
            pass

    # ── Session lifecycle ──────────────────────────────────────────────────────

    def start_session(self, session_id: str | None = None) -> SessionProfile:
        sid = session_id or datetime.utcnow().strftime("SID-%Y%m%d-%H%M%S")
        with self._lock:
            self.current_session = SessionProfile(sid)
            self.total_sessions += 1
        return self.current_session

    def end_session(self):
        with self._lock:
            if not self.current_session:
                return
            self.current_session.close()
            summary = self.current_session.to_dict()
            self.session_history.append({k: summary[k] for k in
                ("session_id", "started_at", "ended_at", "query_count",
                 "dominant_topic", "acceptance_rate", "avg_confidence")})
            # Update global topic affinity
            for topic, count in self.current_session.topic_counts.items():
                self.topic_affinity[topic] += count
            self.current_session = None
            self._save()

    # ── Recording ──────────────────────────────────────────────────────────────

    def record_query(
        self,
        query:      str,
        confidence: float = 0.8,
        validated:  bool  = False,
        accepted:   Optional[bool] = None,
        agent_type: str   = "won",
    ) -> QueryRecord:
        with self._lock:
            self.total_queries += 1
            if not self.current_session:
                self.start_session()
            qr = self.current_session.record(query, confidence, validated, accepted, agent_type)
            self.topic_affinity[qr.topic] += 1
            if accepted is not None:
                self.agent_scorecard.record(agent_type, 1.0 if accepted else 0.0)
            # Infer response prefs from patterns
            self._infer_response_prefs(query)
            return qr

    def update_acceptance(self, query_hash: str, accepted: bool):
        """Called when Dan approves or rejects a response (thumbs up/down)."""
        with self._lock:
            if not self.current_session:
                return
            for qr in self.current_session.queries:
                if qr.query_hash == query_hash:
                    qr.accepted = accepted
                    self.agent_scorecard.record(qr.agent_type, 1.0 if accepted else 0.0)
                    break
            self._save()

    def update_agent_dna(self, agent_type: str, score: float):
        """Direct fitness signal from procreation engine."""
        with self._lock:
            self.agent_scorecard.record(agent_type, score)
            self._save()

    # ── Inference ──────────────────────────────────────────────────────────────

    def _infer_response_prefs(self, query: str):
        words = len(query.split())
        if words < 10:
            self.response_prefs["preferred_length"] = "concise"
        elif words > 40:
            self.response_prefs["preferred_length"] = "detailed"

        low = query.lower()
        if any(w in low for w in ("explain", "describe", "what is", "how does")):
            self.response_prefs["preferred_structure"] = "explanatory"
        elif any(w in low for w in ("list", "steps", "how to", "build", "create")):
            self.response_prefs["preferred_structure"] = "structured"

    def top_topics(self, n: int = 5) -> list[tuple[str, int]]:
        return self.topic_affinity.most_common(n)

    def top_agents(self, n: int = 5) -> list[tuple[str, float]]:
        return self.agent_scorecard.ranked_agents()[:n]

    # ── Prompt injection ───────────────────────────────────────────────────────

    def get_prompt_injection(self) -> str:
        """
        Returns a compact profile block to inject into system prompts.
        Informs the agent about Dan's current focus, preferences, and
        which agent types are performing well.
        """
        top_t = ", ".join(t for t, _ in self.top_topics(3)) or "general"
        top_a = ", ".join(f"{a}({s:.0%})" for a, s in self.top_agents(3)) or "none"
        prefs = self.response_prefs
        hist  = self.session_history[-1] if self.session_history else {}

        return (
            f"\n── OPERATOR PROFILE (live) ──────────────────────────\n"
            f"  Principal:     {self.operator_name}\n"
            f"  Focus topics:  {top_t}\n"
            f"  Response pref: {prefs.get('preferred_density','dense')} · "
            f"{prefs.get('preferred_structure','structured')} · "
            f"{prefs.get('preferred_length','medium')}\n"
            f"  Top agents:    {top_a}\n"
            f"  Sessions:      {self.total_sessions} · "
            f"Queries: {self.total_queries}\n"
            f"  Last session:  {hist.get('dominant_topic','—')} · "
            f"acceptance {hist.get('acceptance_rate',0):.0%}\n"
            f"────────────────────────────────────────────────────\n"
        )

    def status_dict(self) -> dict:
        with self._lock:
            return {
                "operator":      self.operator_name,
                "total_sessions": self.total_sessions,
                "total_queries":  self.total_queries,
                "top_topics":     dict(self.top_topics(5)),
                "top_agents":     dict(self.top_agents(5)),
                "response_prefs": self.response_prefs,
                "current_session": (
                    self.current_session.to_dict()
                    if self.current_session else None
                ),
            }


# ── Module-level singleton accessor ───────────────────────────────────────────

def get_profile() -> OperatorProfile:
    return OperatorProfile.get()
