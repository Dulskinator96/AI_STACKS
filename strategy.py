# strategy.py — STRATUM Autonomous Strategy Matrix
# ──────────────────────────────────────────────────────────────────────────────
# STRATUM thinks ahead. The Strategy Matrix tracks Dan's goals, decomposes them
# into executable tasks, prioritizes via Eisenhower matrix, and autonomously
# surfaces the highest-leverage next action.
#
# Framework basis:
#   - OKR (Objectives & Key Results) — Doerr, 2018
#   - Eisenhower Priority Matrix — urgent/important quadrants
#   - SMART goal criteria — Doran, 1981
#   - Critical Path Method (CPM) — task dependency sequencing
#   - Jobs-To-Be-Done framework — Christensen, 2016
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import os
import time
import uuid
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import logging
_log = logging.getLogger(__name__)

SAVE_DIR     = Path.home() / "Documents" / "AI_Monitor"
MATRIX_FILE  = SAVE_DIR / "strategy_matrix.json"
OLLAMA_URL   = "http://localhost:11434/api/generate"
DEFAULT_MODEL = os.environ.get("WON_MODEL", "mistral:latest")


# ── Data structures ───────────────────────────────────────────────────────────

class Task:
    def __init__(
        self,
        name:         str,
        description:  str = "",
        status:       str = "pending",   # pending | active | done | blocked
        priority:     int = 5,           # 1=highest, 10=lowest
        effort_h:     float = 1.0,       # estimated hours
        depends_on:   list[str] = None,  # task IDs this depends on
        tags:         list[str] = None,
    ):
        self.id          = uuid.uuid4().hex[:8]
        self.name        = name
        self.description = description
        self.status      = status
        self.priority    = priority
        self.effort_h    = effort_h
        self.depends_on  = depends_on or []
        self.tags        = tags or []
        self.created_at  = datetime.utcnow().isoformat()
        self.updated_at  = self.created_at
        self.completed_at: Optional[str] = None

    def complete(self):
        self.status       = "done"
        self.completed_at = datetime.utcnow().isoformat()
        self.updated_at   = self.completed_at

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ["id", "name", "description", "status", "priority",
                 "effort_h", "depends_on", "tags",
                 "created_at", "updated_at", "completed_at"]}

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        t = cls(d["name"], d.get("description", ""), d.get("status", "pending"),
                d.get("priority", 5), d.get("effort_h", 1.0),
                d.get("depends_on", []), d.get("tags", []))
        t.id           = d.get("id", t.id)
        t.created_at   = d.get("created_at", t.created_at)
        t.updated_at   = d.get("updated_at", t.updated_at)
        t.completed_at = d.get("completed_at")
        return t


class Goal:
    def __init__(
        self,
        name:        str,
        description: str = "",
        status:      str = "active",     # active | complete | paused | archived
        priority:    int = 5,
        deadline:    str = "",           # ISO date string
        tags:        list[str] = None,
    ):
        self.id          = uuid.uuid4().hex[:8]
        self.name        = name
        self.description = description
        self.status      = status
        self.priority    = priority
        self.deadline    = deadline
        self.tags        = tags or []
        self.tasks:      list[Task] = []
        self.key_results: list[str] = []  # OKR key results
        self.created_at  = datetime.utcnow().isoformat()
        self.updated_at  = self.created_at

    def add_task(self, task: Task):
        self.tasks.append(task)
        self.updated_at = datetime.utcnow().isoformat()

    def completion_pct(self) -> float:
        if not self.tasks:
            return 0.0
        done = sum(1 for t in self.tasks if t.status == "done")
        return done / len(self.tasks)

    def next_task(self) -> Optional[Task]:
        """Return highest-priority unblocked pending task."""
        completed_ids = {t.id for t in self.tasks if t.status == "done"}
        candidates = [
            t for t in self.tasks
            if t.status == "pending"
            and all(dep in completed_ids for dep in t.depends_on)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda t: t.priority)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "name":        self.name,
            "description": self.description,
            "status":      self.status,
            "priority":    self.priority,
            "deadline":    self.deadline,
            "tags":        self.tags,
            "tasks":       [t.to_dict() for t in self.tasks],
            "key_results": self.key_results,
            "created_at":  self.created_at,
            "updated_at":  self.updated_at,
            "completion_pct": round(self.completion_pct(), 3),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Goal":
        g = cls(d["name"], d.get("description", ""), d.get("status", "active"),
                d.get("priority", 5), d.get("deadline", ""), d.get("tags", []))
        g.id           = d.get("id", g.id)
        g.tasks        = [Task.from_dict(t) for t in d.get("tasks", [])]
        g.key_results  = d.get("key_results", [])
        g.created_at   = d.get("created_at", g.created_at)
        g.updated_at   = d.get("updated_at", g.updated_at)
        return g


