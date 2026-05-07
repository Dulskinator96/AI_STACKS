# DBOMBCENTRAL — AGENT WON
## DBOMB ASCENDENT | ACAS-Phase1-v1.1

---

## QUICK START (3 steps)

```
Step 1:  Extract this folder to your Desktop
Step 2:  Double-click  install_won.bat          (run once)
Step 3:  Double-click  CENTCOM_Ignition.bat     (run every time)
```

That's it. WON is running.

---

## BEFORE YOU RUN — ONE SETTING

Open `configs/won_settings.yaml` in Notepad and set your Obsidian vault path:

```yaml
obsidian_vault: "C:/Users/dulsk/Documents/WON-Vault"
```

WON will create the vault folder automatically if it doesn't exist.

---

## WHAT WON DOES

WON is your local AI advisor, tracker, planner, and brief engine.
It runs entirely on your machine — no paid API, no cloud, no data leaving your PC.

| What you type | What happens |
|---|---|
| Any question or topic | WON reasons through it with local AI |
| `brief ACAS` | Generates a structured brief → saves to Obsidian |
| `research <topic>` | Pulls public intel from DuckDuckGo → saves to Obsidian |
| `suggest` | 3 probability-weighted next steps for your project |
| `plan <project>` | Builds an execution plan note in Obsidian |
| `centcom` | Full DBOMBCENTRAL department + agent overview |
| `agents` | All agents — active, planned, and backlogged |
| `track` | ACAS phase progress |
| `projects` | All tracked projects |
| `memory 20` | Last 20 memory entries (persists across sessions) |
| `search RAG` | Full-text search across everything WON has remembered |
| `status` | System dashboard |

---

## FILE STRUCTURE

```
DBOMBCENTRAL/
├── CENTCOM_Ignition.bat     ← Launch WON (double-click)
├── install_won.bat          ← First-time setup (run once)
├── won.py                   ← WON main agent
├── requirements.txt         ← Python dependencies
│
├── core/
│   ├── brain.py             ← Local LLM via Ollama (free)
│   ├── memory.py            ← SQLite persistent memory + FTS5 search
│   ├── researcher.py        ← DuckDuckGo public source research
│   ├── obsidian.py          ← Obsidian vault writer
│   ├── brief_engine.py      ← Structured brief + plan generator
│   ├── predictor.py         ← Probability-weighted next-step engine
│   ├── project_tracker.py   ← ACAS phase + project registry
│   ├── centcom.py           ← CENTCOM Cortex coordinator layer
│   ├── agent_registry.py    ← Full agent registry (Phase 1-4)
│   ├── master_brief.py      ← Master DBOMBCENTRAL brief generator
│   ├── biases.py            ← Bias engine (adaptive weights)
│   └── checkers.py          ← Output quality heuristics
│
├── configs/
│   ├── won_settings.yaml    ← Main config (set vault path here)
│   ├── prompts.yaml         ← Experience frame + bias directives
│   └── settings.yaml        ← AI Experience Project settings
│
└── data/                    ← Auto-created on first run
    ├── won_memory.db        ← All WON memory (SQLite, persists forever)
    └── projects.json        ← Project registry (pre-seeded)
```

---

## OBSIDIAN VAULT (auto-built)

WON writes structured notes directly into your vault:

```
WON-Vault/
├── DBOMBCENTRAL MASTER BRIEF.md   ← Full operation overview
├── WON Dashboard.md               ← Live status (updated each session)
├── Briefs/                        ← Timestamped project briefs
├── Plans/                         ← Execution plans with milestones
├── Projects/                      ← Project stubs with progress logs
├── Research/                      ← Public source intel notes
└── Sessions/                      ← Session summaries + forward vectors
```

---

## FREE STACK

| Component | Tool | Cost |
|---|---|---|
| Local AI brain | Ollama + llama3.2 | Free |
| Web research | DuckDuckGo | Free |
| Persistent memory | SQLite (built into Python) | Free |
| Full-text search | SQLite FTS5 (built-in) | Free |
| Knowledge vault | Obsidian | Free |
| Terminal UI | Rich | Free |

**Total cost: $0**

---

## AGENT ARCHITECTURE (ACAS)

```
DBOMBCENTRAL
└── CENTCOM CORTEX (Coordinator)
    ├── WON ✅ active — advisor, tracker, brief, memory, research
    ├── Forge Agent 🔲 Phase 2 — build, code-gen, architecture
    ├── Sentinel Agent 🔲 Phase 2 — monitoring, validation
    ├── Nexus Agent 🔲 Phase 2 — RAG, FAISS, knowledge graph
    ├── Oracle Agent 🔲 Phase 3 — prediction, market analysis
    └── Compliance Agent 🔲 Phase 4 — AR 25-50, audit trail
```

---

## OLLAMA COMMANDS (Important Notes)

```bash
ollama run llama3.2     # run the model manually
ollama update           # update ollama
ollama list             # see downloaded models
/bye                    # exit ollama terminal
```

WON starts Ollama automatically. If the brain shows "offline", run `ollama serve` in a terminal.

---

*DBOMB ASCENDENT WON | ACAS-Phase1-v1.1 | DBOMBCENTRAL*
