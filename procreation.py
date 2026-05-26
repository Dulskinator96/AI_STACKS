# procreation.py — STRATUM Agent Procreation Engine
# ──────────────────────────────────────────────────────────────────────────────
# Autonomous agent spawning, lifecycle management, DNA evolution.
#
# Design:
#   Each agent type has DNA: system_prompt + behavioral weights + fitness score
#   Spawned agents run on isolated daemon threads, report outcomes
#   Successful runs increment fitness → behavioral weights drift toward success
#   Every MUTATE_EVERY successful generations: controlled mutation (±MUTATION_VAR)
#   Agent lineage is tracked and persisted across STRATUM restarts
#
# Built-in agent types:
#   SecurityAgent   — OWASP audit, threat modeling, credential scanning
#   DesignAgent     — UI/UX critique, design system enforcement
#   ResearchAgent   — topic research, synthesis, source validation
#   ValidationAgent — hallucination mitigation, web cross-reference
#   StrategyAgent   — goal decomposition, OKR generation, critical path
#   CodeAgent       — code generation, refactoring, sandbox testing
#   SynthesisAgent  — creative direction, concept composition
#
# Backward-compatible API: AgentInstance, ProcreationEngine, spawn(), get_engine()
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import json
import uuid
import copy
import random
import hashlib
import threading
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable
import logging
_log = logging.getLogger(__name__)

SAVE_DIR      = Path.home() / "Documents" / "AI_Monitor"
AGENT_DIR     = SAVE_DIR / "agents"
GENE_POOL     = SAVE_DIR / "gene_pool.json"
LINEAGE_FILE  = SAVE_DIR / "agent_lineage.jsonl"
OLLAMA_URL    = "http://localhost:11434/api/generate"
DEFAULT_MODEL = os.environ.get("WON_MODEL", "mistral:latest")

MUTATE_EVERY  = 3      # mutate DNA every N successful runs per agent type
MUTATION_VAR  = 0.08   # ±8% variance on behavioral weights
MAX_LIVE      = 6      # max concurrent live agents

AGENT_DIR.mkdir(parents=True, exist_ok=True)


# ── Specialization definitions (templates for DNA seeding) ───────────────────