# ── Strategy Matrix ───────────────────────────────────────────────────────────

class StrategyMatrix:
    """
    The central strategic planning hub.
    Owns all goals, decomposes them, surfaces critical path.
    """

    def __init__(self):
        self._lock  = threading.Lock()
        self._goals: list[Goal] = []
        self._load()

    # ── Goal Management ────────────────────────────────────────────────────────

    def add_goal(self, name: str, description: str = "", priority: int = 5,
                 deadline: str = "", tags: list = None) -> Goal:
        g = Goal(name, description, "active", priority, deadline, tags)
        with self._lock:
            self._goals.append(g)
        self.save()
        return g

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        with self._lock:
            return next((g for g in self._goals if g.id == goal_id), None)

    def list_goals(self, status: str = None) -> list[Goal]:
        with self._lock:
            if status:
                return [g for g in self._goals if g.status == status]
            return list(self._goals)

    def add_task_to_goal(self, goal_id: str, task: Task) -> bool:
        g = self.get_goal(goal_id)
        if not g:
            return False
        g.add_task(task)
        self.save()
        return True

    def complete_task(self, goal_id: str, task_id: str) -> bool:
        g = self.get_goal(goal_id)
        if not g:
            return False
        for t in g.tasks:
            if t.id == task_id:
                t.complete()
                if g.completion_pct() >= 1.0:
                    g.status = "complete"
                self.save()
                return True
        return False

    # ── AI-Powered Decomposition ──────────────────────────────────────────────

    def decompose_goal(self, goal_id: str, context: str = "") -> list[Task]:
        """
        Ask Ollama to decompose a goal into SMART tasks.
        Returns created tasks and adds them to the goal.
        """
        g = self.get_goal(goal_id)
        if not g:
            return []

        prompt = f"""You are a strategic planning AI. Decompose this goal into 4-6 specific tasks.

GOAL: {g.name}
DESCRIPTION: {g.description or 'None'}
CONTEXT: {context[:300] if context else 'None'}

For each task output EXACTLY:
TASK: <name> | EFFORT: <hours> | PRIORITY: <1-10> | DEPENDS: <none or task name>

One task per line. No other text."""

        try:
            import requests as _r
            r = _r.post(
                OLLAMA_URL,
                json={"model": DEFAULT_MODEL, "prompt": prompt, "stream": False,
                      "options": {"num_predict": 400, "temperature": 0.4}},
                timeout=60
            )
            raw = r.json().get("response", "")
        except Exception:
            return []

        tasks = []
        for line in raw.splitlines():
            if "TASK:" not in line:
                continue
            try:
                parts  = {p.split(":")[0].strip(): ":".join(p.split(":")[1:]).strip()
                          for p in line.split("|") if ":" in p}
                name   = parts.get("TASK", line)[:80]
                effort = float(parts.get("EFFORT", "1").replace("h", "").strip() or 1)
                prio   = int(parts.get("PRIORITY", "5").strip() or 5)
                task   = Task(name, effort_h=effort, priority=prio)
                tasks.append(task)
                g.add_task(task)
            except Exception:
                continue

        self.save()
        return tasks

    def generate_key_results(self, goal_id: str) -> list[str]:
        """Generate OKR key results for a goal using Ollama."""
        g = self.get_goal(goal_id)
        if not g:
            return []

        prompt = (
            f"Generate 3 measurable Key Results for this Objective.\n"
            f"Objective: {g.name}\n"
            f"Output format: KR1: ... | KR2: ... | KR3: ..."
        )
        try:
            import requests as _r
            r = _r.post(
                OLLAMA_URL,
                json={"model": DEFAULT_MODEL, "prompt": prompt, "stream": False,
                      "options": {"num_predict": 200, "temperature": 0.5}},
                timeout=30
            )
            raw = r.json().get("response", "")
            krs = [p.split(":", 1)[1].strip() for p in raw.split("|") if "KR" in p]
            g.key_results = krs[:3]
            self.save()
            return krs
        except Exception:
            return []

    # ── Priority & Critical Path ───────────────────────────────────────────────

    def get_critical_vector(self) -> Optional[dict]:
        """
        Return the single highest-priority next action across all active goals.
        Uses: goal priority × task priority × deadline urgency.
        """
        with self._lock:
            active = [g for g in self._goals if g.status == "active"]

        if not active:
            return None

        scored = []
        now = datetime.utcnow()
        for g in active:
            next_t = g.next_task()
            if not next_t:
                continue

            # Base score from priorities (lower = more important)
            score = g.priority * next_t.priority

            # Deadline urgency bonus
            if g.deadline:
                try:
                    dl = datetime.fromisoformat(g.deadline)
                    days_left = (dl - now).days
                    if days_left < 7:
                        score -= 20
                    elif days_left < 30:
                        score -= 10
                except Exception as e:
                    _log.warning(f'caught exception: {e}')

            scored.append((score, g, next_t))

        if not scored:
            return None

        scored.sort(key=lambda x: x[0])
        _, best_goal, best_task = scored[0]

        return {
            "goal":     best_goal.name,
            "goal_id":  best_goal.id,
            "task":     best_task.name,
            "task_id":  best_task.id,
            "priority": best_task.priority,
            "effort_h": best_task.effort_h,
            "completion": f"{best_goal.completion_pct():.0%}",
        }

    def eisenhower_sort(self) -> dict[str, list[dict]]:
        """
        Sort all tasks across all goals into Eisenhower quadrants.
        Quadrant mapping based on priority and tags.
        Returns: {"urgent_important": [...], "not_urgent_important": [...], ...}
        """
        q = {"urgent_important": [], "not_urgent_important": [],
             "urgent_not_important": [], "not_urgent_not_important": []}

        with self._lock:
            for g in self._goals:
                if g.status != "active":
                    continue
                for t in g.tasks:
                    if t.status == "done":
                        continue
                    urgent    = "urgent" in t.tags or t.priority <= 3
                    important = "important" in t.tags or g.priority <= 3

                    entry = {"goal": g.name, "task": t.name, "priority": t.priority}
                    if urgent and important:
                        q["urgent_important"].append(entry)
                    elif not urgent and important:
                        q["not_urgent_important"].append(entry)
                    elif urgent and not important:
                        q["urgent_not_important"].append(entry)
                    else:
                        q["not_urgent_not_important"].append(entry)

        return q

    def get_dashboard_summary(self) -> dict:
        """Full strategic snapshot for UI display."""
        with self._lock:
            goals = list(self._goals)

        active   = [g for g in goals if g.status == "active"]
        complete = [g for g in goals if g.status == "complete"]
        total_tasks = sum(len(g.tasks) for g in active)
        done_tasks  = sum(sum(1 for t in g.tasks if t.status == "done") for g in active)

        return {
            "goals_active":   len(active),
            "goals_complete": len(complete),
            "tasks_total":    total_tasks,
            "tasks_done":     done_tasks,
            "overall_pct":    round(done_tasks / total_tasks, 3) if total_tasks else 0.0,
            "critical_vector": self.get_critical_vector(),
            "active_goals":   [g.to_dict() for g in active[:5]],
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self):
        try:
            MATRIX_FILE.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {"goals": [g.to_dict() for g in self._goals],
                        "saved_at": datetime.utcnow().isoformat()}
            MATRIX_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            _log.warning(f'caught exception: {e}')

    def _load(self):
        try:
            if MATRIX_FILE.exists():
                data = json.loads(MATRIX_FILE.read_text(encoding="utf-8"))
                self._goals = [Goal.from_dict(g) for g in data.get("goals", [])]
        except Exception:
            self._goals = []


