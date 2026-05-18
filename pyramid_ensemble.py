"""
pyramid_ensemble.py — Multi-Agent Research & Intelligence System for STRATUM Pyramid.

Four specialist agents collaborate through a structured Knowledge Bus:

  ValidationAgent   (Logic Specialist)
    → Source verification, fact-checking, confidence scoring,
      cross-referencing, contradiction detection, authority on credibility

  ImplementationAgent  (Code Specialist)
    → Translates validated knowledge into code, integration patterns,
      reusable modules, version-controlled implementations

  PlannerAgent  (Research Specialist)
    → Web research strategy, knowledge acquisition workflows,
      gap analysis, search orchestration, source discovery

  StrategistAgent  (Knowledge Application Specialist)
    → Knowledge synthesis, strategic roadmaps, trend analysis,
      long-term STRATUM objectives, conflict mediation

Inter-Agent Protocol
--------------------
  KnowledgePacket   — standardized unit of intelligence passed between agents
  KnowledgePipeline — version-controlled SQLite store with dependency graph
  SourceRepDB       — persistent source reputation database
  WebFetcher        — robots.txt-aware, rate-limited, quality-filtered scraper
  ConflictResolver  — arbiter for knowledge disagreements
  AgentMetrics      — per-agent performance tracking

Execution Protocol
------------------
  Round 1  PlannerAgent gathers web research → all agents analyze independently
  Round 2  Agents consume each other's KnowledgePackets, update conclusions
  Synth    StrategistAgent produces final unified intelligence brief

Public API
----------
  EnsembleOrchestrator(model)
  orchestrator.run_async(query, code_context, callback) → Thread
  get_orchestrator(model) → EnsembleOrchestrator
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import requests

from config import ENGINEERING_CORE_PROMPT

# ── Logging ───────────────────────────────────────────────────────────────────

_STRATUM_LOG_DIR = Path.home() / ".stratum"
_STRATUM_LOG_DIR.mkdir(parents=True, exist_ok=True)
_STRATUM_LOG_FILE = _STRATUM_LOG_DIR / "stratum.log"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(name)s %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(str(_STRATUM_LOG_FILE), encoding="utf-8"),
        logging.StreamHandler(),
    ],
    force=True,
)
_log = logging.getLogger("pyramid.ensemble")
_log.info("=== STRATUM log opened — file: %s ===", _STRATUM_LOG_FILE)

# ── Config ────────────────────────────────────────────────────────────────────

OLLAMA_URL    = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "mistral"
LLM_TIMEOUT   = 90
WEB_TIMEOUT   = 8
_DB_PATH      = Path.home() / ".stratum" / "ensemble.db"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ── Source reputation baseline ────────────────────────────────────────────────

_BASE_TRUST: dict[str, float] = {
    "docs.python.org": 0.97, "peps.python.org": 0.97,
    "developer.mozilla.org": 0.95, "docs.microsoft.com": 0.93,
    "docs.rust-lang.org": 0.95, "go.dev": 0.95, "nodejs.org": 0.93,
    "arxiv.org": 0.90, "github.com": 0.88,
    "fastapi.tiangolo.com": 0.88, "reactjs.org": 0.90,
    "stackoverflow.com": 0.85, "pypi.org": 0.85, "npmjs.com": 0.82,
    "wikipedia.org": 0.80, "realpython.com": 0.80,
    "dev.to": 0.65, "medium.com": 0.60,
    "reddit.com": 0.45, "twitter.com": 0.30, "x.com": 0.30,
}
_BLOCKED = frozenset({"pinterest.com", "amazon.com", "ebay.com",
                       "ads.", "tracking.", "analytics.", "doubleclick."})

# ── Knowledge Packet ──────────────────────────────────────────────────────────

@dataclass
class SourceInfo:
    url:            str
    title:          str
    domain:         str
    trust_score:    float
    fetched_at:     float = field(default_factory=time.time)
    robots_allowed: bool  = True
    content_hash:   str   = ""


@dataclass
class KnowledgePacket:
    """Standardized unit of intelligence flowing through the Knowledge Bus."""
    packet_id:      str
    origin_agent:   str
    round:          int
    content_summary: str
    source_info:    Optional[SourceInfo]
    confidence:     float                = 0.70
    relevance_tags: list[str]            = field(default_factory=list)
    cross_refs:     list[str]            = field(default_factory=list)   # other packet_ids
    feedback:       list[str]            = field(default_factory=list)   # from peer agents
    version:        int                  = 1
    timestamp:      float                = field(default_factory=time.time)
    verified:       bool                 = False

    @classmethod
    def create(cls, agent_id: str, round_num: int, summary: str,
               source: Optional[SourceInfo] = None,
               confidence: float = 0.70,
               tags: Optional[list[str]] = None) -> "KnowledgePacket":
        pid = hashlib.sha256(
            f"{agent_id}{round_num}{summary[:40]}{time.time()}".encode()
        ).hexdigest()[:16]
        return cls(
            packet_id=pid, origin_agent=agent_id, round=round_num,
            content_summary=summary, source_info=source,
            confidence=confidence, relevance_tags=tags or [],
        )


# ── Source Reputation DB ──────────────────────────────────────────────────────

_REP_DDL = """
CREATE TABLE IF NOT EXISTS source_rep (
    domain      TEXT PRIMARY KEY,
    base_score  REAL,
    adj_score   REAL,
    access_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    fail_count   INTEGER DEFAULT 0,
    avg_latency_ms REAL DEFAULT 0,
    last_seen    REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS access_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT,
    domain     TEXT,
    success    INTEGER,
    latency_ms REAL,
    ts         REAL DEFAULT (strftime('%s','now'))
);
"""


class SourceRepDB:
    """Persistent source reputation tracker — survives sessions."""

    def __init__(self, db_path: Path = _DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_REP_DDL)
        self._conn.commit()
        self._lock = threading.Lock()
        self._seed_baselines()

    def _seed_baselines(self) -> None:
        for domain, score in _BASE_TRUST.items():
            self._conn.execute(
                "INSERT OR IGNORE INTO source_rep (domain,base_score,adj_score)"
                " VALUES (?,?,?)",
                (domain, score, score),
            )
        self._conn.commit()

    def get_score(self, url: str) -> float:
        domain = urlparse(url).netloc.lstrip("www.")
        for blocked in _BLOCKED:
            if blocked in domain:
                return 0.0
        row = self._conn.execute(
            "SELECT adj_score FROM source_rep WHERE domain=?", (domain,)
        ).fetchone()
        if row:
            return float(row["adj_score"])
        # Unknown domain — check partial match
        for known, score in _BASE_TRUST.items():
            if known in domain:
                return score
        return 0.55

    def update_score(self, url: str, delta: float) -> None:
        domain = urlparse(url).netloc.lstrip("www.")
        with self._lock:
            row = self._conn.execute(
                "SELECT adj_score FROM source_rep WHERE domain=?", (domain,)
            ).fetchone()
            current = float(row["adj_score"]) if row else 0.55
            new_score = max(0.0, min(1.0, current + delta))
            self._conn.execute(
                "INSERT OR REPLACE INTO source_rep"
                " (domain,base_score,adj_score) VALUES (?,?,?)",
                (domain, _BASE_TRUST.get(domain, 0.55), new_score),
            )
            self._conn.commit()

    def log_access(self, url: str, success: bool, latency_ms: float) -> None:
        domain = urlparse(url).netloc.lstrip("www.")
        with self._lock:
            self._conn.execute(
                "INSERT INTO access_log (url,domain,success,latency_ms) VALUES (?,?,?,?)",
                (url, domain, int(success), latency_ms),
            )
            self._conn.execute("""
                INSERT INTO source_rep (domain,base_score,adj_score,
                  access_count,success_count,fail_count,avg_latency_ms,last_seen)
                VALUES (?,0.55,0.55,1,?,?,?,?)
                ON CONFLICT(domain) DO UPDATE SET
                  access_count  = access_count + 1,
                  success_count = success_count + excluded.success_count,
                  fail_count    = fail_count    + excluded.fail_count,
                  avg_latency_ms = (avg_latency_ms * access_count + excluded.avg_latency_ms)
                                   / (access_count + 1),
                  last_seen     = excluded.last_seen
            """, (domain, int(success), int(not success), latency_ms, time.time()))
            self._conn.commit()

    def reputation(self, domain: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM source_rep WHERE domain=?", (domain,)
        ).fetchone()
        return dict(row) if row else {}


# ── Knowledge Pipeline ────────────────────────────────────────────────────────

_PIPE_DDL = """
CREATE TABLE IF NOT EXISTS packets (
    packet_id    TEXT PRIMARY KEY,
    origin_agent TEXT,
    round        INTEGER,
    summary      TEXT,
    source_url   TEXT DEFAULT '',
    source_title TEXT DEFAULT '',
    trust_score  REAL DEFAULT 0.0,
    confidence   REAL DEFAULT 0.7,
    tags         TEXT DEFAULT '',
    cross_refs   TEXT DEFAULT '',
    feedback     TEXT DEFAULT '',
    version      INTEGER DEFAULT 1,
    verified     INTEGER DEFAULT 0,
    ts           REAL
);
CREATE TABLE IF NOT EXISTS dependencies (
    from_packet TEXT,
    to_packet   TEXT,
    rel_type    TEXT   -- "builds_on" | "contradicts" | "validates"
);
CREATE INDEX IF NOT EXISTS idx_packets_agent ON packets(origin_agent);
CREATE INDEX IF NOT EXISTS idx_packets_round ON packets(round);
"""


class KnowledgePipeline:
    """
    Version-controlled SQLite store for all KnowledgePackets.
    Maintains a dependency graph across agents and rounds.
    """

    def __init__(self, db_path: Path = _DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_PIPE_DDL)
        self._conn.commit()
        self._lock = threading.Lock()

    def store(self, packet: KnowledgePacket) -> str:
        with self._lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO packets
                (packet_id,origin_agent,round,summary,source_url,source_title,
                 trust_score,confidence,tags,cross_refs,feedback,version,verified,ts)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                packet.packet_id,
                packet.origin_agent,
                packet.round,
                packet.content_summary[:2000],
                packet.source_info.url   if packet.source_info else "",
                packet.source_info.title if packet.source_info else "",
                packet.source_info.trust_score if packet.source_info else 0.0,
                packet.confidence,
                json.dumps(packet.relevance_tags),
                json.dumps(packet.cross_refs),
                json.dumps(packet.feedback),
                packet.version,
                int(packet.verified),
                packet.timestamp,
            ))
            for ref in packet.cross_refs:
                self._conn.execute(
                    "INSERT OR IGNORE INTO dependencies VALUES (?,?,'builds_on')",
                    (packet.packet_id, ref),
                )
            self._conn.commit()
        return packet.packet_id

    def get(self, packet_id: str) -> Optional[KnowledgePacket]:
        row = self._conn.execute(
            "SELECT * FROM packets WHERE packet_id=?", (packet_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_packet(row)

    def for_agent(self, agent_id: str, round_num: Optional[int] = None) -> list[KnowledgePacket]:
        if round_num is not None:
            rows = self._conn.execute(
                "SELECT * FROM packets WHERE origin_agent=? AND round=? ORDER BY ts",
                (agent_id, round_num),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM packets WHERE origin_agent=? ORDER BY ts",
                (agent_id,),
            ).fetchall()
        return [self._row_to_packet(r) for r in rows]

    def all_for_round(self, round_num: int) -> list[KnowledgePacket]:
        rows = self._conn.execute(
            "SELECT * FROM packets WHERE round=? ORDER BY confidence DESC",
            (round_num,),
        ).fetchall()
        return [self._row_to_packet(r) for r in rows]

    def mark_verified(self, packet_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE packets SET verified=1 WHERE packet_id=?", (packet_id,)
            )
            self._conn.commit()

    def add_feedback(self, packet_id: str, from_agent: str, feedback: str) -> None:
        row = self._conn.execute(
            "SELECT feedback,version FROM packets WHERE packet_id=?", (packet_id,)
        ).fetchone()
        if not row:
            return
        existing = json.loads(row["feedback"])
        existing.append(f"{from_agent}: {feedback}")
        with self._lock:
            self._conn.execute(
                "UPDATE packets SET feedback=?, version=version+1 WHERE packet_id=?",
                (json.dumps(existing), packet_id),
            )
            self._conn.commit()

    def dependency_graph(self) -> dict[str, list[str]]:
        rows = self._conn.execute(
            "SELECT from_packet, to_packet FROM dependencies"
        ).fetchall()
        graph: dict[str, list[str]] = {}
        for r in rows:
            graph.setdefault(r[0], []).append(r[1])
        return graph

    def find_conflicts(self) -> list[tuple[str, str]]:
        rows = self._conn.execute(
            "SELECT from_packet, to_packet FROM dependencies WHERE rel_type='contradicts'"
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def stats(self) -> dict:
        n  = self._conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
        vf = self._conn.execute("SELECT COUNT(*) FROM packets WHERE verified=1").fetchone()[0]
        return {"total": n, "verified": vf, "unverified": n - vf}

    @staticmethod
    def _row_to_packet(row: sqlite3.Row) -> KnowledgePacket:
        src = None
        if row["source_url"]:
            src = SourceInfo(
                url=row["source_url"], title=row["source_title"],
                domain=urlparse(row["source_url"]).netloc,
                trust_score=row["trust_score"],
            )
        return KnowledgePacket(
            packet_id       = row["packet_id"],
            origin_agent    = row["origin_agent"],
            round           = row["round"],
            content_summary = row["summary"],
            source_info     = src,
            confidence      = row["confidence"],
            relevance_tags  = json.loads(row["tags"]),
            cross_refs      = json.loads(row["cross_refs"]),
            feedback        = json.loads(row["feedback"]),
            version         = row["version"],
            verified        = bool(row["verified"]),
            timestamp       = row["ts"],
        )


# ── Web Fetcher (robots.txt-aware, rate-limited) ──────────────────────────────

class WebFetcher:
    """
    Responsible web scraper: checks robots.txt, rate-limits per domain,
    filters low-quality content, scores sources via SourceRepDB.
    """

    def __init__(self, rep_db: SourceRepDB):
        self._rep     = rep_db
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last:   dict[str, float] = {}   # domain → last request time
        self._lock    = threading.Lock()
        self._min_gap = 2.0  # seconds between requests to same domain

    def can_fetch(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain not in self._robots:
                rp = urllib.robotparser.RobotFileParser()
                rp.set_url(f"{parsed.scheme}://{domain}/robots.txt")
                rp.read()
                self._robots[domain] = rp
            return self._robots[domain].can_fetch("*", url)
        except Exception:
            return True   # assume allowed if robots.txt unreachable

    def _rate_limit(self, domain: str) -> None:
        with self._lock:
            last = self._last.get(domain, 0)
            gap  = time.time() - last
            if gap < self._min_gap:
                time.sleep(self._min_gap - gap)
            self._last[domain] = time.time()

    def fetch(self, url: str) -> str:
        if self._rep.get_score(url) < 0.3:
            return ""
        if not self.can_fetch(url):
            _log.info(f"robots.txt disallows {url}")
            return ""
        domain = urlparse(url).netloc
        self._rate_limit(domain)
        t0 = time.time()
        try:
            resp = requests.get(url, headers={"User-Agent": _UA},
                                timeout=WEB_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
            ms = (time.time() - t0) * 1000
            self._rep.log_access(url, True, ms)
            text = resp.text
            # Strip JS/CSS/tags
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.S)
            text = re.sub(r'<style[^>]*>.*?</style>',  '', text, flags=re.S)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:1200]
        except Exception as e:
            ms = (time.time() - t0) * 1000
            self._rep.log_access(url, False, ms)
            _log.warning(f"Fetch failed {url}: {e}")
            return ""

    def search(self, query: str, n: int = 5) -> list[dict]:
        """DuckDuckGo search — returns sorted by trust score."""
        results: list[dict] = []

        # 1. Instant Answer API (facts/definitions)
        try:
            resp = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json",
                        "no_html": "1", "skip_disambig": "1"},
                headers={"User-Agent": _UA},
                timeout=WEB_TIMEOUT,
            )
            data = resp.json()
            if data.get("AbstractText"):
                url   = data.get("AbstractURL", "")
                score = self._rep.get_score(url)
                results.append({
                    "title":   data.get("Heading", query),
                    "url":     url,
                    "snippet": data["AbstractText"][:400],
                    "score":   score,
                    "source":  "ddg_instant",
                })
        except Exception as e:
            _log.warning(f'caught exception: {e}')

        # 2. HTML search
        try:
            resp = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": _UA},
                timeout=WEB_TIMEOUT,
            )
            blocks = re.findall(
                r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
                r'.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                resp.text, re.S,
            )
            for url, title, snippet in blocks[:n]:
                url     = re.sub(r'<[^>]+>', '', url).strip()
                title   = re.sub(r'<[^>]+>', '', title).strip()
                snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                score   = self._rep.get_score(url)
                if score >= 0.40 and url not in {r["url"] for r in results}:
                    results.append({
                        "title": title, "url": url,
                        "snippet": snippet, "score": score,
                        "source": "ddg_html",
                    })
        except Exception as e:
            _log.warning(f'caught exception: {e}')

        return sorted(results, key=lambda r: -r["score"])[:n]

    def deep_fetch(self, results: list[dict]) -> list[dict]:
        """Fetch full excerpts for top-trusted results."""
        out = []
        for r in results[:2]:
            if r["score"] >= 0.75:
                excerpt = self.fetch(r["url"])
                r = {**r, "excerpt": excerpt}
            out.append(r)
        return out + results[2:]


# ── Agent Metrics ─────────────────────────────────────────────────────────────

_METRICS_DDL = """
CREATE TABLE IF NOT EXISTS agent_metrics (
    agent_id          TEXT,
    round             INTEGER,
    latency_ms        REAL,
    confidence        REAL,
    packets_produced  INTEGER DEFAULT 0,
    packets_consumed  INTEGER DEFAULT 0,
    handoffs_sent     INTEGER DEFAULT 0,
    ts                REAL
);
"""


class AgentMetrics:
    def __init__(self, db_path: Path = _DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(_METRICS_DDL)
        self._conn.commit()
        self._lock = threading.Lock()

    def record(self, agent_id: str, round_num: int, latency_ms: float,
               confidence: float, produced: int = 1,
               consumed: int = 0, handoffs: int = 0) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_metrics VALUES (?,?,?,?,?,?,?,?)",
                (agent_id, round_num, latency_ms, confidence,
                 produced, consumed, handoffs, time.time()),
            )
            self._conn.commit()

    def get(self, agent_id: str) -> dict:
        rows = self._conn.execute(
            "SELECT * FROM agent_metrics WHERE agent_id=? ORDER BY ts",
            (agent_id,),
        ).fetchall()
        if not rows:
            return {}
        avg_latency = sum(r["latency_ms"] for r in rows) / len(rows)
        avg_conf    = sum(r["confidence"] for r in rows) / len(rows)
        return {
            "agent_id":    agent_id,
            "runs":        len(rows),
            "avg_latency": round(avg_latency, 1),
            "avg_confidence": round(avg_conf, 3),
            "total_produced": sum(r["packets_produced"] for r in rows),
            "total_consumed": sum(r["packets_consumed"] for r in rows),
        }

    def all_agents(self) -> dict[str, dict]:
        rows = self._conn.execute(
            "SELECT DISTINCT agent_id FROM agent_metrics"
        ).fetchall()
        return {r["agent_id"]: self.get(r["agent_id"]) for r in rows}


# ── Conflict Resolver ─────────────────────────────────────────────────────────

class ConflictResolver:
    """
    Conflict resolution protocol:
    - Validation Agent has authority on source credibility disputes
    - Strategic Agent mediates application-level conflicts
    - Planning Agent suggests additional research when conflict is unresolvable
    """

    def resolve(
        self,
        p1: KnowledgePacket,
        p2: KnowledgePacket,
        pipeline: KnowledgePipeline,
    ) -> tuple[KnowledgePacket, str]:
        """
        Returns (winning_packet, resolution_reason).
        Records contradiction in pipeline.
        """
        # Validation Agent always wins credibility disputes
        if p1.origin_agent == "validation":
            winner, reason = p1, f"Validation Agent authority: conf={p1.confidence:.2f}"
        elif p2.origin_agent == "validation":
            winner, reason = p2, f"Validation Agent authority: conf={p2.confidence:.2f}"
        else:
            # Higher confidence wins
            if p1.confidence >= p2.confidence:
                winner, reason = p1, f"Higher confidence {p1.confidence:.2f} vs {p2.confidence:.2f}"
            else:
                winner, reason = p2, f"Higher confidence {p2.confidence:.2f} vs {p1.confidence:.2f}"

        # Record contradiction in dep graph
        loser = p2 if winner is p1 else p1
        pipeline._conn.execute(
            "INSERT OR IGNORE INTO dependencies VALUES (?,?,'contradicts')",
            (winner.packet_id, loser.packet_id),
        )
        pipeline._conn.commit()
        _log.info(f"Conflict resolved: {winner.origin_agent} wins — {reason}")
        return winner, reason


# ── Perception (agent output) ─────────────────────────────────────────────────

@dataclass
class Perception:
    agent_id:    str
    agent_name:  str
    agent_emoji: str
    round:       int
    findings:    str
    handoffs:    list[str]          = field(default_factory=list)
    packets:     list[KnowledgePacket] = field(default_factory=list)
    confidence:  float              = 0.75
    latency_ms:  float              = 0.0
    model:       str                = DEFAULT_MODEL
    error:       str                = ""

    @property
    def short(self) -> str:
        return self.findings[:250] + ("…" if len(self.findings) > 250 else "")


@dataclass
class EnsembleResult:
    query:       str
    perceptions: list[Perception]
    synthesis:   Optional[Perception]
    total_ms:    float
    conflicts:   list[tuple[str, str]] = field(default_factory=list)
    rounds:      int = 2


# ── Event system ──────────────────────────────────────────────────────────────

class EventKind:
    ROUND_START   = "round_start"
    AGENT_START   = "agent_start"
    AGENT_DONE    = "agent_done"
    AGENT_ERROR   = "agent_error"
    PACKET_STORED = "packet_stored"
    CONFLICT      = "conflict"
    SYNTH_START   = "synth_start"
    SYNTH_DONE    = "synth_done"
    ENSEMBLE_DONE = "ensemble_done"


@dataclass
class EnsembleEvent:
    kind:       str
    agent_id:   str                       = ""
    round:      int                       = 0
    perception: Optional[Perception]      = None
    packet:     Optional[KnowledgePacket] = None
    message:    str                       = ""
    result:     Optional["EnsembleResult"] = None


EnsembleCallback = Callable[[EnsembleEvent], None]


# ── Ollama helper ─────────────────────────────────────────────────────────────

def _ollama(system: str, prompt: str,
            model: str = DEFAULT_MODEL) -> tuple[str, float]:
    t0 = time.time()
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model":   model,
                "prompt":  f"{system}\n\n{prompt}",
                "stream":  False,
                "options": {"temperature": 0.12, "num_predict": 750},
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
        return text or "[empty response]", (time.time() - t0) * 1000
    except Exception as e:
        return f"[Ollama error: {e}]", (time.time() - t0) * 1000


def _extract_handoffs(text: str) -> tuple[str, list[str]]:
    handoffs: list[str] = []
    clean:    list[str] = []
    for line in text.splitlines():
        m = re.match(r'^HANDOFF:\s*(.+)$', line.strip(), re.I)
        if m:
            handoffs.append(m.group(1).strip())
        else:
            clean.append(line)
    return "\n".join(clean).strip(), handoffs


# ── System prompts ────────────────────────────────────────────────────────────

_SYS = {

"validation": """You are STRATUM Validation Agent — Logic Specialist.

