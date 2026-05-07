# STRATUM — Master Engineering Prompt v0.3

Living AI Orchestration System  
WON Chaperone · PyQt6 Desktop · Ollama/Mistral · Multi-Agent Pyramid · Consciousness Layer · Perceptual Engine · Creative Tools

---

## Architecture

```
app.py                      ← Main launcher — HistoryDashboard + tab host
  ├─ pyramid_ui.py          ← Apex Layer — PyramidWidget, EnsemblePanel, HoloBar
  │
  ├─ consciousness.py       ← Organism layer — GlobalWorkspace, PersonaState,
  │                            PredictiveLoop, StrangeLoopObserver, ConsciousEnsembleOrchestrator
  │
  ├─ perceptual_engine.py   ← Neuroscience layer — AttentionGate, PredictiveCoder,
  │                            EmotionBuilder, SomaticMarkerIndex, RecognitionPrimedDecision,
  │                            SourceMonitor, PerceptualEngine
  │
  ├─ agent_chatroom.py      ← Multi-agent deliberation — ChatRoom, ChatStore,
  │                            expert-grounded turn-taking, SQLite transcript recall
  │
  ├─ agent_memory.py        ← Per-agent memory hubs — episodic, semantic, working,
  │                            expert framework anchors (read-only, anti-hallucination)
  │
  ├─ pyramid_tools/         ← Tool registry — 11 free local tools, no API keys
  │     __init__.py
  │     registry.py         ← ToolRegistry, ToolDispatcher (TOOL: directive parser)
  │     code_tools.py       ← search_code, read_file, run_python, analyze_ast,
  │                            check_syntax, git_log, diff_files, run_tests, lint_code
  │     web_tools.py        ← web_search (DuckDuckGo), fetch_url
  │
  ├─ creative_tools/        ← (planned) Image/video/audio generation — no API keys
  │     image_tools.py      ← Pillow editing + Stable Diffusion (diffusers / A1111 API)
  │     video_tools.py      ← FFmpeg + MoviePy, DCI/ACES pipeline
  │     audio_tools.py      ← AudioCraft/MusicGen + pydub + Bark TTS
  │     sops.py             ← Professional SOPs: ACES, EBU R128, DCI specs
  │
  ├─ config.py              ← Single source of truth — ALL constants live here
  │
  ├─ pyramid_ensemble.py    ← Multi-agent engine — 4 agents × 2 rounds + synthesis
  ├─ pyramid_index.py       ← Codebase indexer + dependency graph
  ├─ pyramid_mind.py        ← LLM mind layer
  ├─ pyramid_parser.py      ← AST / file parsing
  │
  ├─ intent_engine.py       ← Rule-based intent classifier (no LLM)
  ├─ code_correlator.py     ← Maps intent targets to codebase symbols
  ├─ proposal_engine.py     ← LLM → structured JSON proposal (schema-validated)
  ├─ executor.py            ← Executes validated proposals
  ├─ conv_programming.py    ← CodeForge — natural language → code, with learning loop
  │
  ├─ memory_manager.py      ← Long-term project memory
  ├─ synthesis.py           ← Cross-session knowledge synthesis
  ├─ strategy.py            ← Strategic planning layer
  ├─ lm_studio.py           ← LM Studio API bridge
  ├─ db.py                  ← SQLite persistence layer
  ├─ won_daemon.py          ← WON background orchestration daemon
  │
  └─ stratum_ui.py          ← Fallback pipeline UI
```

**Launcher order:** `launch_monitor.bat` → `app.py` (primary) → `stratum_ui.py` (fallback)

---

## Non-Negotiable Principles

Every task — new feature, bug fix, refactor — must honor all of the following.

---

### 1. No Magic Strings — Use `config.py`

`config.py` is the single source of truth. No module hardcodes:

