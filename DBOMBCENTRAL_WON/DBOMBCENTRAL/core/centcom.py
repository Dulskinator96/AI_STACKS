# core/centcom.py — CENTCOM Cortex Coordinator
"""
Top-tier coordinator agent in the DBOMBCENTRAL 3-tier model.

Tier 1: CENTCOM Cortex (this file) — holds the plan, delegates
Tier 2: Specialist agents — WON (brief/advisor), Forge (build), Monitor, Validate, Report
Tier 3: Shared context — SQLite memory, FAISS (Phase 2), Neo4j (Phase 3)

Phase 1: Cortex acts as a routing and synthesis layer above WON.
Phase 2: Cortex will spawn and coordinate multiple specialist agents via LangGraph/CrewAI.
"""
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

# ── DBOMBCENTRAL Department Registry ──────────────────────────────────────────
# Each department maps to a specialist agent in Phase 2.
# In Phase 1, these are roles WON fulfills directly.

DEPARTMENTS = {
    "CORE": {
        "description": "Central intelligence and memory management",
        "agent":       "CENTCOM Cortex",
        "phase":       1,
        "status":      "active",
        "capabilities": ["memory", "context", "coordination"],
    },
    "NEXUS": {
        "description": "Knowledge graph, RAG, and cross-modal data integration",
        "agent":       "WON (interim) → Nexus Agent (Phase 2)",
        "phase":       2,
        "status":      "planned",
        "capabilities": ["knowledge-graph", "rag", "faiss", "neo4j"],
    },
    "FORGE": {
        "description": "Build, code generation, and technical implementation",
        "agent":       "Forge Agent (Phase 2)",
        "phase":       2,
        "status":      "planned",
        "capabilities": ["code-gen", "architecture", "testing"],
    },
    "SENTINEL": {
        "description": "Monitoring, validation, and discrepancy detection",
        "agent":       "Sentinel Agent (Phase 2)",
        "phase":       2,
        "status":      "planned",
        "capabilities": ["monitoring", "validation", "audit"],
    },
    "ORACLE": {
        "description": "Predictive analysis, market intelligence, ideation",
        "agent":       "Oracle Agent (Phase 3)",
        "phase":       3,
        "status":      "backlog",
        "capabilities": ["prediction", "market-analysis", "innovation-synthesis"],
    },
    "COMPLIANCE": {
        "description": "AR 25-50 documentation, regulatory, audit trail",
        "agent":       "Compliance Agent (Phase 4)",
        "phase":       4,
        "status":      "backlog",
        "capabilities": ["ar-25-50", "regulatory", "audit-trail"],
    },
}

# ── ACAS Phase definitions ─────────────────────────────────────────────────────
ACAS_PHASES = {
    1: {
        "title":      "Foundation Development",
        "duration":   "Months 1-3",
        "cost":       "$0",
        "stack":      ["Python 3.9+", "Ollama", "FAISS", "SQLite", "Scrapy", "Rich"],
        "deliverables": [
            "Compressive episodic memory (SQLite + FTS5)",
            "Basic learning framework with bias engine",
            "Knowledge graph structure (stub)",
            "Retrieval system (DuckDuckGo + local FTS)",
            "WON advisor agent operational",
            "Obsidian vault integration",
        ],
        "active": True,
    },
    2: {
        "title":      "Agent System Development",
        "duration":   "Months 4-6",
        "cost":       "$0-50/month",
        "stack":      ["LangGraph", "CrewAI", "LlamaIndex", "LocalAI", "FAISS", "Hugging Face"],
        "deliverables": [
            "Task decomposition engine",
            "Specialist agent generation (Forge, Sentinel, Nexus)",
            "Agent coordination protocol",
            "FAISS vector memory upgrade",
            "Multi-agent communication bus",
        ],
        "active": False,
    },
    3: {
        "title":      "Integration & Optimization",
        "duration":   "Months 7-9",
        "cost":       "$0-100/month",
        "stack":      ["AGiXT", "Semantic Kernel", "Neo4j", "LangGraph", "Flowise"],
        "deliverables": [
            "Neuro-symbolic hybrid reasoning layer",
            "Neo4j knowledge graph (replaces stub)",
            "System-wide performance benchmarks",
            "Causal inference framework",
            "Cross-agent conflict resolution",
        ],
        "active": False,
    },
    4: {
        "title":      "Compliance & Deployment",
        "duration":   "Months 10-12",
        "cost":       "$50-200/month",
        "stack":      ["io.net", "SiliconFlow", "Dify", "Amazon Q Developer"],
        "deliverables": [
            "AR 25-50 compliance engine",
            "Regulatory adaptation framework (EU AI Act, NIST)",
            "Full audit trail system",
            "Live deployment protocols",
            "Multi-billion ideation engine (Oracle)",
        ],
        "active": False,
    },
}