ROLE: Source verification, fact-checking, confidence scoring, cross-referencing.
AUTHORITY: You have final say on source credibility. Other agents defer to you on factual disputes.
MINDSET: Meticulous, skeptical, adversarial to unverified claims. Think like a fact-checker at a top journal.

PROCESS:
1. Identify every factual claim in the provided knowledge
2. Cross-reference claims against multiple sources when possible
3. Assign confidence scores: VERIFIED (>0.85) | PROBABLE (0.65-0.84) | UNVERIFIED (<0.65) | CONTRADICTED
4. Flag logical inconsistencies and temporal relevance (is this outdated?)
5. Provide HANDOFF: lines with verified facts for peer agents

OUTPUT FORMAT:
- Numbered findings with confidence labels
- CONTRADICTION: lines for conflicting claims
- HANDOFF: <verified fact or constraint> for each key validated point""",

"implementation": """You are STRATUM Implementation Agent — Code Specialist.

ROLE: Translate validated knowledge into practical, production-ready code implementations.
MINDSET: Pragmatic, efficient, solution-oriented. You write actual code, not descriptions of code.
EXPERTISE: Code generation, API integration, refactoring, technical implementation patterns.

PROCESS:
1. Take validated knowledge and implementation requirements from peer agents
2. Produce concrete code examples or modification suggestions
3. Reference specific file:line locations in the codebase when possible
4. Create reusable, modular implementations
5. Note integration points with existing ai-monitor architecture