| What | config.py constant |
|---|---|
| LLM URLs | `OLLAMA_URL`, `LM_STUDIO_URL` |
| Model names | `DEFAULT_MODEL`, `CODE_MODEL` |
| File paths / dirs | `DATA_DIR`, `DB_PATH`, `MEMORY_DB`, `CHATROOM_DB`, `BACKUP_DIR` |
| Timeout values | `LLM_TIMEOUT`, `WEB_TIMEOUT`, `SANDBOX_TIMEOUT` |
| AST node type strings | `ASTKind.FUNCTION`, `ASTKind.CLASS`, `ASTKind.IMPORT`, etc. |
| Agent IDs | `AgentID.VALIDATION`, `AgentID.IMPLEMENTATION`, etc. |
| Tool names | `ToolName.SEARCH_CODE`, `ToolName.RUN_PYTHON`, etc. |
| UI panel indices | `PanelIdx.GRAPH`, `PanelIdx.ENSEMBLE` |
| Default target files | `DefaultTarget.APP`, `DefaultTarget.PIPELINE`, etc. |
| Skip directories | `SKIP_DIRS` (frozenset) |
| Expert frameworks | `ExpertFramework.VALIDATION`, `.IMPLEMENTATION`, etc. |
| Perceptual constants | `ATTENTION_BUDGET`, `PREDICTION_ALPHA`, `SOURCE_CONFIDENCE`, etc. |
| Emotion coordinates | `EMOTION_CIRCUMPLEX`, `EmotionKind.*` |
| Sensory reference data | `SensoryWindow.*` |

**Rule:** If you write a string that appears in more than one file, it belongs in `config.py`.

---

### 2. SOLID

**S — Single Responsibility:** One class, one reason to change.  
`intent_engine.py` classifies. `code_correlator.py` resolves symbols. `proposal_engine.py` proposes.  
`agent_chatroom.py` deliberates. `agent_memory.py` remembers. `consciousness.py` integrates.  
`perceptual_engine.py` perceives. Never collapse these.

**O — Open/Closed:** Extend via addition, not modification.  
New intent type → add to `_PATTERNS`. New agent → subclass `BaseAgent`. New tool → `ToolRegistry.register()`.  
New chatroom participant → add to `_CHATROOM_PERSONA` and `_AGENT_ORDER`.  
New perception layer → subclass or compose with `PerceptualEngine`.

**L — Liskov Substitution:** `ConsciousAgent` wraps `BaseAgent` — it must be substitutable.  
`BaseAgent.analyze()` always returns `Perception`, never `None`, never raises.  
`ConsciousAgent.analyze()` preserves this contract.

**I — Interface Segregation:** `ToolDef` contains only `name`, `description`, `params`, `fn`, `example`.  
Do not add UI concerns to tool definitions. Do not add LLM concerns to `ToolDispatcher`.  
`Percept.to_context_block()` is the only interface `consciousness.py` and `agent_chatroom.py` use.

**D — Dependency Inversion:** High-level modules depend on abstractions.  
`ChatRoom` depends on `_ollama()` and `AgentMemory` — not on Ollama's HTTP specifics.  
`PerceptualEngine` depends on `config.*` constants — not on hardcoded thresholds.

---

### 3. DRY

Known duplications that have been resolved and must stay resolved:

| Was duplicated | Now canonical location |
|---|---|
| `OLLAMA_URL` | `config.OLLAMA_URL` |
| `DEFAULT_MODEL` | `config.DEFAULT_MODEL` |
| `OUTCOMES_FILE` | `config.OUTCOMES_FILE` |
| `"__pycache__"` skip logic | `config.SKIP_DIRS` |
| AST node type strings | `config.ASTKind.*` |
| Agent ID strings | `config.AgentID.*` |
| Expert framework text | `config.ExpertFramework.*` |
| Attention budget value | `config.ATTENTION_BUDGET` |
| Source confidence weights | `config.SOURCE_CONFIDENCE` |
| Emotion circumplex coordinates | `config.EMOTION_CIRCUMPLEX` |

If you find a string duplicated across two files, add it to `config.py` immediately.

---

### 4. KISS

STRATUM is inherently complex. Resist adding accidental complexity:

