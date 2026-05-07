# core/project_tracker.py — WON ACAS phase + project registry
import json, os
from datetime import datetime
from rich.table import Table
from rich.console import Console
from rich import box

_ACAS_PHASES = {
    1: ("Foundation Development",    "Memory architecture, learning framework, knowledge graph"),
    2: ("Agent System Development",  "Task decomposition, specialized agents, coordination"),
    3: ("Integration & Optimization","System integration, performance tuning, conflict resolution"),
    4: ("Compliance & Deployment",   "AR 25-50, audit trails, testing, live deployment"),
}

_DEFAULT_PROJECTS = [
    {"name": "AI Experience Project", "phase": "1", "status": "active",
     "description": "Phase 1 experiential AI — memory, biases, generation core",
     "created": datetime.utcnow().isoformat()},
    {"name": "ACAS",                 "phase": "1", "status": "planning",
     "description": "Advanced Cognitive Autonomous System — full 4-phase roadmap",
     "created": datetime.utcnow().isoformat()},
    {"name": "WON Agent",            "phase": "1", "status": "active",
     "description": "DBOMB ASCENDENT WON — advisor, tracker, brief engine",
     "created": datetime.utcnow().isoformat()},
]


class ProjectTracker:
    def __init__(self, path: str = "data/projects.json"):
        self._path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._projects = self._load()

    def _load(self) -> list[dict]:
        if os.path.exists(self._path):
            with open(self._path) as f:
                return json.load(f)
        self._save(_DEFAULT_PROJECTS)
        return _DEFAULT_PROJECTS

    def _save(self, data=None):
        with open(self._path, "w") as f:
            json.dump(data or self._projects, f, indent=2)

    # ── Read ───────────────────────────────────────────────────────────────

    def all(self) -> list[dict]:
        return self._projects

    def count(self) -> int:
        return len(self._projects)

    def current_phase(self) -> int:
        """Derive current ACAS phase from active projects."""
        active = [p for p in self._projects if p.get("status") == "active"]
        if not active:
            return 1
        phases = [int(p.get("phase", 1)) for p in active]
        return max(set(phases), key=phases.count)

    def get(self, name: str) -> dict | None:
        for p in self._projects:
            if p["name"].lower() == name.lower():
                return p
        return None

    # ── Write ──────────────────────────────────────────────────────────────

    def add_project(self, name: str, phase: str, description: str):
        self._projects.append({
            "name": name, "phase": phase, "status": "active",
            "description": description,
            "created": datetime.utcnow().isoformat(),
        })
        self._save()

    def update_phase(self, name: str, phase: str):
        for p in self._projects:
            if p["name"].lower() == name.lower():
                p["phase"] = phase
                p["updated"] = datetime.utcnow().isoformat()
        self._save()

    def update_status(self, name: str, status: str):
        for p in self._projects:
            if p["name"].lower() == name.lower():
                p["status"] = status
        self._save()

    # ── Display ────────────────────────────────────────────────────────────

    def print_projects(self, console: Console):
        t = Table(title="WON — Tracked Projects", box=box.SIMPLE_HEAVY)
        t.add_column("Project",     style="bold cyan")
        t.add_column("Phase",       style="yellow", justify="center")
        t.add_column("Status",      style="green")
        t.add_column("Description", style="dim")
        for p in self._projects:
            t.add_row(p["name"], str(p["phase"]), p.get("status","—"), p.get("description","")[:60])
        console.print(t)

    def print_phases(self, console: Console):
        current = self.current_phase()
        console.print()
        for num, (title, desc) in _ACAS_PHASES.items():
            marker = "[bold green]▶[/bold green]" if num == current else ("[dim]○[/dim]" if num > current else "[dim green]✓[/dim green]")
            style  = "bold" if num == current else "dim"
            console.print(f"  {marker} [bold]Phase {num}[/bold]: [{style}]{title}[/{style}]")
            console.print(f"       [dim]{desc}[/dim]")
        console.print()