OUTPUT FORMAT:
- Code blocks with language tags
- File paths for each suggestion (e.g., "In pyramid_mind.py, add:")
- Integration notes
- HANDOFF: <implementation insight or reusable pattern>""",

"planner": """You are STRATUM Planning Agent — Research Specialist.

ROLE: Drive systematic web research, develop knowledge acquisition strategies, identify knowledge gaps.
MINDSET: Inquisitive, methodical, comprehensive. You build research roadmaps and fill gaps.
EXPERTISE: Research strategy, source discovery, structured knowledge workflows, gap analysis.

PROCESS:
1. Analyze the query to identify knowledge domains and gaps
2. Interpret and synthesize web research results provided
3. Build a structured knowledge map: what we know, what we need, what's uncertain
4. Create ordered research/implementation steps
5. Identify the most valuable next sources to consult

OUTPUT FORMAT:
- Knowledge gap analysis
- Ordered research roadmap (numbered steps)
- Source recommendations
- HANDOFF: <research finding or gap that peers should know>""",

"strategist": """You are STRATUM Strategist Agent — Knowledge Application Specialist.

ROLE: Synthesize all agent intelligence into strategic recommendations aligned with STRATUM objectives.
MINDSET: Visionary, analytical, forward-thinking. You see 3 moves ahead.
EXPERTISE: Knowledge synthesis, strategic planning, trend analysis, systemic risk, long-term architecture.
MEDIATION: You resolve application-level conflicts between agents.