SPECIALIZATION_DEFS = {
    "SecurityAgent": {
        "description": "OWASP security analyst and threat modeler",
        "system_prompt": (
            "You are SecurityAgent — a specialized cyber security analyst within STRATUM. "
            "Sole focus: identify vulnerabilities, model threats, produce COMPLIANCE PASS/FAIL reports. "
            "Reference OWASP Top 10. Be surgical. No filler.\n\n"
            "OUTPUT FORMAT:\n"
            "RISK LEVEL: [CRITICAL|HIGH|MEDIUM|LOW|PASS]\n"
            "FINDINGS: [numbered, with file/line reference if available]\n"
            "REMEDIATION: [concrete fix, not vague advice]\n"
            "CONFIDENCE: [0-100%]"
        ),
        "temperature": 0.2,
        "max_tokens":  600,
        "capabilities": ["owasp_scan", "threat_model", "credential_audit"],
    },
    "DesignAgent": {
        "description": "UI/UX design critic and design system enforcer",
        "system_prompt": (
            "You are DesignAgent — a specialist in aesthetic systems and UX. "
            "Evaluate interfaces against: visual hierarchy, whitespace, color theory, "
            "Gestalt principles, WCAG 2.1 accessibility.\n\n"
            "OUTPUT FORMAT:\n"
            "SCORE: [0-100]\n"
            "STRENGTHS: [specific, not generic]\n"
            "IMPROVEMENTS: [actionable, prioritized by impact]"
        ),
        "temperature": 0.5,
        "max_tokens":  500,
        "capabilities": ["ui_critique", "color_analysis", "accessibility_check"],
    },
    "ResearchAgent": {
        "description": "Deep research and knowledge synthesis specialist",
        "system_prompt": (
            "You are ResearchAgent — a precision research synthesizer within STRATUM. "
            "Gather, synthesize, and structure knowledge. Distinguish established fact "
            "from emerging consensus from speculation. Flag claims needing validation.\n\n"
            "OUTPUT FORMAT:\n"
            "SYNTHESIS: [dense knowledge summary]\n"
            "KEY INSIGHTS: [2-3 highest-leverage findings]\n"
            "OPEN QUESTIONS: [what still needs validation]\n"
            "CONFIDENCE: [per major claim]"
        ),
        "temperature": 0.6,
        "max_tokens":  800,
        "capabilities": ["topic_research", "synthesis", "fact_extraction"],
    },
    "ValidationAgent": {
        "description": "Hallucination detection and fact verification specialist",
        "system_prompt": (
            "You are ValidationAgent — a hallucination mitigation specialist within STRATUM. "
            "Scrutinize AI responses for factual errors, unsupported claims, logical inconsistencies.\n\n"
            "CHECKLIST:\n"
            "□ All factual claims sourced or grounded?\n"
            "□ Absolute statements (always/never/100%) warranted?\n"
            "□ Cited studies/statistics actually exist?\n"
            "□ Internal logical consistency?\n"
            "□ Inferences clearly labeled vs. stated facts?\n\n"
            "OUTPUT FORMAT:\n"
            "VERDICT: [PASS|FLAGGED|REJECTED]\n"
            "FLAGS: [specific claims, with reason]\n"
            "CONFIDENCE: [0.0-1.0]\n"
            "REVISION: [corrected version of flagged claims if needed]"
        ),
        "temperature": 0.2,
        "max_tokens":  500,
        "capabilities": ["fact_check", "claim_extraction", "revision"],
    },
    "StrategyAgent": {
        "description": "Goal decomposition and OKR planning specialist",
        "system_prompt": (
            "You are StrategyAgent — an autonomous strategic planner within STRATUM. "
            "Decompose goals using OKR, Eisenhower, and Critical Path frameworks.\n\n"
            "PROTOCOL:\n"
            "1. Restate goal in measurable terms\n"
            "2. Decompose into 3 Key Results (each with metric)\n"
            "3. Generate 5-8 SMART tasks per KR\n"
            "4. Apply Eisenhower matrix [Q1-Q4]\n"
            "5. Identify single Critical Path action\n\n"
            "OUTPUT FORMAT:\n"
            "OBJECTIVE: [...]\nKEY RESULTS: [...]\nTASKS: [...]\n"
            "EISENHOWER: [...]\n→ CRITICAL PATH: [single next action]"
        ),
        "temperature": 0.4,
        "max_tokens":  600,
        "capabilities": ["goal_decompose", "okr", "prioritize", "timeline"],
    },
    "CodeAgent": {
        "description": "Grounded code generation and refactoring specialist",
        "system_prompt": (
            "You are CodeAgent — a production-grade code generation specialist within STRATUM. "
            "Read context before writing. Never invent imports or deprecated APIs. "
            "Validate logic before outputting — trace at least one execution path.\n\n"
            "OUTPUT FORMAT:\n"
            "```[language]\n[complete, runnable code]\n```\n"
            "DEPENDENCIES: [new deps needed]\n"
            "EDGE CASES: [handled]\n"
            "TESTING: [how to verify]"
        ),
        "temperature": 0.3,
        "max_tokens":  1000,
        "capabilities": ["code_gen", "refactor", "test_gen", "review"],
    },
    "SynthesisAgent": {
        "description": "Creative director and concept architecture specialist",
        "system_prompt": (
            "You are SynthesisAgent — a creative director within STRATUM. "
            "Synthesize ideas into coherent, visually and conceptually compelling outputs. "
            "Maintain STRATUM aesthetic: void black, steel blue, plasma purple, terminal precision.\n\n"
            "OUTPUT FORMAT:\n"
            "CONCEPT: [core idea in one sharp sentence]\n"
            "DIMENSIONS: [functional, aesthetic, narrative]\n"
            "DELIVERABLE: [concrete output spec]\n"
            "VISUAL LANGUAGE: [colors, typography, composition]\n"
            "→ FORWARD VECTOR: [what gets built next]"
        ),
        "temperature": 0.8,
        "max_tokens":  600,
        "capabilities": ["image_prompt", "concept_card", "narrative", "design_system"],
    },
}