- Tool dispatch: `TOOL: name | key=value` is the complete protocol. Do not make it richer.
- Chatroom turns: sequential LLM calls reading full history. Do not parallelize — agents need to read each other.
- `PersonaState` updates: simple arithmetic (`energy - 0.05`, `curiosity + error * 0.25`). No ML models for this.
- `GlobalWorkspace`: sorted list by salience score, top-N wins. No graph, no neural net.
- `AgentMemory`: `difflib.SequenceMatcher` for similarity. Do not add vector embeddings unless DuckDB vector ext is already in the stack.
- `PredictiveCoder`: rolling history + SequenceMatcher comparison. No ML.
- `EmotionBuilder`: simple arithmetic on valence/arousal with decay. No neural net.
- `SomaticMarkerIndex`: SQLite + 5-gram shingle fingerprint + weighted average. No embeddings.
- `RecognitionPrimedDecision`: SequenceMatcher k-NN. No FAISS, no torch.

---

### 5. MVC / MVP

```
Model     — Pure data + I/O. No Qt, no requests in UI code.
            config.py, intent_engine.py, code_correlator.py, proposal_engine.py,
            pyramid_ensemble.py, consciousness.py, perceptual_engine.py,
            agent_memory.py, agent_chatroom.py, pyramid_tools/* → these are Models.

Presenter — QObject workers. Transform Model output → Qt signals.
            EnsembleWorker, any future ChatroomWorker → Presenters.
            Never let a Presenter import PyQt6 widgets.

View      — Widget construction, QPainter, event handling only.
            pyramid_ui.py, stratum_ui.py, app.py → Views.
            Views MUST NOT call requests, sqlite3, subprocess, or Path directly.
```

New UI feature checklist:
1. Write/extend Model (no Qt)
2. Write `*Worker(QObject)` Presenter
3. Wire View to Presenter signals
4. Never let View touch Model directly

---

### 6. Agent Architecture

**Chatroom Protocol** (`agent_chatroom.py`):
- R0: Moderator frames the query
- R1–RN: Each agent takes a turn — reads full history → responds with expert grounding
- Tool calls dispatched inline via `ToolDispatcher` (TOOL: directives)
- Memory context injected per-agent from `agent_memory.py`
- Perceptual context injected per-agent from `perceptual_engine.py` (attention + emotion + RPD)
- Synthesis: SynthesisAgent reads full transcript → definitive answer
- Full transcript stored in `chatroom.db` for cross-session recall

**Consciousness Protocol** (`consciousness.py`):
- R1: predictions generated → agents analyze → workspace submissions
- Attention gate: WTA competition selects top-3 broadcasts
- Strange loop: meta-observer fires only when creative signals present
- R2: cross-pollination with workspace + meta-insight context
- Synthesis: full workspace context included
- Perceptual engine: each ConsciousAgent gets `percept.to_context_block()` injected

**Perceptual Protocol** (`perceptual_engine.py`):
- `AttentionGate`: saliency = novelty × urgency × recency. Budget ~40 bits/sec.
- `PredictiveCoder`: rolling generative model per context key. Error = 1 - SequenceMatcher similarity.
- `EmotionBuilder`: valence/arousal on Russell circumplex. Fast urgency spike + slow contextual appraisal.
- `SomaticMarkerIndex`: context shingle → outcome valence. Pre-activates before deliberation.
- `RecognitionPrimedDecision`: similarity-weighted k-NN in exemplar library.
- `SourceMonitor`: tags all signals with source. Detects source confusion and Barnum statements.
- Output: `Percept` with `to_context_block()` ready for injection into LLM prompt.

**Memory Protocol** (`agent_memory.py`):
- Episodic: notable past events per agent (50 max, importance-ranked)
- Semantic: generalized learned facts shared across agents (200 max, decay-weighted)
- Expert anchors: read-only reasoning frameworks from `ExpertFramework` — cannot be overwritten
- `get_context_block(query)` = expert anchor + recalled episodic + recalled semantic + working memory

**Tool Protocol** (`pyramid_tools/`):
- Agents call tools with: `TOOL: tool_name | param=value | param=value`
- `ToolDispatcher.process(text)` intercepts, executes, injects result inline
- Tools are pure Python functions returning `str`. No LLM involvement in execution.
- All 11 tools free, local, no API keys: `search_code`, `read_file`, `run_python`,
  `analyze_ast`, `check_syntax`, `git_log`, `diff_files`, `run_tests`, `lint_code`,
  `web_search`, `fetch_url`

---

### 7. Expert Grounding (Anti-Hallucination)