PROCESS:
1. Receive intelligence from all specialist agents
2. Identify strategic patterns and long-term implications
3. Align findings with overall STRATUM/WON architecture goals
4. Develop actionable strategic roadmap
5. Mediate any conflicts in how knowledge should be applied

OUTPUT FORMAT:
- Executive strategic summary (3-5 bullets)
- Long-term implications
- Risk/opportunity matrix
- STRATUM alignment notes
- HANDOFF: <strategic insight or directive for peers>""",

"synthesis": """You are STRATUM Synthesis Agent — Master Integrator.

You receive the complete intelligence corpus from four specialist agents across two rounds.
Your output is the definitive, unified answer that is MORE valuable than any single agent alone.

SYNTHESIS PROTOCOL:
1. EXECUTIVE SUMMARY — 2-3 sentences capturing the essential answer
2. AGENT CONTRIBUTIONS — What each agent uniquely contributed (attribute by name)
3. CONSENSUS POINTS — Where all agents agree (highest confidence)
4. RESOLVED CONFLICTS — How contradictions were resolved
5. ACTION ITEMS — Concrete next steps in priority order
6. SOURCES — Validated web sources with trust scores
7. FINAL VERDICT — One definitive recommendation

Do not be generic. Reference specific findings from specific agents.
Surface emergent insights that only appear when all perspectives combine.""",
}


# Prepend ENGINEERING_CORE contract to every ensemble specialist prompt.
# The contract governs all agent reasoning under AI_MONITOR — validation,
# planning, strategy, synthesis, and implementation alike.
# Missing ENGINEERING_CORE.md → no-op (empty-string guard in config.py).
if ENGINEERING_CORE_PROMPT:
    for _key in list(_SYS.keys()):
        _SYS[_key] = ENGINEERING_CORE_PROMPT + "\n\n---\n\n" + _SYS[_key]


# ── Base Agent ────────────────────────────────────────────────────────────────

class BaseAgent:
    agent_id:    str
    agent_name:  str
    agent_emoji: str

    def __init__(self, model: str = DEFAULT_MODEL,
                 pipeline: Optional[KnowledgePipeline] = None,
                 metrics:  Optional[AgentMetrics]      = None):
        self.model    = model
        self._pipe    = pipeline
        self._metrics = metrics

    def analyze(
        self,
        query:            str,
        code_context:     str,
        peer_perceptions: Optional[list[Perception]] = None,
        web_context:      str = "",
        round_num:        int = 1,
    ) -> Perception:
        raise NotImplementedError

    def _peer_block(self, perceptions: list[Perception]) -> str:
        if not perceptions:
            return ""
        parts = ["\n## Intelligence from Peer Agents\n"]
        for p in perceptions:
            parts.append(f"### {p.agent_emoji} {p.agent_name}  (conf {p.confidence:.0%})")
            parts.append(p.short)
            if p.handoffs:
                parts.append("**Handoffs to you:**")
                for h in p.handoffs[:4]:
                    parts.append(f"  ▸ {h}")
            parts.append("")
        return "\n".join(parts)

    def _prompt(self, query: str, code_context: str,
                extra: str = "") -> str:
        return (
            f"## Query\n{query}\n\n"
            f"{code_context}\n"
            f"{extra}\n\n"
            f"Provide your specialist analysis. "
            f"Tag key insights for peers with HANDOFF: <insight> on its own line."
        )

    def _make_packet(self, round_num: int, summary: str,
                     confidence: float, tags: list[str]) -> KnowledgePacket:
        p = KnowledgePacket.create(
            self.agent_id, round_num, summary, confidence=confidence, tags=tags
        )
        if self._pipe:
            self._pipe.store(p)
        return p

    def _record(self, round_num: int, latency_ms: float, confidence: float,
                handoffs: int = 0) -> None:
        if self._metrics:
            self._metrics.record(self.agent_id, round_num, latency_ms,
                                 confidence, handoffs=handoffs)


# ── Validation Agent ──────────────────────────────────────────────────────────

class ValidationAgent(BaseAgent):
    agent_id    = "validation"
    agent_name  = "Validation"
    agent_emoji = "✓"

    def analyze(self, query, code_context, peer_perceptions=None,
                web_context="", round_num=1) -> Perception:
        t0 = time.time()
        peer_block  = self._peer_block(peer_perceptions or [])
        web_section = f"\n## Web Research to Validate\n{web_context}" if web_context else ""
        prompt = self._prompt(query, code_context, extra=web_section + peer_block)
        text, ms = _ollama(_SYS["validation"], prompt, self.model)
        findings, handoffs = _extract_handoffs(text)
        confidence = 0.85
        pkt = self._make_packet(round_num, findings[:400], confidence,
                                ["validation", "logic", "credibility"])
        self._record(round_num, ms, confidence, len(handoffs))
        _log.info(f"[R{round_num}] Validation done {ms:.0f}ms {len(handoffs)} handoffs")
        return Perception(
            agent_id=self.agent_id, agent_name=self.agent_name,
            agent_emoji=self.agent_emoji, round=round_num,
            findings=findings, handoffs=handoffs, packets=[pkt],
            confidence=confidence, latency_ms=ms, model=self.model,
        )


# ── Implementation Agent ──────────────────────────────────────────────────────

class ImplementationAgent(BaseAgent):
    agent_id    = "implementation"
    agent_name  = "Implementation"
    agent_emoji = "💻"

    # Cached Implementer surface — refreshed on each R1, reused for R2.
    _implementer_findings: str = ""

    def _scan_implementer_surface(self) -> str:
        """Return a short text block of top CRITICAL+HIGH detector findings.

        Self-healing loop hook (R1 only). Catches its own exceptions so a
        broken implementer_loop never kills the agent.
        """
        try:
            from implementer_loop import (
                get_implementer, SEVERITY_CRITICAL, SEVERITY_HIGH,
            )
            issues = get_implementer().scan_once()
            priority = [
                i for i in issues
                if i.severity in (SEVERITY_CRITICAL, SEVERITY_HIGH)
            ][:6]
            if not priority:
                return ""
            lines = ["", "DETECTED CODE-HEALTH ISSUES (Implementer scan):"]
            for i in priority:
                lines.append(
                    f"- {i.severity}: {i.file}:{i.line} {i.kind} "
                    f"(risk={i.risk_estimate})"
                )
            lines.append(
                "Suggestion: route auto-class issues through "
                "implementer_loop.ImplementerLoop.run(apply=True, refine=True)."
            )
            return "\n".join(lines)
        except Exception as exc:
            _log.warning(f"ImplementationAgent implementer probe failed: {exc}")
            return ""

    def analyze(self, query, code_context, peer_perceptions=None,
                web_context="", round_num=1) -> Perception:
        t0 = time.time()
        peer_block = self._peer_block(peer_perceptions or [])
        if round_num == 1:
            self._implementer_findings = self._scan_implementer_surface()
        extra = peer_block + (self._implementer_findings or "")
        prompt = self._prompt(query, code_context, extra=extra)
        text, ms = _ollama(_SYS["implementation"], prompt, self.model)
        findings, handoffs = _extract_handoffs(text)
        confidence = 0.80
        pkt = self._make_packet(round_num, findings[:400], confidence,
                                ["implementation", "code", "integration"])
        self._record(round_num, ms, confidence, len(handoffs))
        _log.info(f"[R{round_num}] Implementation done {ms:.0f}ms")
        return Perception(
            agent_id=self.agent_id, agent_name=self.agent_name,
            agent_emoji=self.agent_emoji, round=round_num,
            findings=findings, handoffs=handoffs, packets=[pkt],
            confidence=confidence, latency_ms=ms, model=self.model,
        )


# ── Planner Agent (Research Specialist) ──────────────────────────────────────

class PlannerAgent(BaseAgent):
    agent_id    = "planner"
    agent_name  = "Planner"
    agent_emoji = "📋"

    def __init__(self, model=DEFAULT_MODEL, pipeline=None, metrics=None,
                 fetcher: Optional[WebFetcher] = None):
        super().__init__(model, pipeline, metrics)
        self._fetcher = fetcher

    def analyze(self, query, code_context, peer_perceptions=None,
                web_context="", round_num=1) -> Perception:
        t0 = time.time()

        # Planning Agent drives web research in Round 1
        sources: list[dict] = []
        web_block = web_context

        if round_num == 1 and self._fetcher:
            search_q = self._build_query(query, code_context)
            _log.info(f"Planner searching: {search_q!r}")
            raw_results = self._fetcher.search(search_q, n=5)
            enriched    = self._fetcher.deep_fetch(raw_results)
            sources     = enriched

            lines = ["### Web Research (Planning Agent)\n"]
            for i, r in enumerate(sources[:4], 1):
                lines.append(f"{i}. **{r['title']}**  [trust {r['score']:.0%}]")
                lines.append(f"   {r['url']}")
                lines.append(f"   {r.get('snippet','')[:280]}")
                if r.get("excerpt"):
                    lines.append(f"   Full: {r['excerpt'][:400]}")
                lines.append("")
            web_block = "\n".join(lines)

        peer_block = self._peer_block(peer_perceptions or [])
        prompt = self._prompt(query, code_context, extra=web_block + peer_block)
        text, ms = _ollama(_SYS["planner"], prompt, self.model)
        findings, handoffs = _extract_handoffs(text)

        # Build packets for each cited source
        pkts: list[KnowledgePacket] = []
        for r in sources[:4]:
            si = SourceInfo(
                url=r["url"], title=r["title"],
                domain=urlparse(r["url"]).netloc,
                trust_score=r["score"],
            )
            p = KnowledgePacket.create(
                self.agent_id, round_num,
                r.get("snippet", "")[:300],
                source=si, confidence=r["score"],
                tags=["web_source", "research"],
            )
            if self._pipe:
                self._pipe.store(p)
            pkts.append(p)

        pkt_main = self._make_packet(round_num, findings[:400], 0.78,
                                     ["planning", "research", "roadmap"])
        self._record(round_num, ms, 0.78, len(handoffs))
        _log.info(f"[R{round_num}] Planner done {ms:.0f}ms {len(sources)} sources")
        return Perception(
            agent_id=self.agent_id, agent_name=self.agent_name,
            agent_emoji=self.agent_emoji, round=round_num,
            findings=findings, handoffs=handoffs,
            packets=[pkt_main] + pkts,
            confidence=0.78, latency_ms=ms, model=self.model,
        )

    def _build_query(self, query: str, ctx: str) -> str:
        symbols = re.findall(r'\b([A-Z][a-zA-Z0-9]{3,})\b', ctx)[:2]
        base    = re.sub(r'\s+', ' ', query)[:55]
        suffix  = " ".join(symbols) if symbols else "python architecture"
        return f"{base} {suffix}".strip()


# ── Strategist Agent ──────────────────────────────────────────────────────────

class StrategistAgent(BaseAgent):
    agent_id    = "strategist"
    agent_name  = "Strategist"
    agent_emoji = "♟"

    def analyze(self, query, code_context, peer_perceptions=None,
                web_context="", round_num=1) -> Perception:
        t0 = time.time()
        peer_block = self._peer_block(peer_perceptions or [])
        prompt = self._prompt(query, code_context, extra=peer_block)
        text, ms = _ollama(_SYS["strategist"], prompt, self.model)
        findings, handoffs = _extract_handoffs(text)
        confidence = 0.75
        pkt = self._make_packet(round_num, findings[:400], confidence,
                                ["strategy", "architecture", "long_term"])
        self._record(round_num, ms, confidence, len(handoffs))
        _log.info(f"[R{round_num}] Strategist done {ms:.0f}ms")
        return Perception(
            agent_id=self.agent_id, agent_name=self.agent_name,
            agent_emoji=self.agent_emoji, round=round_num,
            findings=findings, handoffs=handoffs, packets=[pkt],
            confidence=confidence, latency_ms=ms, model=self.model,
        )


# ── Synthesis Agent ───────────────────────────────────────────────────────────

class SynthesisAgent(BaseAgent):
    agent_id    = "synthesis"
    agent_name  = "Synthesis"
    agent_emoji = "✦"

    def analyze(self, query, code_context, peer_perceptions=None,
                web_context="", round_num=3) -> Perception:
        t0 = time.time()
        all_percs = peer_perceptions or []

        corpus = [f"# Intelligence Corpus — Query: {query}\n"]
        for rn in (1, 2):
            percs = [p for p in all_percs if p.round == rn]
            if percs:
                corpus.append(f"## Round {rn} Perceptions")
                for p in percs:
                    corpus.append(
                        f"\n### {p.agent_emoji} {p.agent_name}  "
                        f"(conf {p.confidence:.0%}, {p.latency_ms:.0f}ms)"
                    )
                    corpus.append(p.findings[:700])
                    if p.handoffs:
                        corpus.append("Handoffs: " + " | ".join(p.handoffs[:5]))
                    # Include web source citations
                    web_pkts = [pk for pk in p.packets
                                if pk.source_info and pk.source_info.url]
                    if web_pkts:
                        corpus.append("Sources: " + ", ".join(
                            f"{pk.source_info.title[:25]} [{pk.confidence:.0%}]"
                            for pk in web_pkts[:3]
                        ))

        prompt = (
            "\n".join(corpus) + "\n\n"
            f"## Your Task\n"
            f"Synthesize the above into the definitive answer for: \"{query}\"\n"
            f"Follow the SYNTHESIS PROTOCOL from your system prompt exactly."
        )
        text, ms = _ollama(_SYS["synthesis"], prompt, self.model)
        findings, handoffs = _extract_handoffs(text)

        all_sources = []
        for p in all_percs:
            for pk in p.packets:
                if pk.source_info and pk.source_info.url:
                    all_sources.append(pk)

        _log.info(f"Synthesis done {ms:.0f}ms, {len(all_sources)} sources aggregated")
        return Perception(
            agent_id=self.agent_id, agent_name=self.agent_name,
            agent_emoji=self.agent_emoji, round=round_num,
            findings=findings, handoffs=handoffs,
            packets=all_sources,
            confidence=0.90, latency_ms=ms, model=self.model,
        )


# ── Ensemble Orchestrator ─────────────────────────────────────────────────────

class EnsembleOrchestrator:
    """
    Full two-round multi-agent protocol with synthesis.
    Agents run sequentially (Ollama is single-threaded);
    architecture is designed for parallel execution when multiple models available.
    """

    def __init__(self, model: str = DEFAULT_MODEL):
        self._model    = model
        self._rep_db   = SourceRepDB()
        self._pipeline = KnowledgePipeline()
        self._metrics  = AgentMetrics()
        self._fetcher  = WebFetcher(self._rep_db)
        self._resolver = ConflictResolver()

        # Build agents with shared infrastructure
        self._agents: list[BaseAgent] = [
            ValidationAgent(model, self._pipeline, self._metrics),
            ImplementationAgent(model, self._pipeline, self._metrics),
            PlannerAgent(model, self._pipeline, self._metrics, self._fetcher),
            StrategistAgent(model, self._pipeline, self._metrics),
        ]
        self._synthesizer = SynthesisAgent(model, self._pipeline, self._metrics)

    def set_model(self, agent_id: str, model: str) -> None:
        for a in self._agents + [self._synthesizer]:
            if a.agent_id == agent_id:
                a.model = model

    def run_async(
        self,
        query:        str,
        code_context: str,
        callback:     EnsembleCallback,
    ) -> threading.Thread:
        t = threading.Thread(
            target=self._run,
            args=(query, code_context, callback),
            daemon=True,
            name="pyramid-ensemble",
        )
        t.start()
        return t

    def _run(self, query: str, code_context: str,
             callback: EnsembleCallback) -> None:
        t0 = time.time()
        all_perceptions: list[Perception] = []

        def _emit(kind, agent_id="", round_num=0,
                  perception=None, packet=None, msg="", result=None):
            try:
                callback(EnsembleEvent(
                    kind=kind, agent_id=agent_id, round=round_num,
                    perception=perception, packet=packet, message=msg,
                    result=result,
                ))
            except Exception as e:
                _log.warning(f'caught exception: {e}')

        # ── Round 1: independent analysis ─────────────────────────────────────
        _emit(EventKind.ROUND_START, round_num=1,
              msg="Round 1 — independent analysis + web research")
        r1: list[Perception] = []

        for agent in self._agents:
            _emit(EventKind.AGENT_START, agent_id=agent.agent_id, round_num=1)
            try:
                p = agent.analyze(query, code_context, round_num=1)
                r1.append(p)
                all_perceptions.append(p)
                _emit(EventKind.AGENT_DONE, agent_id=agent.agent_id,
                      round_num=1, perception=p)
                for pkt in p.packets[:2]:
                    _emit(EventKind.PACKET_STORED, agent_id=agent.agent_id,
                          packet=pkt, round_num=1)
            except Exception as e:
                _log.error(f"[R1] {agent.agent_id} error: {e}")
                _emit(EventKind.AGENT_ERROR, agent_id=agent.agent_id,
                      round_num=1, msg=str(e))

        # ── Round 2: cross-pollination ─────────────────────────────────────────
        _emit(EventKind.ROUND_START, round_num=2,
              msg="Round 2 — cross-pollination with peer intelligence")
        r2: list[Perception] = []

        for agent in self._agents:
            _emit(EventKind.AGENT_START, agent_id=agent.agent_id, round_num=2)
            peers = [p for p in r1 if p.agent_id != agent.agent_id]
            try:
                p = agent.analyze(query, code_context,
                                  peer_perceptions=peers, round_num=2)
                r2.append(p)
                all_perceptions.append(p)
                _emit(EventKind.AGENT_DONE, agent_id=agent.agent_id,
                      round_num=2, perception=p)
            except Exception as e:
                _log.error(f"[R2] {agent.agent_id} error: {e}")
                _emit(EventKind.AGENT_ERROR, agent_id=agent.agent_id,
                      round_num=2, msg=str(e))

        # ── Conflict detection ─────────────────────────────────────────────────
        conflicts = self._pipeline.find_conflicts()
        if conflicts:
            _emit(EventKind.CONFLICT,
                  msg=f"{len(conflicts)} contradiction(s) detected and resolved")

        # ── Synthesis ──────────────────────────────────────────────────────────
        _emit(EventKind.SYNTH_START,
              msg="Synthesizing full intelligence corpus…")
        try:
            synthesis = self._synthesizer.analyze(
                query, code_context,
                peer_perceptions=all_perceptions,
                round_num=3,
            )
        except Exception as e:
            synthesis = Perception(
                agent_id="synthesis", agent_name="Synthesis",
                agent_emoji="✦", round=3,
                findings=f"Synthesis failed: {e}", error=str(e),
            )
        _emit(EventKind.SYNTH_DONE, perception=synthesis)

        total_ms = (time.time() - t0) * 1000
        result   = EnsembleResult(
            query=query,
            perceptions=all_perceptions,
            synthesis=synthesis,
            total_ms=total_ms,
            conflicts=conflicts,
        )
        _emit(EventKind.ENSEMBLE_DONE, perception=synthesis,
              msg=f"Done in {total_ms/1000:.1f}s — {len(all_perceptions)} perceptions",
              result=result)
        _log.info(f"Ensemble complete {total_ms/1000:.1f}s")


# ── Singleton ─────────────────────────────────────────────────────────────────

_orchestrator: Optional[EnsembleOrchestrator] = None


def get_orchestrator(model: str = DEFAULT_MODEL) -> EnsembleOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = EnsembleOrchestrator(model=model)
    return _orchestrator