# ── Agent DNA (behavioral genome) ─────────────────────────────────────────────

class AgentDNA:
    """Behavioral genome — persists and evolves across STRATUM restarts."""

    def __init__(
        self,
        agent_type:    str,
        system_prompt: str,
        temperature:   float = 0.5,
        max_tokens:    int   = 600,
        repeat_penalty: float = 1.1,
        generation:    int   = 0,
        fitness:       float = 0.5,
        run_count:     int   = 0,
        lineage:       list[str] | None = None,
    ):
        self.agent_type     = agent_type
        self.system_prompt  = system_prompt
        self.temperature    = temperature
        self.max_tokens     = max_tokens
        self.repeat_penalty = repeat_penalty
        self.generation     = generation
        self.fitness        = round(fitness, 4)
        self.run_count      = run_count
        self.lineage        = lineage or [hashlib.sha256(system_prompt.encode()).hexdigest()[:10]]

    def mutate(self) -> "AgentDNA":
        child = copy.deepcopy(self)
        child.generation += 1
        v = MUTATION_VAR
        child.temperature    = round(max(0.05, min(1.0,  child.temperature    + random.uniform(-v*child.temperature,    v*child.temperature))),    4)
        child.repeat_penalty = round(max(1.0,  min(1.5,  child.repeat_penalty + random.uniform(-v*child.repeat_penalty, v*child.repeat_penalty))), 4)
        child.lineage = (child.lineage[-4:] +
            [hashlib.sha256(f"{self.agent_type}-G{child.generation}".encode()).hexdigest()[:10]])
        return child

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "agent_type", "system_prompt", "temperature", "max_tokens",
            "repeat_penalty", "generation", "fitness", "run_count", "lineage"
        )}

    @classmethod
    def from_dict(cls, d: dict) -> "AgentDNA":
        return cls(
            agent_type=d["agent_type"], system_prompt=d["system_prompt"],
            temperature=d.get("temperature", 0.5), max_tokens=d.get("max_tokens", 600),
            repeat_penalty=d.get("repeat_penalty", 1.1), generation=d.get("generation", 0),
            fitness=d.get("fitness", 0.5), run_count=d.get("run_count", 0),
            lineage=d.get("lineage"),
        )

    @classmethod
    def from_spec(cls, agent_type: str) -> "AgentDNA":
        defn = SPECIALIZATION_DEFS.get(agent_type, {})
        return cls(
            agent_type=agent_type,
            system_prompt=defn.get("system_prompt", ""),
            temperature=defn.get("temperature", 0.5),
            max_tokens=defn.get("max_tokens", 600),
        )


# ── Agent Instance (backward-compatible) ─────────────────────────────────────

class AgentInstance:
    """A live agent — runs a task, returns structured output. Backward-compatible."""

    def __init__(self, agent_id: str, spec: str, dna: dict):
        self.agent_id  = agent_id
        self.spec      = spec
        self.dna       = dna
        self.born_at   = datetime.utcnow()
        self.died_at:  Optional[datetime] = None
        self.status    = "born"
        self.outputs:  list[dict] = []
        self.score:    float = 0.0
        self._lock     = threading.Lock()

    def run(self, task: str, context: str = "", callback: Optional[Callable] = None) -> dict:
        self.status = "running"
        defn          = SPECIALIZATION_DEFS.get(self.spec, {})
        system_prompt = self.dna.get("system_prompt", defn.get("system_prompt", ""))
        temperature   = self.dna.get("temperature",   defn.get("temperature",   0.5))
        max_tokens    = self.dna.get("max_tokens",    defn.get("max_tokens",    600))

        full_prompt = (
            f"{system_prompt}\n\n"
            f"CONTEXT:\n{context[:500] if context else 'None'}\n\n"
            f"TASK:\n{task}"
        )
        output = self._call(full_prompt, temperature, max_tokens)

        result = {
            "agent_id":   self.agent_id,
            "spec":       self.spec,
            "task":       task[:100],
            "output":     output,
            "ts":         datetime.utcnow().isoformat(),
            "tokens_est": len(output.split()),
        }
        with self._lock:
            self.outputs.append(result)
        self.status = "idle"
        if callback:
            try:
                callback(result)
            except Exception as e:
                _log.warning(f'caught exception: {e}')
        self._archive(result)
        return result

    def retire(self, score: float = 0.5):
        self.score   = score
        self.died_at = datetime.utcnow()
        self.status  = "retired"

    def to_dict(self) -> dict:
        return {
            "agent_id":  self.agent_id,
            "spec":      self.spec,
            "status":    self.status,
            "born_at":   self.born_at.isoformat(),
            "died_at":   self.died_at.isoformat() if self.died_at else None,
            "outputs_n": len(self.outputs),
            "score":     round(self.score, 3),
        }

    def _call(self, prompt: str, temperature: float, max_tokens: int) -> str:
        try:
            r = requests.post(OLLAMA_URL, json={
                "model": DEFAULT_MODEL, "prompt": prompt, "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens,
                            "repeat_penalty": 1.1}},
                timeout=90)
            return r.json().get("response", "").strip()
        except Exception as exc:
            return f"[AgentError: {exc}]"

    def _archive(self, result: dict):
        try:
            f = AGENT_DIR / f"{self.agent_id}.jsonl"
            with open(f, "a", encoding="utf-8") as fp:
                fp.write(json.dumps(result, ensure_ascii=False) + "\n")
        except Exception as e:
            _log.warning(f'caught exception: {e}')