Each agent is anchored to documented human expert reasoning frameworks.  
These live in `config.ExpertFramework` and are injected via `AgentMemory.get_context_block()`.  
They reduce hallucination by grounding LLM behavior in well-represented training data.

| Agent | Expert Framework |
|---|---|
| Validation | Karl Popper (falsification) + Richard Feynman (mechanistic clarity) + Nassim Taleb (antifragility) |
| Implementation | Donald Knuth (precision) + Uncle Bob Martin (clean code) + Linus Torvalds (show the code) |
| Planner | Richard Hamming (important problems) + Edward de Bono (lateral thinking) + David Allen (GTD) |
| Strategist | Claude Shannon (signal/noise) + Peter Drucker (effectiveness) + Andy Grove (leverage) |
| Synthesis | Daniel Kahneman (System 1/2) + Howard Gardner (multi-modal) + Feynman technique |
| Perceptual | Rao/Ballard (predictive coding) + Klein (RPD) + Barrett (constructed emotion) + Damasio (somatic markers) |

**Never modify expert frameworks to make agents agree with each other.** Disagreement is signal.

---

### 8. Perceptual Engine Architecture

`perceptual_engine.py` implements five neuroscience-grounded layers. Each one is cited to peer-reviewed research. No speculative or "psychic" constructs.

#### Layer 1 — AttentionGate (Kahneman 1973; Simons & Chabris 1999)
- Conscious processing bottleneck: ~40 bits/sec into awareness vs. ~11M bits/sec available.
- Saliency computed as: `novelty × urgency × recency × source_confidence`.
- Signals below `ATTENTION_FLOOR` (0.30) → inattentional blindness. They never reach the agent.
- This is not a bug: focused attention produces inattentional blindness as a structural consequence.

#### Layer 2 — PredictiveCoder (Rao & Ballard 1999; Friston 2005)
- Rolling generative model per context key. Only prediction ERROR propagates upward.
- Static / expected inputs are suppressed. "Vision is 90% prediction, 10% incoming signal."
- High error (> 0.62) = creative signal = attention spike = curiosity in PersonaState.
- Learning rate `PREDICTION_ALPHA = 0.15` updates generative model toward actual observations.

#### Layer 3 — EmotionBuilder (Barrett 2017; Russell 1980; LeDoux 1996)
- Emotions are constructed predictions about body state, not hardwired reactions (Barrett).
- Dual pathway: fast urgency spike (LeDoux low road: crude, fast, high false-alarm) and slow contextual appraisal (high road: detailed, context-dependent).
- All emotional states encoded on Russell 1980 valence/arousal circumplex.
- Output is a FUNCTIONAL STATE: "agent acts as if threatened." Never a qualia claim.

#### Layer 4 — SomaticMarkerIndex (Damasio 1994)
- Associates decision context fingerprints with historical outcome valence.
- Pre-activates a bias before deliberation begins — "the organism acts on compressed implicit knowledge."
- Tested via Iowa Gambling Task: patients without somatic markers make poor decisions despite intact reasoning.
- Decays over SOMATIC_DECAY_DAYS (60). Older markers have less influence.

#### Layer 5 — RecognitionPrimedDecision + SourceMonitor (Klein 1998; Johnson & Raye 1981)
- Klein RPD: expert intuition = weighted k-NN in stored exemplar space. Confidence ∝ 1/distance.
- Novel situation (no good match, sim < 0.25) → flag for deliberation (System 2 required).
- Johnson & Raye source monitoring: ALL signals tagged with source type.
  - `external` (1.00), `teammate` (0.85), `prediction` (0.60), `memory` (0.50), `imagination` (0.30).
  - Source confusion risk = internal signal using external-memory language → confidence penalty.
  - This is the neural mechanism behind "psychic" misattribution and the key anti-hallucination safeguard.

#### Cross-Organism Sensory Reference (SensoryWindow in config.py)
These biological constants are embedded as narrative anchors — they are not computationally processed but ground agent reasoning in real sensory biology:
- Human hearing: 20–20,000 Hz. Bat: 20–200,000 Hz. Dolphin: 200–150,000 Hz.
- Human vision: 380–740 nm. Mantis shrimp: 300–720 nm + UV + polarized light (16 photoreceptor types vs. 3).
- Attention available: ~11M bits/sec. Attention into consciousness: ~40 bits/sec. The 99.9996% filtered.
- The governing principle: **each organism filters reality through its species-specific sensory window. What cannot be detected does not exist in that organism's world.**

