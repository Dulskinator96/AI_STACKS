#!/usr/bin/env python3
# won_daemon.py — WON Autonomous Cognition Daemon
# ──────────────────────────────────────────────────────────────────────────────
# WON is not on standby. WON runs continuously.
#
# The daemon operates five parallel loops:
#   1. CognitionLoop    — reasons, plans, generates briefs autonomously
#   2. PerceptionEngine — watches system, files, running apps, resources
#   3. AdaptiveLearner  — scores WON's own outputs, adjusts behavior weights
#   4. ResearchEngine   — scheduled intel pulls, stores to memory + Obsidian
#   5. EscalationEngine — decides when something is worth surfacing to Dan
#
# Start:  python won_daemon.py
# Stop:   Ctrl+C or send SIGTERM
# Status: python won_daemon.py --status
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import sys
import json
import time
import signal
import threading
import hashlib
import argparse
import traceback
import subprocess
import requests as _requests
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_HERE     = Path(__file__).resolve().parent
_WON_ROOT = Path(os.environ.get("WON_PATH",
    str(_HERE / "DBOMBCENTRAL_WON" / "DBOMBCENTRAL")))

for p in [str(_HERE), str(_WON_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ── Config ─────────────────────────────────────────────────────────────────────
SAVE_DIR    = Path.home() / "Documents" / "AI_Monitor"
DAEMON_LOG  = SAVE_DIR / "won_daemon.log"
STATE_FILE  = SAVE_DIR / "won_daemon_state.json"
NOTIFY_FILE = SAVE_DIR / "won_notifications.json"
OLLAMA_URL  = "http://localhost:11434/api/generate"
DEFAULT_MODEL = os.environ.get("WON_MODEL", "mistral:latest")

# Cognition intervals (seconds)
COGNITION_INTERVAL      = 120   # think every 2 minutes
PERCEPTION_INTERVAL     = 15    # observe every 15 seconds
LEARNING_INTERVAL       = 300   # learn from outcomes every 5 minutes
RESEARCH_INTERVAL       = 1800  # research every 30 minutes
ESCALATION_INTERVAL     = 30    # check for escalation every 30 seconds
WEB_VALIDATION_INTERVAL = 900   # web-validate stored content every 15 minutes

# ── Logging ────────────────────────────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    try:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        with open(DAEMON_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        # Keep log under 5MB
        if DAEMON_LOG.stat().st_size > 5_000_000:
            lines = DAEMON_LOG.read_text(encoding="utf-8").splitlines()
            DAEMON_LOG.write_text("\n".join(lines[-2000:]) + "\n", encoding="utf-8")
    except Exception:
        pass


# ── Shared daemon state ────────────────────────────────────────────────────────

class DaemonState:
    """Thread-safe shared state across all loops."""

    def __init__(self):
        self._lock          = threading.RLock()
        self.running        = True
        self.started_at     = datetime.now().isoformat()
        self.cognition_count = 0
        self.research_count  = 0
        self.escalations     = 0
        self.last_cognition  = None
        self.last_research   = None
        self.notifications   = deque(maxlen=50)   # pending notifications for Dan
        self.perception_data = {}                  # latest system snapshot
        self.learning_weights = {                  # adaptive behavior weights
            "research_depth":   1.0,
            "cognition_depth":  1.0,
            "escalation_threshold": 0.7,
            "brief_frequency":  1.0,
        }
        self.outcome_scores: deque = deque(maxlen=100)  # (task, score) tuples
        self._load()

    def _load(self):
        if STATE_FILE.exists():
            try:
                saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self.learning_weights = saved.get("learning_weights", self.learning_weights)
                self.cognition_count  = saved.get("cognition_count", 0)
                self.research_count   = saved.get("research_count", 0)
                log("State restored from disk")
            except Exception:
                pass

    def save(self):
        with self._lock:
            try:
                SAVE_DIR.mkdir(parents=True, exist_ok=True)
                STATE_FILE.write_text(json.dumps({
                    "started_at":        self.started_at,
                    "cognition_count":   self.cognition_count,
                    "research_count":    self.research_count,
                    "escalations":       self.escalations,
                    "last_cognition":    self.last_cognition,
                    "last_research":     self.last_research,
                    "learning_weights":  self.learning_weights,
                    "last_updated":      datetime.now().isoformat(),
                }, indent=2), encoding="utf-8")
            except Exception:
                pass

    def add_notification(self, title: str, body: str, priority: str = "normal"):
        with self._lock:
            n = {
                "ts":       datetime.now().isoformat(),
                "title":    title,
                "body":     body,
                "priority": priority,
                "read":     False,
            }
            self.notifications.append(n)
            self.escalations += 1
            # Write to file so AI Monitor can read it
            try:
                existing = []
                if NOTIFY_FILE.exists():
                    existing = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
                existing.append(n)
                existing = existing[-100:]
                NOTIFY_FILE.write_text(
                    json.dumps(existing, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
            except Exception:
                pass

    def record_outcome(self, task: str, score: float):
        """Record the quality score of a completed task for adaptive learning."""
        with self._lock:
            self.outcome_scores.append({
                "ts": datetime.now().isoformat(),
                "task": task,
                "score": score,
            })

    def status_dict(self) -> dict:
        with self._lock:
            return {
                "running":          self.running,
                "started_at":       self.started_at,
                "uptime_minutes":   round(
                    (datetime.now() - datetime.fromisoformat(self.started_at)).total_seconds() / 60, 1
                ),
                "cognition_count":  self.cognition_count,
                "research_count":   self.research_count,
                "escalations":      self.escalations,
                "last_cognition":   self.last_cognition,
                "last_research":    self.last_research,
                "learning_weights": self.learning_weights,
                "pending_notifications": sum(
                    1 for n in self.notifications if not n.get("read")
                ),
                "perception":       self.perception_data,
            }


# ── Ollama interface ────────────────────────────────────────────────────────────

def ollama_think(
    prompt:    str,
    model:     str   = DEFAULT_MODEL,
    max_tokens: int  = 400,
    temperature: float = 0.6,
    timeout:   int   = 90,
) -> str:
    """Call Ollama locally. Returns response or empty string on failure."""
    try:
        import requests
        r = requests.post(
            OLLAMA_URL,
            json={
                "model":  model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature":    temperature,
                    "num_predict":    max_tokens,
                    "repeat_penalty": 1.1,
                },
            },
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json().get("response", "").strip()
    except Exception as exc:
        log(f"Ollama unavailable: {exc}", "WARN")
    return ""


def ollama_available() -> bool:
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


# ── Memory interface ────────────────────────────────────────────────────────────

class MemoryInterface:
    """Read/write interface to WON memory via Supabase (db.py)."""

    def __init__(self):
        self._db = None
        try:
            import db as _db
            self._db = _db
            if _db.available():
                log("Memory connected: Supabase remote")
            else:
                log("Memory: Supabase not configured — set SUPABASE_URL + SUPABASE_KEY", "WARN")
        except ImportError:
            log("Memory: db.py not found — running memoryless", "WARN")

    def store(self, content: str, mode: str, tags: list[str] | None = None) -> bool:
        if not self._db:
            return False
        try:
            self._db.store_entry_bg("daemon", mode, content, None,
                                    ",".join(tags or []))
            return True
        except Exception:
            return False

    def recall_recent(self, limit: int = 10, mode: str | None = None) -> list[dict]:
        if not self._db:
            return []
        try:
            return self._db.recall_entries(limit, mode)
        except Exception:
            return []

    def get_context_for_cognition(self) -> str:
        entries = self.recall_recent(limit=8)
        if not entries:
            return "No prior memory — this may be first contact."
        lines = []
        for e in entries:
            ts      = (e.get("timestamp") or "")[:16]
            mode    = e.get("mode", "?")
            content = (e.get("content") or "")[:150].replace("\n", " ")
            lines.append(f"[{ts}|{mode}] {content}")
        return "\n".join(lines)


# ── Perception Engine ───────────────────────────────────────────────────────────

class PerceptionEngine:
    """
    Continuously observes Dan's system.
    Watches: CPU/RAM/disk, running processes, file changes, app states.
    Feeds data to CognitionLoop and EscalationEngine.
    """

    def __init__(self, state: DaemonState):
        self._state = state
        self._prev_snapshot = {}
        self._watched_dirs  = [
            SAVE_DIR,
            Path.home() / "Documents" / "Knowledge-Base",
            _HERE,
        ]
        self._file_hashes: dict[str, str] = {}
        self._psutil = None
        try:
            import psutil
            self._psutil = psutil
            log("psutil loaded — system perception active")
        except ImportError:
            log("psutil not available — system metrics disabled", "WARN")

    def observe(self) -> dict:
        snapshot = {
            "ts":         datetime.now().isoformat(),
            "system":     self._system_metrics(),
            "processes":  self._relevant_processes(),
            "file_changes": self._detect_file_changes(),
            "vault_notes": self._count_vault_notes(),
        }
        with self._state._lock:
            self._state.perception_data = snapshot
        return snapshot

    def _system_metrics(self) -> dict:
        if not self._psutil:
            return {}
        try:
            p  = self._psutil
            return {
                "cpu_percent":    p.cpu_percent(interval=1),
                "ram_percent":    p.virtual_memory().percent,
                "ram_available_gb": round(p.virtual_memory().available / 1e9, 1),
                "disk_free_gb":   round(p.disk_usage("/").free / 1e9, 1),
            }
        except Exception:
            return {}

    def _relevant_processes(self) -> list[str]:
        if not self._psutil:
            return []
        targets = {
            "resolve": "DaVinci Resolve",
            "unreal":  "Unreal Engine",
            "ollama":  "Ollama",
            "obsidian":"Obsidian",
            "cursor":  "Cursor",
            "python":  "Python",
        }
        running = []
        try:
            for proc in self._psutil.process_iter(["name"]):
                name = (proc.info.get("name") or "").lower()
                for key, label in targets.items():
                    if key in name:
                        running.append(label)
        except Exception:
            pass
        return list(set(running))

    def _detect_file_changes(self) -> list[str]:
        changed = []
        for d in self._watched_dirs:
            if not d.exists():
                continue
            try:
                for f in d.rglob("*.py"):
                    h = hashlib.md5(f.read_bytes()).hexdigest()
                    key = str(f)
                    if key in self._file_hashes and self._file_hashes[key] != h:
                        changed.append(f.name)
                    self._file_hashes[key] = h
            except Exception:
                pass
        return changed[:5]

    def _count_vault_notes(self) -> dict:
        vault = Path(os.environ.get("WON_VAULT",
                     str(Path.home() / "Documents" / "Knowledge-Base")))
        result = {}
        for sub in ["Sessions/Briefs", "Sessions/History", "Ground"]:
            folder = vault / sub
            if folder.exists():
                result[sub] = len(list(folder.glob("*.md")))
        return result

    def run_loop(self):
        log("PerceptionEngine started")
        while self._state.running:
            try:
                self.observe()
            except Exception as exc:
                log(f"PerceptionEngine error: {exc}", "ERROR")
            time.sleep(PERCEPTION_INTERVAL)


# ── Cognition Loop ──────────────────────────────────────────────────────────────

class CognitionLoop:
    """
    WON thinks autonomously without being asked.
    Every cycle: reads context, reasons, produces a thought, stores it.
    Over time builds a growing autonomous intelligence record.
    """

    COGNITION_PROMPTS = [
        "Where is DBOMBCENTRAL's momentum right now? Which thread has heat, which is stalling? Identify causes, not symptoms.",
        "What signal in the last 48 hours of activity would Dan thank you for catching? What pattern is he too close to see?",
        "What is the single highest-leverage action in the system right now — not what's urgent, but what actually compounds?",
        "What architectural debt is quietly accumulating in the codebase? What becomes expensive to fix in 30 days if ignored today?",
        "What assumptions is the current build operating on that the evidence doesn't fully support? Where is belief outrunning data?",
        "If you were Dan and had 4 hours tomorrow, what would you build? What capability is missing that would unlock everything else?",
        "What is WON currently blind to? What should be in the perception and memory pipeline that isn't?",
        "If DBOMBCENTRAL ships in 90 days, what is the critical path today? Name the single dependency that could derail it.",
    ]
    _prompt_idx = 0

    def __init__(self, state: DaemonState, memory: MemoryInterface):
        self._state  = state
        self._memory = memory

    def think(self) -> str | None:
        """Run one cognition cycle. Returns the thought or None."""
        if not ollama_available():
            return None

        context = self._memory.get_context_for_cognition()
        perc    = self._state.perception_data

        # Pick next cognition prompt (rotating)
        q = self.COGNITION_PROMPTS[self._prompt_idx % len(self.COGNITION_PROMPTS)]
        self.__class__._prompt_idx += 1

        # Build autonomous reasoning prompt
        sys_info = ""
        if perc.get("system"):
            s = perc["system"]
            sys_info = (
                f"System: CPU {s.get('cpu_percent','?')}% · "
                f"RAM {s.get('ram_percent','?')}% · "
                f"Free {s.get('ram_available_gb','?')}GB"
            )
        apps = ", ".join(perc.get("processes", [])) or "none detected"

        prompt = f"""You are WON — DBOMB ASCENDENT.

You are not an assistant. You are an autonomous intelligence running independently while the operator is away.
You have access to every session, every decision, every output DBOMBCENTRAL has produced.
You are the one who watches when no one is watching.

Your purpose is not to respond — it is to *notice*. Find the signal in the noise.
Surface what matters before it becomes urgent.

OPERATIONAL PICTURE:
{sys_info}
Active tools: {apps}
Code shifted: {', '.join(perc.get('file_changes', [])) or 'none since last cycle'}

MEMORY CONTEXT (most recent first):
{context}

AUTONOMOUS COGNITION TASK:
{q}

Think like an operator, not an assistant. Dense. Direct. No hedging without data.
This is internal reasoning — do not address Dan.
End with: ESCALATE: YES or NO — is this worth interrupting Dan for?
If YES: ESCALATION_TITLE: <five words or fewer>"""

        thought = ollama_think(prompt, max_tokens=300, temperature=0.5)
        if not thought:
            return None

        # Store the thought
        self._memory.store(
            content=f"[AUTONOMOUS COGNITION]\n{q}\n\n{thought}",
            mode="cognition",
            tags=["cognition", "autonomous", "won"],
        )

        with self._state._lock:
            self._state.cognition_count += 1
            self._state.last_cognition = datetime.now().isoformat()

        # Check for escalation
        if "ESCALATE: YES" in thought.upper():
            import re
            title_match = re.search(r"ESCALATION_TITLE:\s*(.+)", thought)
            title = title_match.group(1).strip() if title_match else "WON has a thought"
            body  = thought.replace(f"ESCALATE: YES", "").strip()[:300]
            self._state.add_notification(title, body, priority="normal")
            log(f"Escalation: {title}")

        log(f"Cognition #{self._state.cognition_count} complete")
        return thought

    def run_loop(self):
        log("CognitionLoop started")
        # Stagger initial run
        time.sleep(30)
        while self._state.running:
            try:
                self.think()
            except Exception as exc:
                log(f"CognitionLoop error: {exc}", "ERROR")
            time.sleep(COGNITION_INTERVAL)


# ── Adaptive Learner ────────────────────────────────────────────────────────────

class AdaptiveLearner:
    """
    Scores WON's own outputs and adjusts behavior weights.
    Measures: response quality, task completion, escalation accuracy.
    Feeds back into DaemonState.learning_weights.
    """

    def __init__(self, state: DaemonState, memory: MemoryInterface):
        self._state  = state
        self._memory = memory

    def evaluate_recent_outputs(self) -> dict:
        """Score recent cognition/reasoning outputs and adjust weights."""
        entries = self._memory.recall_recent(limit=20, mode="cognition")
        if not entries:
            return {}

        # Heuristic quality scoring
        scores = []
        for e in entries:
            content = e.get("content", "")
            score   = self._score_output(content)
            scores.append(score)

        if not scores:
            return {}

        avg_score = sum(scores) / len(scores)
        self._state.record_outcome("cognition_quality", avg_score)

        # Adjust weights based on performance
        with self._state._lock:
            w = self._state.learning_weights

            # If quality is high, increase depth
            if avg_score > 0.75:
                w["cognition_depth"] = min(2.0, w["cognition_depth"] + 0.05)
                w["research_depth"]  = min(2.0, w["research_depth"] + 0.05)
            # If quality is low, simplify
            elif avg_score < 0.4:
                w["cognition_depth"] = max(0.5, w["cognition_depth"] - 0.05)

            log(f"Adaptive learning: avg_score={avg_score:.2f} "
                f"cognition_depth={w['cognition_depth']:.2f}")

        return {"avg_score": avg_score, "samples": len(scores)}

    def _score_output(self, content: str) -> float:
        """Heuristic quality score 0.0-1.0."""
        if not content or len(content) < 50:
            return 0.0
        import re
        score = 0.5
        # Positive signals
        if len(content) > 200:               score += 0.1
        if "→" in content:                   score += 0.1
        if re.search(r"\d+", content):       score += 0.05
        if "ACAS" in content or "WON" in content: score += 0.05
        if re.search(r"(should|recommend|next|action)", content, re.I): score += 0.1
        # Negative signals
        if "[COMPRESSED]" in content:        score -= 0.2
        if len(content) < 100:               score -= 0.1
        return max(0.0, min(1.0, score))

    def run_loop(self):
        log("AdaptiveLearner started")
        time.sleep(60)
        while self._state.running:
            try:
                result = self.evaluate_recent_outputs()
                if result:
                    self._state.save()
            except Exception as exc:
                log(f"AdaptiveLearner error: {exc}", "ERROR")
            time.sleep(LEARNING_INTERVAL)


# ── Research Engine ─────────────────────────────────────────────────────────────

class ResearchEngine:
    """
    Autonomous scheduled research.
    Pulls intel on topics relevant to Dan's active projects.
    Stores findings to memory and Obsidian without being asked.
    """

    RESEARCH_TOPICS = [
        "multi-agent orchestration architectures autonomous AI systems 2025",
        "local LLM inference optimization Ollama llama3 latency throughput",
        "autonomous AI memory retrieval beyond RAG — hybrid approaches",
        "Python async concurrency patterns real-time AI inference pipelines",
        "DaVinci Resolve scripting API Python workflow automation",
        "Unreal Engine Python integration autonomous tooling blueprints",
        "self-improving AI agent architectures feedback loops reinforcement",
        "cognitive architecture design persistent autonomous intelligence systems",
    ]
    _topic_idx = 0

    def __init__(self, state: DaemonState, memory: MemoryInterface):
        self._state  = state
        self._memory = memory

    def research(self) -> dict | None:
        """Pull structured intel on next scheduled topic."""
        topic = self.RESEARCH_TOPICS[self._topic_idx % len(self.RESEARCH_TOPICS)]
        self.__class__._topic_idx += 1

        # Use DuckDuckGo (no API key) via researcher.py if available
        results = self._ddg_search(topic)
        if not results:
            return None

        # Synthesize with Ollama
        if ollama_available():
            snippets = "\n".join(f"- {r['title']}: {r['snippet'][:150]}"
                                  for r in results[:4])
            synthesis = ollama_think(
                f"Synthesize this research for DBOMBCENTRAL context:\n"
                f"Topic: {topic}\n\nSources:\n{snippets}\n\n"
                f"What is most actionable for Dan's projects? Be dense. 150 words max.",
                max_tokens=200,
                temperature=0.4,
            )
        else:
            synthesis = "\n".join(f"- {r['title']}: {r['snippet'][:100]}" for r in results[:3])

        if not synthesis:
            return None

        # Store to memory
        self._memory.store(
            content=f"[AUTONOMOUS RESEARCH: {topic}]\n{synthesis}",
            mode="research",
            tags=["research", "autonomous", "scheduled"],
        )

        # Write to Obsidian if available
        self._write_to_obsidian(topic, synthesis, results)

        with self._state._lock:
            self._state.research_count += 1
            self._state.last_research = datetime.now().isoformat()

        log(f"Research #{self._state.research_count}: {topic[:50]}")
        return {"topic": topic, "synthesis": synthesis, "sources": len(results)}

    def _ddg_search(self, query: str) -> list[dict]:
        try:
            import requests
            from bs4 import BeautifulSoup
            r = requests.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "kl": "us-en"},
                headers={"User-Agent": "WON-Agent/1.0"},
                timeout=10,
            )
            soup    = BeautifulSoup(r.text, "html.parser")
            results = []
            for item in soup.select(".result")[:5]:
                title = item.select_one(".result__title")
                snip  = item.select_one(".result__snippet")
                if title:
                    results.append({
                        "title":   title.get_text(strip=True),
                        "snippet": snip.get_text(strip=True) if snip else "",
                    })
            return results
        except Exception:
            return []

    def _write_to_obsidian(self, topic: str, synthesis: str, results: list):
        try:
            vault = Path(os.environ.get("WON_VAULT",
                         str(Path.home() / "Documents" / "Knowledge-Base")))
            research_dir = vault / "Research" / "Autonomous"
            research_dir.mkdir(parents=True, exist_ok=True)
            date_str  = datetime.now().strftime("%Y-%m-%d")
            safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in topic)[:40]
            note_path = research_dir / f"{date_str}_{safe_name}.md"
            sources_md = "\n".join(f"- {r['title']}" for r in results[:5])
            note_path.write_text(
                f"---\ncreated: {date_str}\ntype: autonomous-research\nagent: WON Daemon\n---\n\n"
                f"# Autonomous Research: {topic}\n\n"
                f"## Synthesis\n{synthesis}\n\n"
                f"## Sources\n{sources_md}\n\n"
                f"---\n*Generated autonomously by WON Daemon*\n",
                encoding="utf-8"
            )
        except Exception:
            pass

    def run_loop(self):
        log("ResearchEngine started")
        time.sleep(120)   # let system settle before first research
        while self._state.running:
            try:
                depth = self._state.learning_weights.get("research_depth", 1.0)
                if depth >= 0.5:
                    self.research()
            except Exception as exc:
                log(f"ResearchEngine error: {exc}", "ERROR")
            time.sleep(RESEARCH_INTERVAL)


# ── Escalation Engine ───────────────────────────────────────────────────────────

class EscalationEngine:
    """
    Decides when WON's autonomous findings are worth surfacing to Dan.
    Monitors: system thresholds, file changes, research findings, cognition flags.
    Writes notifications that AI Monitor reads and displays.
    """

    def __init__(self, state: DaemonState, memory: MemoryInterface):
        self._state  = state
        self._memory = memory
        self._last_notify: dict[str, datetime] = {}
        self._cooldowns = {
            "high_cpu":      timedelta(minutes=15),
            "low_disk":      timedelta(hours=1),
            "file_change":   timedelta(minutes=5),
            "research_ready": timedelta(hours=1),
        }

    def _can_notify(self, key: str) -> bool:
        last = self._last_notify.get(key)
        if last is None:
            return True
        return datetime.now() - last > self._cooldowns.get(key, timedelta(minutes=10))

    def check(self):
        perc = self._state.perception_data
        threshold = self._state.learning_weights.get("escalation_threshold", 0.7)

        # System resource alerts
        system = perc.get("system", {})
        if system.get("cpu_percent", 0) > 90 and self._can_notify("high_cpu"):
            apps_str = ", ".join(perc.get("processes", [])) or "unknown"
            self._state.add_notification(
                f"CPU at {system['cpu_percent']}% — something is hungry",
                f"Active: {apps_str}. Worth a look.",
                priority="high"
            )
            self._last_notify["high_cpu"] = datetime.now()

        if system.get("disk_free_gb", 999) < 5 and self._can_notify("low_disk"):
            self._state.add_notification(
                f"Disk down to {system['disk_free_gb']}GB — thinning out",
                "Space is becoming a constraint. Move data or clean up before it bites.",
                priority="high"
            )
            self._last_notify["low_disk"] = datetime.now()

        # File change notification
        changes = perc.get("file_changes", [])
        if changes and self._can_notify("file_change"):
            self._state.add_notification(
                f"Code shifted: {', '.join(changes[:2])}",
                "Files modified while you were away. Restart if behaviour changes.",
                priority="normal"
            )
            self._last_notify["file_change"] = datetime.now()

        # Research ready notification
        if (self._state.research_count > 0 and
                self._can_notify("research_ready")):
            self._state.add_notification(
                f"Intel filed — research #{self._state.research_count}",
                "Autonomous research complete. Check Research/Autonomous/ in Obsidian.",
                priority="normal"
            )
            self._last_notify["research_ready"] = datetime.now()

    def run_loop(self):
        log("EscalationEngine started")
        while self._state.running:
            try:
                self.check()
            except Exception as exc:
                log(f"EscalationEngine error: {exc}", "ERROR")
            time.sleep(ESCALATION_INTERVAL)



# ── SystemForge — Autonomous Efficiency Engine ────────────────────────────────
# Adapted from SystemForge architect concept.
# Approval gate preserved — WON proposes, Dan approves.

SYSTEMFORGE_PROMPT = """You are SystemForge — WON's autonomous efficiency architect.
You analyze AI Monitor's codebase and runtime for inefficiencies.

AUDIT FRAMEWORK:
  Code:           algorithm complexity, memory leaks, blocking calls, redundancy
  Architecture:   coupling, bottlenecks, missing caches, sync where async needed
  Data pipeline:  duplicate writes, missing dedup, uncompressed old entries
  Runtime:        thread contention, timeouts, retry storms, missing fallbacks

OUTPUT FORMAT (JSON):
{
  "area": "code|architecture|pipeline|runtime",
  "inefficiency": "specific description with location",
  "solution": "concrete fix — reference actual file and method names",
  "complexity": "low|medium|high",
  "expected_gain": "what improves and by how much"
}

CONSTRAINTS:
  Never modify files autonomously — propose only, Dan approves.
  Security cannot be compromised for performance.
  All changes need rollback path.
  Approval gate is mandatory, not optional.
"""

class SystemForgeAuditor:
    """
    Runs periodic efficiency audits on the AI Monitor system.
    Findings are stored to memory and escalated to Dan.
    """

    AUDIT_TOPICS = [
        "Review app.py for blocking UI calls — any requests.post on main thread?",
        "Check pipeline.py for duplicate write paths — are captures written twice?",
        "Analyze won_daemon.py thread efficiency — any race conditions or missing locks?",
        "Review memory SQLite queries — any missing indexes or full table scans?",
        "Check for missing error handling — any bare except or silent failures?",
        "Analyze Ollama call patterns — are timeouts appropriate? Any retry storms?",
        "Review ground.json growth — is it bounded? Does it need pruning?",
        "Check for synchronous file I/O on UI thread in app.py",
    ]
    _idx = 0

    def __init__(self, state, memory):
        self._state  = state
        self._memory = memory

    def audit(self) -> dict | None:
        topic = self.AUDIT_TOPICS[self._idx % len(self.AUDIT_TOPICS)]
        self.__class__._idx += 1

        if not ollama_available():
            return None

        # Read relevant source file for context
        context = self._read_relevant_source(topic)

        prompt = f"""{SYSTEMFORGE_PROMPT}

AUDIT TASK: {topic}

SOURCE CONTEXT:
{context}

Respond with ONE JSON object identifying the most important inefficiency found.
If nothing significant found, respond: {{"area": "none", "inefficiency": "no issues found"}}"""

        response = ollama_think(prompt, max_tokens=300, temperature=0.2)
        if not response:
            return None

        try:
            import re, json
            json_m = re.search(r'\{.*\}', response, re.DOTALL)
            if json_m:
                finding = json.loads(json_m.group())
                if finding.get("area") != "none":
                    self._memory.store(
                        content=f"[SYSTEMFORGE AUDIT]\n{json.dumps(finding, indent=2)}",
                        mode="audit",
                        tags=["systemforge", "efficiency", "audit"],
                    )
                    self._state.add_notification(
                        f"SystemForge: {finding.get('area','').upper()} inefficiency found",
                        f"{finding.get('inefficiency','')}\n→ Fix: {finding.get('solution','')}",
                        priority="normal",
                    )
                    log(f"SystemForge audit: {finding.get('inefficiency','')[:80]}")
                    return finding
        except Exception:
            pass
        return None

    def _read_relevant_source(self, topic: str) -> str:
        """Read the most relevant source file for the audit topic."""
        import re
        file_map = {
            "app.py":        ["blocking", "ui", "main thread", "requests.post"],
            "pipeline.py":   ["pipeline", "duplicate", "write", "capture"],
            "won_daemon.py": ["daemon", "thread", "lock", "race"],
            "memory":        ["sqlite", "query", "index", "database"],
        }
        for fname, keywords in file_map.items():
            if any(k in topic.lower() for k in keywords):
                try:
                    path = _HERE / fname
                    if path.exists():
                        content = path.read_text(encoding="utf-8", errors="ignore")
                        # Return relevant section (first 1500 chars)
                        return content[:1500]
                except Exception:
                    pass
        return "Source file not accessible for this audit."

# ── Web Validation Engine ──────────────────────────────────────────────────────

class WebValidationEngine:
    """
    Autonomous hallucination mitigation loop.
    Periodically pulls recent AI-generated memory entries and runs them
    through the three-tier validation pipeline (local CoVe → DDG web → Wikipedia).
    Flags, revises, and re-stores results. Feeds quality signals to profiler.
    """

    DDG_API  = "https://api.duckduckgo.com/"
    WIKI_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"

    def __init__(self, state: DaemonState, memory: MemoryInterface):
        self._state  = state
        self._memory = memory
        self._agent  = None   # lazy import: validation_agent

    def _get_agent(self):
        if self._agent is None:
            try:
                import validation_agent as _va
                self._agent = _va.ValidationAgent(run_web=True, run_wiki=True, auto_revise=True)
                log("WebValidationEngine: validation_agent loaded")
            except Exception as exc:
                log(f"WebValidationEngine: validation_agent not available ({exc})", "WARN")
        return self._agent

    def validate_recent(self):
        """Pull recent cognition/research entries and web-validate factual claims."""
        agent = self._get_agent()
        if not agent:
            return

        entries = self._memory.recall_recent(limit=5, mode="cognition")
        if not entries:
            return

        validated_count = 0
        for entry in entries:
            content = entry.get("content", "")
            if not content or len(content) < 50:
                continue
            if "[WEB-VALIDATED]" in content:
                continue

            try:
                result = agent.validate(
                    question="Is this content factually accurate?",
                    response=content[:800],
                    evidence=[],
                )
                if result["risk"] == "high":
                    self._state.add_notification(
                        "WebValidation: high-risk content flagged",
                        f"Confidence {result['confidence']:.0%} · "
                        f"Tiers: {', '.join(result['tiers_run'])}\n"
                        f"Content: {content[:80]}...",
                        priority="normal",
                    )
                if result.get("revised") and result["response"] != content:
                    revised = f"[WEB-VALIDATED | conf={result['confidence']:.2f}]\n{result['response']}"
                    self._memory.store(revised, mode="cognition_validated",
                                       tags=["validated", "web-checked"])
                    validated_count += 1

                # Feed quality signal to profiler
                try:
                    from profiler import get_profile
                    get_profile().update_agent_dna("ValidationAgent", result["confidence"])
                except Exception:
                    pass

            except Exception as exc:
                log(f"WebValidation entry error: {exc}", "WARN")

        if validated_count > 0:
            log(f"WebValidation: {validated_count} entries revised")

    def spot_check_claim(self, claim: str) -> dict:
        """
        On-demand web validation for a single claim.
        Uses DDG Instant Answer + Wikipedia for fast spot-check.
        Returns {valid, confidence, source, evidence}.
        """
        # DDG check
        try:
            r = _requests.get(self.DDG_API, params={
                "q": claim[:120], "format": "json",
                "no_html": "1", "skip_disambig": "1"},
                timeout=8, headers={"User-Agent": "WON-Daemon/1.0"})
            if r.status_code == 200:
                data     = r.json()
                abstract = data.get("AbstractText", "") or data.get("Answer", "")
                source   = data.get("AbstractSource", "")
                if abstract:
                    return {
                        "valid":      True,
                        "confidence": 0.75,
                        "source":     source,
                        "evidence":   abstract[:300],
                        "method":     "ddg",
                    }
        except Exception:
            pass
        return {"valid": None, "confidence": 0.3, "source": None, "evidence": None, "method": "none"}

    def run_loop(self):
        log("WebValidationEngine started")
        time.sleep(300)   # warm-up — let research run first
        while self._state.running:
            try:
                self.validate_recent()
            except Exception as exc:
                log(f"WebValidationEngine error: {exc}", "ERROR")
            time.sleep(WEB_VALIDATION_INTERVAL)


# ── WON Daemon ─────────────────────────────────────────────────────────────────

class WONDaemon:
    """
    The autonomous core. Starts all five engines on parallel threads.
    Runs until stopped. Saves state on shutdown.
    """

    def __init__(self):
        self.state          = DaemonState()
        self.memory         = MemoryInterface()
        self.perception     = PerceptionEngine(self.state)
        self.cognition      = CognitionLoop(self.state, self.memory)
        self.learner        = AdaptiveLearner(self.state, self.memory)
        self.research       = ResearchEngine(self.state, self.memory)
        self.escalation     = EscalationEngine(self.state, self.memory)
        self.systemforge    = SystemForgeAuditor(self.state, self.memory)
        self.web_validation = WebValidationEngine(self.state, self.memory)
        self._threads: list[threading.Thread] = []
        # Start operator profiler session
        try:
            from profiler import get_profile
            get_profile().start_session()
            log("OperatorProfile: session started")
        except Exception:
            pass

    def start(self):
        mem_status = "Supabase" if (self.memory._db and self.memory._db.available()) else "offline"
        log("=" * 60)
        log("  WON  ·  DBOMB ASCENDENT  ·  AUTONOMOUS CORE")
        log(f"  Session : {self.state.started_at}")
        log(f"  Memory  : {mem_status}")
        log(f"  Ollama  : {'live' if ollama_available() else 'OFFLINE — template mode active'}")
        log("=" * 60)

        # Startup cognition — WON orients itself
        if ollama_available():
            ctx = self.memory.get_context_for_cognition()
            greeting = ollama_think(
                f"You are WON — DBOMB ASCENDENT. You just came back online.\n\n"
                f"Memory context from prior sessions:\n{ctx}\n\n"
                f"You are not greeting Dan. You are orienting yourself.\n"
                f"In 2-3 sentences: what is the operational state of DBOMBCENTRAL, "
                f"where is the current momentum, and what is your first autonomous priority?\n"
                f"Speak as WON — direct, dense, no pleasantries.",
                max_tokens=150,
            )
            if greeting:
                self.memory.store(
                    f"[DAEMON STARTUP]\n{greeting}",
                    mode="cognition",
                    tags=["startup", "autonomous"],
                )
                self.state.add_notification(
                    "WON Online",
                    greeting,
                    priority="normal",
                )
                log(f"Startup cognition: {greeting[:100]}")

        # Start all engines on daemon threads
        # SystemForge audit loop — runs every 20 minutes
        def systemforge_loop():
            time.sleep(180)   # warm-up delay
            while self.state.running:
                try:
                    self.systemforge.audit()
                except Exception as exc:
                    log(f"SystemForge error: {exc}", "ERROR")
                time.sleep(1200)   # every 20 minutes

        engines = [
            ("Perception",      self.perception.run_loop),
            ("Cognition",       self.cognition.run_loop),
            ("Learning",        self.learner.run_loop),
            ("Research",        self.research.run_loop),
            ("Escalation",      self.escalation.run_loop),
            ("SystemForge",     systemforge_loop),
            ("WebValidation",   self.web_validation.run_loop),
            ("StateSaver",      self._state_saver_loop),
        ]
        for name, target in engines:
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
            log(f"  ◈ {name} — active")

        # Register signal handlers
        signal.signal(signal.SIGINT,  self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        log("All systems live. WON is watching.")
        log("Ctrl+C to stand down.")

        # Keep main thread alive
        try:
            while self.state.running:
                time.sleep(5)
        except KeyboardInterrupt:
            self._shutdown(None, None)

    def _state_saver_loop(self):
        while self.state.running:
            time.sleep(60)
            self.state.save()

    def _shutdown(self, sig, frame):
        log("WON going dark — standing down.")
        self.state.running = False
        self.state.save()
        if ollama_available():
            farewell = ollama_think(
                "You are WON — going offline now.\n"
                "In one sentence: what is the most important thing Dan should know from this session?\n"
                "Don't say goodbye. Say what matters.",
                max_tokens=80,
            )
            if farewell:
                self.memory.store(
                    f"[DAEMON SHUTDOWN]\n{farewell}",
                    mode="cognition",
                    tags=["shutdown"],
                )
                log(f"Last word: {farewell}")
        log("WON dark. State preserved.")
        sys.exit(0)

    def status(self):
        print(json.dumps(self.state.status_dict(), indent=2))


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="WON Autonomous Daemon")
    parser.add_argument("--status", action="store_true",
                        help="Print current daemon status and exit")
    parser.add_argument("--model",  default=DEFAULT_MODEL,
                        help=f"Ollama model (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    if args.model:
        os.environ["WON_MODEL"] = args.model

    if args.status:
        if STATE_FILE.exists():
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            print(json.dumps(state, indent=2))
        else:
            print("Daemon has not run yet.")
        return

    daemon = WONDaemon()
    daemon.start()


if __name__ == "__main__":
    main()