# ── Default Goals for DBOMBCENTRAL ────────────────────────────────────────────

def initialize_default_goals(matrix: StrategyMatrix):
    """Seed the strategy matrix with DBOMBCENTRAL ACAS phase goals if empty."""
    if matrix.list_goals():
        return  # already populated

    goals_data = [
        {
            "name":        "ACAS Phase 1 — Foundation",
            "description": "Establish core AI infrastructure: WON daemon, memory pipeline, agent protocol",
            "priority":    1,
            "tags":        ["acas", "foundation", "important"],
        },
        {
            "name":        "STRATUM Creative Engine — Live",
            "description": "Deploy synthesis, quantum context, procreation engines. Make STRATUM autonomous.",
            "priority":    2,
            "tags":        ["stratum", "synthesis", "important", "urgent"],
        },
        {
            "name":        "DBOMBCENTRAL Token Cost Reduction",
            "description": "Reduce per-session token usage by 60% via context compression + memory routing",
            "priority":    2,
            "tags":        ["cost", "optimization"],
        },
        {
            "name":        "Visual Creative Production Pipeline",
            "description": "Build end-to-end image/video generation pipeline integrated into STRATUM",
            "priority":    3,
            "tags":        ["synthesis", "creative"],
        },
    ]

    for gd in goals_data:
        matrix.add_goal(
            gd["name"], gd["description"],
            priority=gd["priority"], tags=gd["tags"]
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_matrix: Optional[StrategyMatrix] = None

def get_matrix() -> StrategyMatrix:
    global _matrix
    if _matrix is None:
        _matrix = StrategyMatrix()
        initialize_default_goals(_matrix)
    return _matrix

def get_critical_vector() -> Optional[dict]:
    return get_matrix().get_critical_vector()

def get_dashboard() -> dict:
    return get_matrix().get_dashboard_summary()