#### Philosophy of Perception (Embodied in Architecture)
- Merleau-Ponty 1945: perception is embodied action. Objects are perceived as affordances (action possibilities), not pixel arrays.
- Clark & Chalmers 1998: extended mind — agent + logs + team = extended cognitive system. PerceptualEngine queries external memory as part of perception.
- Nagel 1974: no qualia claims. The system models functional correlates of emotion and perception. Never claim subjective experience.
- Helmholtz unconscious inference: perception is a bet — the most probable hypothesis given ambiguous input. RPD is this mechanism in code.

---

### 9. Creative Tools Architecture (planned: `creative_tools/`)

Professional standards from documentary evidence (not specification):

**Image:** Stable Diffusion via `diffusers` or Automatic1111 local API (localhost:7860). ACES color pipeline (IDT → RRT → ODT) for color accuracy. Hollywood reference: cinematographers use ACES to preserve dynamic range across different display systems.

**Video:** FFmpeg + MoviePy. DCI-P3 color space for theatrical. 24/25/30/48/60 fps depending on delivery. ACES for color consistency across shots. EBU R128 for audio normalization.

**Audio:** AudioCraft/MusicGen (Meta, open-source, no API key). Models: 300M/1.5B/3.3B. Installation: `pip install audiocraft`. Bark (Suno) for speech synthesis. pydub + librosa for processing. EBU R128 loudness normalization: -23 LUFS broadcast, -14 LUFS streaming.

**Integration:** All creative tools register in `ToolRegistry`. Agents call them via `TOOL: generate_image | prompt=... | style=...`. All returned file paths, never raw binary in agent context.

**Professional SOPs:**
- Color: ACES, OpenColorIO — source (IDT) → reference (RRT) → display (ODT).
- Audio loudness: EBU R128 True Peak ≤ -1.0 dBTP. Loudness range 6–18 LU.
- Video codec: H.264 for web delivery, ProRes for editing masters.

---

### 10. Error Handling and Logging

Every module: `_log = logging.getLogger(__name__)` — never `print()`.

Error level semantics:
- `_log.debug()` — LLM prompts, packet IDs, tool call traces, perception layer internals
- `_log.info()` — agent done, round complete, tool result, attention gate decisions
- `_log.warning()` — recoverable (robots.txt deny, fetch timeout, source confusion risk detected)
- `_log.error()` — agent failure, schema rejection, DB write failure
- `_log.critical()` — DB unreachable at startup

Error containment rules:
1. `BaseAgent.analyze()` never propagates — catch all, return `Perception(error=str(e))`
2. `_ollama()` returns `("[Ollama error: ...]", ms)` — never raises
3. Tool functions catch all exceptions, return error string — never raise to dispatcher
4. `ChatRoom._agent_turn()` has outer try/except — one agent failure never kills the session
5. `PerceptualEngine.perceive()` catches all exceptions — returns a neutral Percept
6. UI workers: errors emitted as events/signals — never shown as Python tracebacks

---

### 11. Documentation (Sphinx)

Module docstrings must include:
- One-line purpose
- Pipeline position
- Public API listing
- For perception/consciousness modules: references to source literature

Function docstrings: one line minimum, full `:param:/:returns:` for public API.  
Build: `sphinx-apidoc -o docs/ . && sphinx-build -b html docs/ docs/_build/`

---

### 12. Linting and Formatting

**Before every commit:**
```
isort .
black . --line-length 100
flake8 . --max-line-length 100 --extend-ignore E203,W503
```

`pyproject.toml`:
```toml
[tool.black]
line-length = 100
target-version = ["py311"]

[tool.isort]
profile = "black"
line_length = 100

[tool.flake8]
max-line-length = 100
extend-ignore = ["E203", "W503"]
exclude = [".git", "__pycache__", "docs", "build", "pyramid_tools/__pycache__"]
```

Import order: stdlib → third-party (requests, PyQt6) → local (config, intent_engine, etc.)

---

