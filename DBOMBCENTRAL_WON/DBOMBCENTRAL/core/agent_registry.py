# core/agent_registry.py — DBOMBCENTRAL Agent Registry
"""
3-Tier Agent Architecture:

  Tier 1 — COORDINATOR:  CENTCOM Cortex  (holds plan, delegates)
  Tier 2 — SPECIALISTS:  WON, Forge, Sentinel, Nexus, Oracle, Compliance
  Tier 3 — CONTEXT:      SQLite memory, FAISS (Ph2), Neo4j (Ph3), message bus

Phase 1: All specialist roles fulfilled by WON directly.
Phase 2: LangGraph/CrewAI orchestrates real specialist instances.
This file defines the registry so Phase 2 slots in without architectural change.
"""
from dataclasses import dataclass, field
from typing import Callable
from datetime import datetime

@dataclass
class AgentSpec:
    name:         str
    role:         str          # coordinator | specialist | context
    department:   str
    phase:        int          # ACAS phase when this agent becomes active
    status:       str          # active | planned | backlog
    capabilities: list[str]
    entry_point:  str          # module path for Phase 2 instantiation
    handler:      Callable | None = field(default=None, repr=False)


# ── Registry ──────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, AgentSpec] = {

    "CENTCOM_CORTEX": AgentSpec(
        name="CENTCOM Cortex",
        role="coordinator",
        department="CORE",
        phase=1,
        status="active",
        capabilities=["delegate", "plan", "synthesize", "route", "coordinate"],
        entry_point="core.centcom.CENTCOMCortex",
    ),

    "WON": AgentSpec(
        name="WON — DBOMB ASCENDENT",
        role="specialist",
        department="CORE",
        phase=1,
        status="active",
        capabilities=["brief", "research", "memory", "track", "predict", "obsidian", "advise"],
        entry_point="won.run",
    ),

    "FORGE": AgentSpec(
        name="Forge Agent",
        role="specialist",
        department="FORGE",
        phase=2,
        status="planned",
        capabilities=["code-gen", "architecture-design", "testing", "scaffolding", "refactor"],
        entry_point="agents.forge.ForgeAgent",  # Phase 2 module
    ),

    "SENTINEL": AgentSpec(
        name="Sentinel Agent",
        role="specialist",
        department="SENTINEL",
        phase=2,
        status="planned",
        capabilities=["monitoring", "validation", "discrepancy-detection", "audit", "alert"],
        entry_point="agents.sentinel.SentinelAgent",
    ),

    "NEXUS": AgentSpec(
        name="Nexus Agent",
        role="specialist",
        department="NEXUS",
        phase=2,
        status="planned",
        capabilities=["rag", "knowledge-graph", "faiss", "neo4j", "cross-modal-retrieval"],
        entry_point="agents.nexus.NexusAgent",
    ),

    "ORACLE": AgentSpec(
        name="Oracle Agent",
        role="specialist",
        department="ORACLE",
        phase=3,
        status="backlog",
        capabilities=["prediction", "market-analysis", "innovation-synthesis",
                      "feasibility-assessment", "risk-benefit"],
        entry_point="agents.oracle.OracleAgent",
    ),

    "COMPLIANCE": AgentSpec(
        name="Compliance Agent",
        role="specialist",
        department="COMPLIANCE",
        phase=4,
        status="backlog",
        capabilities=["ar-25-50", "eu-ai-act", "nist", "audit-trail", "regulatory-adaptation"],
        entry_point="agents.compliance.ComplianceAgent",
    ),

    # Shared context layer (Tier 3)
    "MEMORY_BUS": AgentSpec(
        name="Memory Bus",
        role="context",
        department="CORE",
        phase=1,
        status="active",
        capabilities=["sqlite-fts5", "session-persistence", "cross-agent-recall"],
        entry_point="core.memory.WONMemory",
    ),

    "FAISS_STORE": AgentSpec(
        name="FAISS Vector Store",
        role="context",
        department="NEXUS",
        phase=2,
        status="planned",
        capabilities=["vector-similarity", "semantic-search", "embedding-storage"],
        entry_point="core.vector_store.FAISSStore",  # Phase 2 module
    ),

    "NEO4J_GRAPH": AgentSpec(
        name="Neo4j Knowledge Graph",
        role="context",
        department="NEXUS",
        phase=3,
        status="backlog",
        capabilities=["relational-knowledge", "graph-traversal", "entity-linking"],
        entry_point="core.knowledge_graph.Neo4jGraph",  # Phase 3 module
    ),
}


# ── API ────────────────────────────────────────────────────────────────────────

def get_active() -> list[AgentSpec]:
    return [a for a in _REGISTRY.values() if a.status == "active"]

def get_by_phase(phase: int) -> list[AgentSpec]:
    return [a for a in _REGISTRY.values() if a.phase == phase]

def get_by_role(role: str) -> list[AgentSpec]:
    return [a for a in _REGISTRY.values() if a.role == role]

def get(name: str) -> AgentSpec | None:
    return _REGISTRY.get(name.upper().replace(" ", "_"))

def register(spec: AgentSpec):
    key = spec.name.upper().replace(" ", "_")
    _REGISTRY[key] = spec

def summary() -> dict:
    total    = len(_REGISTRY)
    active   = len(get_active())
    by_phase = {ph: len(get_by_phase(ph)) for ph in [1,2,3,4]}
    return {
        "total": total, "active": active, "by_phase": by_phase,
        "timestamp": datetime.utcnow().isoformat(),
    }