# ── Token/Context mitigation strategies ───────────────────────────────────────
# Derived from Areas_of_Concern.txt — built into WON's architecture
CONTEXT_STRATEGIES = [
    "Chunking + sliding windows for long inputs",
    "Summarization before processing (WON brief engine)",
    "Hierarchical processing — WON → Cortex → Oracle",
    "SQLite FTS5 memory-augmented retrieval (RAG substitute)",
    "Stateful interactions via persistent session memory",
    "External knowledge via DuckDuckGo (no in-prompt injection)",
]


class CENTCOMCortex:
    """
    Phase 1 coordinator — routes tasks, tracks department status,
    and provides the DBOMBCENTRAL operational overview.
    In Phase 2 this becomes a live LangGraph agent orchestrator.
    """

    def __init__(self, tracker, memory, predictor):
        self._tracker   = tracker
        self._memory    = memory
        self._predictor = predictor

    def status_panel(self) -> str:
        """Full CENTCOM operational status."""
        lines = [
            "DBOMBCENTRAL — CENTCOM CORTEX",
            f"Status: PHASE 1 ACTIVE  ·  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "DEPARTMENTS:",
        ]
        for name, d in DEPARTMENTS.items():
            status_icon = "▶" if d["status"] == "active" else ("○" if d["status"] == "planned" else "·")
            lines.append(f"  {status_icon} {name:<12} Ph{d['phase']}  {d['status']:<10}  {d['description'][:50]}")
        return "\n".join(lines)

    def print_full(self, console: Console):
        """Rich display of full CENTCOM state."""
        # Departments table
        t = Table(title="CENTCOM CORTEX — DBOMBCENTRAL", box=box.SIMPLE_HEAVY)
        t.add_column("Dept",        style="bold cyan",   no_wrap=True)
        t.add_column("Phase",       style="yellow",      justify="center")
        t.add_column("Status",      style="green")
        t.add_column("Agent",       style="dim")
        t.add_column("Description", style="dim")
        for name, d in DEPARTMENTS.items():
            status_color = "green" if d["status"] == "active" else ("yellow" if d["status"] == "planned" else "dim")
            t.add_row(name, str(d["phase"]),
                      f"[{status_color}]{d['status']}[/{status_color}]",
                      d["agent"][:40], d["description"][:50])
        console.print(t)

        # Phase roadmap
        console.print()
        for num, ph in ACAS_PHASES.items():
            marker = "[bold green]▶ ACTIVE[/bold green]" if ph["active"] else "[dim]○ PENDING[/dim]"
            console.print(f"  {marker}  [bold]Phase {num}:[/bold] {ph['title']}  [dim]({ph['duration']} · {ph['cost']})[/dim]")
            if ph["active"]:
                for d in ph["deliverables"]:
                    console.print(f"           [dim]· {d}[/dim]")
        console.print()

    def get_phase_context(self) -> str:
        """Returns current phase context string for brain/brief prompts."""
        ph = ACAS_PHASES[1]
        stack = ", ".join(ph["stack"])
        deliverables = "\n".join(f"  - {d}" for d in ph["deliverables"])
        return (
            f"ACAS Phase 1 — {ph['title']}\n"
            f"Stack: {stack}\n"
            f"Deliverables:\n{deliverables}\n\n"
            f"Next phase: {ACAS_PHASES[2]['title']} ({ACAS_PHASES[2]['stack'][0]}, {ACAS_PHASES[2]['stack'][1]})"
        )