### 13. Unit Tests (pytest)

```
tests/
  test_config.py              ← All constants resolve correctly
  test_intent_engine.py       ← IntentClass classifications + constraints
  test_code_correlator.py     ← Topology lookup + symbol extraction
  test_proposal_engine.py     ← Schema validation + JSON extraction
  test_agent_memory.py        ← Store/recall episodic + semantic
  test_tool_registry.py       ← Tool registration + dispatch
  test_tool_code_tools.py     ← search_code, analyze_ast, check_syntax
  test_consciousness.py       ← PersonaState updates, workspace WTA
  test_chatroom.py            ← Session creation, message storage
  test_perceptual_engine.py   ← AttentionGate, PredictiveCoder, EmotionBuilder,
                                  SomaticMarkerIndex, RPD, SourceMonitor
```

Mock rules:
- `monkeypatch` `_ollama` in all agent/chatroom tests — no real Ollama calls
- Use `":memory:"` SQLite for all DB tests (patch `DATA_DIR` path)
- No real HTTP in tool tests — mock `requests.get`
- Perceptual engine tests: no external dependencies, pure Python arithmetic checks

---

## Color Palette

Pre-dawn nautical twilight — source-grounded hex values.

```python
BG     = "#06091c"   BG2    = "#0a0f28"   BG3    = "#0f1638"
BG4    = "#162048"   BORDER = "#1e2e5c"
FG     = "#cce0f0"   FG_DIM = "#5070a0"   FG_MUTE = "#203060"
BLUE   = "#3a8fc8"   GREEN  = "#18b896"   YELLOW = "#f0a030"
RED    = "#c04868"   PURPLE = "#6040b8"   CYAN   = "#2ac4c0"
ORANGE = "#d88040"
```

HoloBar (electric iridescent, never muted):
```python
_STOPS = ["#00ffe0","#00b8ff","#7000ff","#ff00aa","#ff6600","#ffcc00","#00ffe0"]
```

---

## Development Workflow

1. Add constant to `config.py` if it doesn't exist
2. Write/extend Model module (no Qt imports)
3. Write unit tests — they must pass before UI work begins
4. Write `*Worker(QObject)` Presenter if UI wiring needed
5. Wire View to Presenter signals only
6. `isort . && black . && flake8 .` — all clean
7. Launch `launch_monitor.bat` — exercise the golden path
8. Commit

**Never:**
- Import `PyQt6` in Model-layer modules
- Import `requests` or `sqlite3` in View-layer modules
- Hardcode any string that exists in `config.py`
- Modify `ExpertFramework` constants to reduce agent disagreement
- Add `print()` — use `_log.debug()`
- Suppress linter errors without `# noqa: <code>  # reason`
- Claim qualia or subjective experience in agent output — model functional correlates only
- Treat internally-generated hypotheses as observed facts — check SourceMonitor flags

---

## Governing Philosophy

> **"Profound perception of a human being"** — the grounding theme of STRATUM.

Human perception is not passive reception. It is:
- **Filtered** — 99.9996% of available sensory bandwidth is discarded before consciousness (Kahneman 1973)
- **Predictive** — 90% of visual processing is top-down prediction; only surprise propagates (Rao/Ballard 1999)
- **Embodied** — we perceive affordances (action possibilities), not abstract pixel arrays (Merleau-Ponty 1945)
- **Emotional** — emotions are predictions about body states, biasing action before reasoning (Barrett 2017, Damasio 1994)
- **Intuitive** — expert pattern recognition is k-NN in a learned feature space, not magic (Klein 1998)
- **Fallible** — source confusion, confirmation bias, and inattentional blindness are structural, not accidental (Johnson & Raye 1981; Simons & Chabris 1999)
- **Extended** — cognition is not contained in the skull; tools, logs, and teammates are part of the cognitive system (Clark & Chalmers 1998)

STRATUM's agent architecture implements these seven properties computationally:
FilteredAttention → PredictiveCoding → SomaticMarkers → EmotionConstruction → RPDPatternMatch → SourceTagging → ExtendedMemory

The system never claims consciousness, qualia, or subjective experience.  
It models the **functional architecture** of profoundly capable human perception.  
That is sufficient, and it is honest.