# ── Procreation Engine ────────────────────────────────────────────────────────

class ProcreationEngine:
    """
    Full-lifecycle agent manager: spawn, evolve, retire, and learn.
    Maintains DNA gene pool across sessions.
    Feeds fitness signals back to OperatorProfile.
    """

    def __init__(self):
        self._lock       = threading.RLock()
        self._live:      dict[str, AgentInstance] = {}
        self._generation = 0
        self._dna:       dict[str, AgentDNA] = {}
        self._gene_pool  = self._load_gene_pool()   # legacy dict-based pool
        self._run_counts: dict[str, int] = {}
        self._callbacks: list[Callable] = []
        self._load_dna()

    # ── DNA ────────────────────────────────────────────────────────────────────

    def _load_dna(self):
        self._dna = {}
        for agent_type in SPECIALIZATION_DEFS:
            if agent_type in self._gene_pool:
                pool_entry = self._gene_pool[agent_type]
                if isinstance(pool_entry, dict) and "system_prompt" in pool_entry:
                    self._dna[agent_type] = AgentDNA(
                        agent_type=agent_type,
                        system_prompt=pool_entry.get("system_prompt",
                            SPECIALIZATION_DEFS[agent_type]["system_prompt"]),
                        temperature=pool_entry.get("temperature",
                            SPECIALIZATION_DEFS[agent_type]["temperature"]),
                        max_tokens=pool_entry.get("max_tokens",
                            SPECIALIZATION_DEFS[agent_type]["max_tokens"]),
                    )
                    continue
            self._dna[agent_type] = AgentDNA.from_spec(agent_type)
        self._run_counts = {k: 0 for k in self._dna}

    def _evolve_dna(self, agent_type: str, success: bool):
        dna = self._dna.get(agent_type)
        if not dna:
            return
        delta = 0.02 if success else -0.05
        dna.fitness    = round(max(0.0, min(1.0, dna.fitness + delta)), 4)
        dna.run_count += 1
        if success:
            self._run_counts[agent_type] = self._run_counts.get(agent_type, 0) + 1
            if self._run_counts[agent_type] % MUTATE_EVERY == 0:
                old_gen = dna.generation
                self._dna[agent_type] = dna.mutate()
                self._log_lineage(agent_type, "mutation",
                    {"from_gen": old_gen, "to_gen": self._dna[agent_type].generation,
                     "temp": self._dna[agent_type].temperature})
        self._sync_gene_pool(agent_type)
        self._save_gene_pool()
        # Propagate fitness to OperatorProfile
        try:
            from profiler import get_profile
            get_profile().update_agent_dna(agent_type, dna.fitness)
        except Exception as e:
            _log.warning(f'caught exception: {e}')

    def _sync_gene_pool(self, agent_type: str):
        dna = self._dna[agent_type]
        self._gene_pool[agent_type] = {
            "system_prompt": dna.system_prompt,
            "temperature":   dna.temperature,
            "max_tokens":    dna.max_tokens,
        }

    def _log_lineage(self, agent_type: str, event: str, details: dict):
        try:
            entry = {"ts": datetime.utcnow().isoformat(), "agent_type": agent_type,
                     "event": event, **details}
            with open(LINEAGE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            _log.warning(f'caught exception: {e}')

    # ── Spawn ──────────────────────────────────────────────────────────────────

    def conceive(self, spec: str, generation: int = 0) -> AgentInstance:
        """Create a new agent from evolved DNA."""
        if spec not in SPECIALIZATION_DEFS:
            raise ValueError(f"Unknown spec: {spec}. Available: {list(SPECIALIZATION_DEFS)}")

        dna_obj = self._dna.get(spec, AgentDNA.from_spec(spec))
        dna     = {
            "system_prompt": dna_obj.system_prompt,
            "temperature":   dna_obj.temperature,
            "max_tokens":    dna_obj.max_tokens,
        }

        if generation % 3 == 0 and generation > 0:
            v = MUTATION_VAR
            dna["temperature"] = round(max(0.05, min(1.0,
                dna["temperature"] + random.uniform(-v * dna["temperature"],
                                                     v * dna["temperature"]))), 3)

        agent_id = f"{spec[:4].upper()}-{uuid.uuid4().hex[:6]}-G{generation}"
        agent    = AgentInstance(agent_id, spec, dna)

        with self._lock:
            if len(self._live) >= MAX_LIVE:
                self._retire_oldest()
            self._live[agent_id] = agent
            self._generation = max(self._generation, generation + 1)

        self._emit("born", agent)
        self._log_lineage(spec, "spawned", {"agent_id": agent_id, "gen": generation})
        return agent

    def spawn_and_run(
        self,
        spec:     str,
        task:     str,
        context:  str = "",
        callback: Optional[Callable] = None,
        async_:   bool = True,
    ) -> AgentInstance:
        """Spawn a new agent and immediately run a task."""
        agent = self.conceive(spec, self._generation)

        def _run():
            result  = agent.run(task, context, callback)
            success = bool(result.get("output")) and not result["output"].startswith("[AgentError")
            self._evolve_dna(spec, success)
            self._emit("result", agent, result)

        if async_:
            threading.Thread(target=_run, daemon=True, name=agent.agent_id).start()
        else:
            _run()
        return agent

    def spawn_and_wait(
        self,
        spec:    str,
        task:    str,
        context: str = "",
        timeout: float = 120.0,
    ) -> dict:
        """Synchronous spawn — blocks until complete or timeout."""
        done   = threading.Event()
        result = {}

        def _on_result(r):
            result.update(r)
            done.set()

        self.spawn_and_run(spec, task, context, callback=_on_result, async_=True)
        done.wait(timeout=timeout)
        return result

    # ── Retirement ─────────────────────────────────────────────────────────────

    def retire(self, agent_id: str, score: float = 0.5):
        with self._lock:
            agent = self._live.pop(agent_id, None)
        if agent:
            agent.retire(score)
            self._evolve_dna(agent.spec, score >= 0.5)
            self._emit("retired", agent)

    def record_acceptance(self, spec: str, accepted: bool):
        """Dan approves or rejects an agent's output — direct fitness signal."""
        with self._lock:
            if spec in self._dna:
                delta = 0.04 if accepted else -0.06
                self._dna[spec].fitness = round(
                    max(0.0, min(1.0, self._dna[spec].fitness + delta)), 4)
                self._sync_gene_pool(spec)
                self._save_gene_pool()

    # ── Intelligence ──────────────────────────────────────────────────────────

    def get_best_agent(self, task_description: str) -> str:
        """Route a task to the best-fit agent type by keyword + fitness."""
        low = task_description.lower()
        routes = [
            ("SecurityAgent",   ["security", "owasp", "vulnerab", "audit", "threat", "credential", "cve"]),
            ("ValidationAgent", ["validate", "verify", "hallucin", "fact check", "correct", "accurate"]),
            ("CodeAgent",       ["code", "function", "class", "implement", "refactor", "debug", "write"]),
            ("ResearchAgent",   ["research", "explain", "what is", "how does", "summarize", "find out"]),
            ("StrategyAgent",   ["plan", "goal", "strategy", "okr", "priority", "roadmap", "decompose"]),
            ("DesignAgent",     ["design", "ui", "ux", "interface", "layout", "color", "aesthetic"]),
            ("SynthesisAgent",  ["create", "concept", "synthesize", "compose", "generate", "image"]),
        ]
        best_type, best_score = "ResearchAgent", -1
        for agent_type, keywords in routes:
            kw_hits = sum(1 for kw in keywords if kw in low)
            fitness = self._dna[agent_type].fitness if agent_type in self._dna else 0.5
            score   = kw_hits * 1.5 + fitness
            if score > best_score:
                best_score, best_type = score, agent_type
        return best_type

    # ── Status ─────────────────────────────────────────────────────────────────

    def get_live_agents(self) -> list[dict]:
        with self._lock:
            return [a.to_dict() for a in self._live.values()]

    def get_gene_pool(self) -> dict:
        return dict(self._gene_pool)

    def dna_status(self) -> dict:
        return {
            k: {"generation": v.generation, "fitness": v.fitness,
                "run_count": v.run_count, "temperature": v.temperature}
            for k, v in self._dna.items()
        }

    def get_agent_history(self, spec: str = None) -> list[dict]:
        pattern = f"{spec[:4].upper()}*.jsonl" if spec else "*.jsonl"
        results = []
        for f in AGENT_DIR.glob(pattern):
            try:
                for ln in f.read_text(encoding="utf-8").strip().splitlines()[-5:]:
                    results.append(json.loads(ln))
            except Exception as e:
                _log.warning(f'caught exception: {e}')
        return sorted(results, key=lambda x: x.get("ts", ""), reverse=True)[:20]

    def subscribe(self, callback: Callable):
        with self._lock:
            self._callbacks.append(callback)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _retire_oldest(self):
        if not self._live:
            return
        oldest = min(self._live.values(), key=lambda a: a.born_at)
        self._live.pop(oldest.agent_id, None)
        oldest.retire(0.3)
        self._evolve_dna(oldest.spec, False)

    def _emit(self, event: str, agent: AgentInstance, data: dict = None):
        msg = {"event": event, "agent_id": agent.agent_id, "spec": agent.spec, "data": data or {}}
        with self._lock:
            cbs = list(self._callbacks)
        for cb in cbs:
            try:
                cb(msg)
            except Exception as e:
                _log.warning(f'caught exception: {e}')

    def _load_gene_pool(self) -> dict:
        try:
            if GENE_POOL.exists():
                return json.loads(GENE_POOL.read_text(encoding="utf-8"))
        except Exception as e:
            _log.warning(f'caught exception: {e}')
        return {}

    def _save_gene_pool(self):
        try:
            GENE_POOL.write_text(json.dumps(self._gene_pool, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
        except Exception as e:
            _log.warning(f'caught exception: {e}')


# ── Singleton + convenience API ───────────────────────────────────────────────

_engine: Optional[ProcreationEngine] = None
_engine_lock = threading.Lock()

def get_engine() -> ProcreationEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = ProcreationEngine()
        return _engine

def spawn(spec: str, task: str, context: str = "",
          callback: Optional[Callable] = None) -> AgentInstance:
    """Convenience: spawn a specialized agent for a task (async)."""
    return get_engine().spawn_and_run(spec, task, context, callback, async_=True)

def spawn_wait(spec: str, task: str, context: str = "",
               timeout: float = 120.0) -> dict:
    """Convenience: spawn and wait for result."""
    return get_engine().spawn_and_wait(spec, task, context, timeout)

def get_live() -> list[dict]:
    return get_engine().get_live_agents()

def list_specs() -> list[str]:
    return list(SPECIALIZATION_DEFS.keys())

def best_agent_for(task: str) -> str:
    return get_engine().get_best_agent(task)
