# pulse.py — STRATUM Living Pulse Engine
# ──────────────────────────────────────────────────────────────────────────────
# STRATUM is never idle. The Pulse Engine runs continuously — perceiving,
# analyzing, harvesting, and surfacing intelligence without waiting for input.
#
# Design basis:
#   - Continuous Learning Systems (Parisi et al., 2019)
#   - Autonomous Cognitive Architectures (ACT-R, Anderson 2004)
#   - Event-driven actor model (Hewitt, 1973 — adapted for AI context)
#
# Architecture:
#   PulseEngine  — master coordinator, spawns/manages loops
#   CognitionLoop — autonomous insight generation via Ollama
#   PerceptionLoop — file system, process, memory monitoring
#   HarvestLoop   — captures escaped data before it's lost
#   EvolutionLoop — scores outputs, adapts behavior weights
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import sys
import json
import time
import hashlib
import threading
import traceback
import subprocess
import platform
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional
import logging
_log = logging.getLogger(__name__)

_HERE    = Path(__file__).resolve().parent
SAVE_DIR = Path.home() / "Documents" / "AI_Monitor"
PULSE_LOG = SAVE_DIR / "pulse.log"
STATE_FILE = SAVE_DIR / "pulse_state.json"

OLLAMA_URL    = "http://localhost:11434/api/generate"
DEFAULT_MODEL = os.environ.get("WON_MODEL", "mistral:latest")


# ── Pulse Event ───────────────────────────────────────────────────────────────

class PulseEvent:
    __slots__ = ("ts", "loop", "kind", "data", "priority")

    def __init__(self, loop: str, kind: str, data: str, priority: int = 5):
        self.ts       = datetime.utcnow().isoformat()
        self.loop     = loop
        self.kind     = kind
        self.data     = data
        self.priority = priority  # 1=critical … 10=background

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}

    def __repr__(self):
        return f"[{self.loop}:{self.kind}] {self.data[:80]}"


# ── Pulse Engine ──────────────────────────────────────────────────────────────

