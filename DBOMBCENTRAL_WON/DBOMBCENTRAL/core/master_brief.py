# DBOMBCENTRAL_MASTER_BRIEF.md
# This file is written directly to the Obsidian vault root by WON on first boot.
# It is the living master document for the entire DBOMBCENTRAL operation.

MASTER_BRIEF_MD = """---
created: {date}
type: master-brief
agent: WON — DBOMB ASCENDENT
build: ACAS-Phase1-v1.1
classification: DBOMBCENTRAL INTERNAL
---

# DBOMBCENTRAL — MASTER BRIEF
*Last updated by WON — {timestamp}*

---

## OPERATION OVERVIEW

**DBOMBCENTRAL** is an advanced autonomous AI development operation. The goal is a fully operational **Advanced Cognitive Autonomous System (ACAS)** — a multi-layered, self-improving AI platform capable of enterprise-grade task execution, military-standard documentation, and billion-dollar ideation processes.

The cognitive center of this operation is **CENTCOM Cortex** — the top-tier coordinator agent that routes tasks to specialist agents and maintains operational coherence across all departments.

---

## COMMAND STRUCTURE

```
DBOMBCENTRAL
└── CENTCOM CORTEX (Coordinator — Tier 1)
    ├── WON — DBOMB ASCENDENT (Specialist — active, Phase 1)
    ├── Forge Agent (Specialist — planned, Phase 2)
    ├── Sentinel Agent (Specialist — planned, Phase 2)
    ├── Nexus Agent (Specialist — planned, Phase 2)
    ├── Oracle Agent (Specialist — backlog, Phase 3)
    └── Compliance Agent (Specialist — backlog, Phase 4)
        │
        └── Shared Context Layer (Tier 3)
            ├── SQLite + FTS5 Memory Bus (active)
            ├── FAISS Vector Store (Phase 2)
            └── Neo4j Knowledge Graph (Phase 3)
```

---

## ACAS PHASES

### Phase 1 — Foundation (Active | $0 Cost)
**Stack:** Python 3.9+, Ollama/llama3.2, SQLite+FTS5, DuckDuckGo, Scrapy, Rich
- ✅ WON advisor agent operational
- ✅ Persistent SQLite memory with FTS5 full-text search
- ✅ Obsidian vault integration (Briefs, Plans, Projects, Research, Sessions)
- ✅ CENTCOM Cortex coordinator layer (Phase 1 stub)
- ✅ Agent registry (Phase 2 slots pre-defined)
- ✅ Probability-weighted predictor engine
- ✅ DuckDuckGo public source research
- 🔲 FAISS vector memory (Phase 2 upgrade)
- 🔲 Neo4j knowledge graph (Phase 3 upgrade)

### Phase 2 — Agent System Development ($0-50/month)
**Stack:** LangGraph, CrewAI, LlamaIndex, LocalAI, FAISS, Hugging Face Transformers
- Task decomposition engine
- Forge / Sentinel / Nexus specialist agents
- FAISS vector upgrade replacing FTS5
- Multi-agent communication bus

### Phase 3 — Integration & Optimization ($0-100/month)
**Stack:** AGiXT, Semantic Kernel, Neo4j, Flowise
- Neuro-symbolic hybrid reasoning layer
- Neo4j relational knowledge graph
- Causal inference framework
- System-wide benchmarks

### Phase 4 — Compliance & Deployment ($50-200/month)
**Stack:** io.net, SiliconFlow, Dify, Amazon Q Developer
- AR 25-50 compliance engine
- EU AI Act + NIST regulatory alignment
- Full audit trail system
- Oracle ideation engine (market analysis, innovation synthesis)

---

## ACTIVE PROJECTS

| Project | Phase | Status | Description |
|---------|-------|--------|-------------|
| DBOMBCENTRAL | 1 | Active | Master operation |
| ACAS | 1 | Active | 4-phase architecture |
| CENTCOM Cortex | 1 | Active | Central coordinator |
| WON Agent | 1 | Active | Advisor/tracker/brief engine |
| AI Experience Project | 1 | Active | Phase 1 experiential build |
| Anaconda Snake Game | 1 | Active | Python engine side project |
| CENTCOM Knowledge Base | 1 | Planning | Neo4j + FAISS RAG backbone |
| Agent Orchestration Layer | 2 | Planning | LangGraph + CrewAI |
| AR 25-50 Compliance Engine | 4 | Backlog | Military documentation |

---

## KNOWN CONCERNS & MITIGATIONS

| Concern | Mitigation Built Into WON |
|---------|--------------------------|
| Token limit / context truncation | SQLite FTS5 retrieval — no in-prompt injection |
| Memory loss between sessions | Persistent SQLite DB survives restarts |
| Data quality / noise | DuckDuckGo + source filtering in researcher.py |
| Computational overhead | Local Ollama, no cloud costs |
| Scalability | Modular architecture — each core/ module swappable |
| Explainability | Audit trail in sessions/, brief history in Briefs/ |
| Bias propagation | Bias engine with delta feedback loop (checkers.py) |

---

## TOOL STACK REGISTRY

| Tool | Role | Phase | Cost |
|------|------|-------|------|
| Ollama + llama3.2 | Local LLM inference | 1 | Free |
| SQLite + FTS5 | Persistent memory + search | 1 | Free |
| DuckDuckGo HTML | Public source research | 1 | Free |
| Rich | Terminal UI | 1 | Free |
| Obsidian | Knowledge vault | 1 | Free |
| FAISS | Vector similarity memory | 2 | Free |
| LangGraph | Agent orchestration | 2 | Free |
| CrewAI | Multi-agent coordination | 2 | Free |
| LlamaIndex | RAG management | 2 | Free |
| AGiXT | Production agent infra | 3 | Free |
| Neo4j | Knowledge graph | 3 | Free |
| Semantic Kernel | Symbolic+neural reasoning | 3 | Free |
| io.net | On-demand GPU clusters | 4 | Pay-as-go |
| Dify | Document + compliance gen | 4 | Free tier |

---

## FORWARD VECTORS (WON Prediction — Phase 1 Completion)

1. **Agent Task Decomposition Engine** (87%) — Phase 2 entry point. Build the engine that breaks objectives into sub-tasks. Stack: LangGraph + CrewAI.
2. **RAG Pipeline Implementation** (83%) — Connect FAISS to the existing SQLite memory system. Upgrade recall from keyword to semantic similarity.
3. **Meta-Learning Core Integration** (79%) — Layer adaptive learning on the Phase 1 bias engine. Enable WON to adjust its own reasoning weights from session feedback.

---

## HARDWARE
- Machine: User system with RX 9070 XT / 32GB RAM
- Can run locally: Qwen2.5-Coder 32B, llama3.2, mistral, phi3
- Docker MCP configured in Claude Desktop

---

*DBOMBCENTRAL — CENTCOM CORTEX | WON DBOMB ASCENDENT | ACAS-Phase1-v1.1*
"""


def write_master_brief(vault_path: str):
    """Write the master brief to the Obsidian vault root."""
    import os
    from datetime import datetime
    if not vault_path:
        return
    content = MASTER_BRIEF_MD.format(
        date=datetime.utcnow().strftime("%Y-%m-%d"),
        timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    )
    path = os.path.join(vault_path, "DBOMBCENTRAL MASTER BRIEF.md")
    os.makedirs(vault_path, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