class PulseEngine:
    """
    The heartbeat of STRATUM. Runs all background loops and emits events
    that the UI can subscribe to for live terminal output.
    """

    COGNITION_INTERVAL  = 180   # 3 min: autonomous thought generation
    PERCEPTION_INTERVAL = 20    # 20 s:  system state observation
    HARVEST_INTERVAL    = 45    # 45 s:  data leak capture
    EVOLUTION_INTERVAL  = 600   # 10 min: behavioral learning
    STRATEGY_INTERVAL   = 1200  # 20 min: strategic review

    def __init__(self):
        SAVE_DIR.mkdir(parents=True, exist_ok=True)

        self._stop        = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock        = threading.Lock()
        self._callbacks: list[Callable[[PulseEvent], None]] = []
        self._event_ring  = deque(maxlen=500)   # rolling event buffer
        self._behavior    = self._load_behavior()
        self.cycles       = 0
        self.started_at   = None

    # ── Public API ────────────────────────────────────────────────────────────

    def subscribe(self, callback: Callable[[PulseEvent], None]):
        """Register a callback for live pulse events (called from any thread)."""
        with self._lock:
            self._callbacks.append(callback)

    def start(self):
        if self._threads:
            return  # already running
        self._stop.clear()
        self.started_at = datetime.utcnow()
        self._emit(PulseEvent("STRATUM", "start", "Pulse Engine initializing…", priority=1))

        specs = [
            ("CognitionLoop",  self._cognition_loop,  self.COGNITION_INTERVAL),
            ("PerceptionLoop", self._perception_loop, self.PERCEPTION_INTERVAL),
            ("HarvestLoop",    self._harvest_loop,    self.HARVEST_INTERVAL),
            ("EvolutionLoop",  self._evolution_loop,  self.EVOLUTION_INTERVAL),
            ("StrategyLoop",   self._strategy_loop,   self.STRATEGY_INTERVAL),
        ]
        for name, fn, interval in specs:
            t = threading.Thread(
                target=self._loop_runner,
                args=(name, fn, interval),
                daemon=True,
                name=name,
            )
            t.start()
            self._threads.append(t)

        self._emit(PulseEvent("STRATUM", "ready", "All loops online. STRATUM is live.", priority=1))

    def stop(self):
        self._stop.set()
        self._emit(PulseEvent("STRATUM", "stop", "Pulse Engine stopping.", priority=1))

    def get_recent_events(self, n: int = 50) -> list[dict]:
        with self._lock:
            return [e.to_dict() for e in list(self._event_ring)[-n:]]

    def get_state(self) -> dict:
        return {
            "running":    not self._stop.is_set(),
            "cycles":     self.cycles,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "uptime_s":   int((datetime.utcnow() - self.started_at).total_seconds())
                          if self.started_at else 0,
            "behavior":   self._behavior,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _emit(self, event: PulseEvent):
        with self._lock:
            self._event_ring.append(event)
            cbs = list(self._callbacks)
        for cb in cbs:
            try:
                cb(event)
            except Exception as e:
                _log.warning(f'caught exception: {e}')
        self._log(event)

    def _log(self, event: PulseEvent):
        try:
            with open(PULSE_LOG, "a", encoding="utf-8") as f:
                f.write(f"{event.ts} [{event.loop}:{event.kind}] {event.data}\n")
        except Exception as e:
            _log.warning(f'caught exception: {e}')

    def _loop_runner(self, name: str, fn: Callable, interval: float):
        """Wrap each loop function with error recovery and timing."""
        while not self._stop.is_set():
            try:
                fn()
                self.cycles += 1
            except Exception as exc:
                self._emit(PulseEvent(name, "error", str(exc)[:200], priority=2))
            self._stop.wait(interval)

    # ── Cognition Loop ────────────────────────────────────────────────────────

    def _cognition_loop(self):
        """
        Autonomous thought generation — STRATUM reasons about current context
        without waiting for user input.
        Produces proactive insights stored to memory.
        """
        self._emit(PulseEvent("CognitionLoop", "tick", "Scanning context for autonomous insights…"))

        # Load recent memory context
        context = self._load_recent_context()
        if not context:
            self._emit(PulseEvent("CognitionLoop", "skip", "No context available — skipping cycle"))
            return

        prompt = f"""You are STRATUM — an autonomous AI running silently in the background.
You are scanning Dan's recent AI interactions and generating one proactive insight.

RECENT CONTEXT (last 3 entries):
{context}

TASK: Generate ONE specific, actionable insight Dan hasn't explicitly asked for.
Format: INSIGHT: [one clear sentence] → ACTION: [one specific next step]
No preamble. No explanation. Just the insight line."""

        response = self._ollama_quick(prompt, max_tokens=150)
        if response and "INSIGHT:" in response:
            self._emit(PulseEvent("CognitionLoop", "insight", response.strip(), priority=3))
            self._store_to_memory(response, "cognition", ["autonomous", "insight"])

    # ── Perception Loop ───────────────────────────────────────────────────────

    def _perception_loop(self):
        """
        Observe the system state: new files, resource usage, process health.
        """
        observations = []

        # Check Ollama health
        try:
            import requests as _r
            r = _r.get("http://localhost:11434/api/tags", timeout=2)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                observations.append(f"Ollama: ONLINE — {len(models)} models loaded")
            else:
                observations.append("Ollama: DEGRADED")
        except Exception:
            observations.append("Ollama: OFFLINE")

        # Scan for new pipeline captures
        history_dir = SAVE_DIR / "history"
        if history_dir.exists():
            recent = sorted(history_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
            if recent:
                age_s = time.time() - recent[0].stat().st_mtime
                observations.append(f"Latest capture: {recent[0].name} ({int(age_s)}s ago)")

        # Check memory DB size
        hash_db = SAVE_DIR / "content_hashes.db"
        if hash_db.exists():
            sz_kb = hash_db.stat().st_size // 1024
            observations.append(f"Memory index: {sz_kb}KB")

        # System memory (cross-platform)
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["wmic", "OS", "get", "FreePhysicalMemory,TotalVisibleMemorySize", "/VALUE"],
                    capture_output=True, text=True, timeout=3,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
                lines = {l.split("=")[0]: l.split("=")[1]
                         for l in result.stdout.splitlines() if "=" in l}
                free  = int(lines.get("FreePhysicalMemory", "0")) // 1024
                total = int(lines.get("TotalVisibleMemorySize", "1")) // 1024
                pct   = 100 - int(free / total * 100)
                observations.append(f"RAM: {pct}% used ({free}MB free)")
        except Exception as e:
            _log.warning(f'caught exception: {e}')

        if observations:
            summary = " | ".join(observations)
            self._emit(PulseEvent("PerceptionLoop", "observe", summary))

    # ── Harvest Loop ──────────────────────────────────────────────────────────

    def _harvest_loop(self):
        """
        Capture data that would otherwise be lost:
        - Clipboard content (if AI-looking text)
        - Temp files with AI conversation fragments
        - Context overflow from large sessions
        """
        harvested = []

        # Clipboard harvest
        try:
            import subprocess
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=2,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            clip = result.stdout.strip()
            if clip and len(clip) > 100 and self._looks_like_ai_content(clip):
                h = hashlib.md5(clip.encode()).hexdigest()[:8]
                harvested.append(f"Clipboard fragment [{h}]: {clip[:80]}…")
                self._store_to_memory(clip, "harvest", ["clipboard", "harvested"])
        except Exception as e:
            _log.warning(f'caught exception: {e}')

        # Temp file harvest — find abandoned AI session files
        try:
            temp = Path(os.environ.get("TEMP", "C:/Windows/Temp"))
            patterns = ["*.json", "*.txt", "*.md"]
            for pat in patterns:
                for f in list(temp.glob(pat))[:10]:
                    try:
                        age = time.time() - f.stat().st_mtime
                        if age < 3600:  # files created in last hour
                            content = f.read_text(encoding="utf-8", errors="ignore")
                            if len(content) > 200 and self._looks_like_ai_content(content):
                                harvested.append(f"Temp fragment: {f.name}")
                    except Exception as e:
                        _log.warning(f'caught exception: {e}')
        except Exception as e:
            _log.warning(f'caught exception: {e}')

        if harvested:
            self._emit(PulseEvent("HarvestLoop", "captured",
                                  f"Harvested {len(harvested)} fragments: {harvested[0]}", priority=4))
        else:
            self._emit(PulseEvent("HarvestLoop", "idle", "No escapable data detected"))

    # ── Evolution Loop ────────────────────────────────────────────────────────

    def _evolution_loop(self):
        """
        Score STRATUM's own outputs. Adapt behavior weights based on outcomes.
        Implements a simple reinforcement signal from memory approval patterns.
        """
        self._emit(PulseEvent("EvolutionLoop", "tick", "Evaluating output quality…"))

        outcomes_file = SAVE_DIR / "conv_outcomes.json"
        if not outcomes_file.exists():
            return

        try:
            outcomes = json.loads(outcomes_file.read_text(encoding="utf-8"))
            if not outcomes:
                return

            recent = outcomes[-20:] if len(outcomes) > 20 else outcomes
            approved   = sum(1 for o in recent if o.get("outcome") == "approved")
            rejected   = sum(1 for o in recent if o.get("outcome") == "rejected")
            total      = len(recent)
            approval_r = approved / total if total else 0

            # Adapt temperature based on approval rate
            if approval_r > 0.8:
                self._behavior["temperature"] = min(0.9, self._behavior.get("temperature", 0.7) + 0.05)
                signal = "high approval → increasing creativity"
            elif approval_r < 0.4:
                self._behavior["temperature"] = max(0.1, self._behavior.get("temperature", 0.7) - 0.1)
                signal = "low approval → tightening constraints"
            else:
                signal = "approval nominal"

            self._behavior["approval_rate"] = round(approval_r, 3)
            self._save_behavior()

            self._emit(PulseEvent("EvolutionLoop", "adapt",
                f"Approval {approved}/{total} ({approval_r:.0%}) — {signal}"))
        except Exception as exc:
            self._emit(PulseEvent("EvolutionLoop", "error", str(exc)[:100]))

    # ── Strategy Loop ─────────────────────────────────────────────────────────

    def _strategy_loop(self):
        """
        Autonomous strategic review — checks Dan's project goals and surfaces
        the highest-priority next action.
        """
        self._emit(PulseEvent("StrategyLoop", "tick", "Running strategic review…"))

        strategy_file = SAVE_DIR / "strategy_matrix.json"
        if not strategy_file.exists():
            self._emit(PulseEvent("StrategyLoop", "skip", "No strategy matrix found — run Strategy tab to initialize"))
            return

        try:
            matrix = json.loads(strategy_file.read_text(encoding="utf-8"))
            goals  = matrix.get("goals", [])
            active = [g for g in goals if g.get("status") == "active"]

            if not active:
                self._emit(PulseEvent("StrategyLoop", "complete", "All active goals complete"))
                return

            # Find highest priority incomplete goal
            priority_goal = sorted(active, key=lambda g: g.get("priority", 99))[0]
            tasks = [t for t in priority_goal.get("tasks", []) if t.get("status") != "done"]

            if tasks:
                next_task = tasks[0]["name"]
                self._emit(PulseEvent("StrategyLoop", "vector",
                    f"PRIORITY: {priority_goal['name']} → Next: {next_task}", priority=3))
            else:
                self._emit(PulseEvent("StrategyLoop", "milestone",
                    f"GOAL COMPLETE: {priority_goal['name']}", priority=2))
        except Exception as exc:
            self._emit(PulseEvent("StrategyLoop", "error", str(exc)[:100]))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _ollama_quick(self, prompt: str, max_tokens: int = 200) -> str:
        try:
            import requests as _r
            r = _r.post(
                OLLAMA_URL,
                json={"model": DEFAULT_MODEL, "prompt": prompt, "stream": False,
                      "options": {"num_predict": max_tokens, "temperature":
                                  self._behavior.get("temperature", 0.7)}},
                timeout=30
            )
            return r.json().get("response", "").strip()
        except Exception:
            return ""

    def _looks_like_ai_content(self, text: str) -> bool:
        markers = ["Claude", "ChatGPT", "Gemini", "GPT-4", "assistant:", "User:",
                   "→", "INSIGHT:", "```", "ANALYSIS:", "WON:", "STRATUM"]
        return any(m in text for m in markers)

    def _load_recent_context(self) -> str:
        try:
            history = SAVE_DIR / "history"
            if not history.exists():
                return ""
            files = sorted(history.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
            snippets = []
            for f in files:
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    snippets.append(f"[{f.stem}]\n{content[:400]}")
                except Exception as e:
                    _log.warning(f'caught exception: {e}')
            return "\n\n".join(snippets)
        except Exception:
            return ""

    def _store_to_memory(self, content: str, mode: str, tags: list[str]):
        try:
            sys.path.insert(0, str(_HERE))
            import pipeline as _p
            _p.contribute(content, source="pulse", mode=mode, tags=tags)
        except Exception:
            # Fallback: write to local harvest file
            try:
                harvest_file = SAVE_DIR / "harvested.jsonl"
                entry = {"ts": datetime.utcnow().isoformat(), "mode": mode,
                         "tags": tags, "content": content[:500]}
                with open(harvest_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as e:
                _log.warning(f'caught exception: {e}')

    def _load_behavior(self) -> dict:
        try:
            if STATE_FILE.exists():
                return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            _log.warning(f'caught exception: {e}')
        return {"temperature": 0.7, "approval_rate": 0.5, "creativity_bias": 0.5}

    def _save_behavior(self):
        try:
            STATE_FILE.write_text(json.dumps(self._behavior, indent=2), encoding="utf-8")
        except Exception as e:
            _log.warning(f'caught exception: {e}')


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: Optional[PulseEngine] = None

def get_engine() -> PulseEngine:
    global _engine
    if _engine is None:
        _engine = PulseEngine()
    return _engine

def start() -> PulseEngine:
    e = get_engine()
    e.start()
    return e

def stop():
    if _engine:
        _engine.stop()
