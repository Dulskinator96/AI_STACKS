"""
config.py — Single source of truth for all STRATUM constants.

Eliminates AntiPattern:MagicStrings across the codebase.
No module should hardcode URLs, model names, paths, or node-type strings.
Import from here instead.
"""
# Perceptual engine constants are at the bottom of this file.
from __future__ import annotations

import os
from pathlib import Path

# ── Application ───────────────────────────────────────────────────────────────

APP_NAME    = "STRATUM"
APP_VERSION = "0.2.0"

# ── Directories ───────────────────────────────────────────────────────────────

DATA_DIR      = Path.home() / ".stratum"
DB_PATH       = DATA_DIR / "ensemble.db"
MEMORY_DB     = DATA_DIR / "agent_memory.db"
CHATROOM_DB   = DATA_DIR / "chatroom.db"
LOG_FILE      = DATA_DIR / "stratum.log"
BACKUP_DIR    = Path.home() / "Documents" / "AI_Monitor" / "backups"
OUTCOMES_FILE = Path.home() / "Documents" / "AI_Monitor" / "conv_outcomes.json"

# ── LLM endpoints ─────────────────────────────────────────────────────────────

OLLAMA_URL      = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
LM_STUDIO_URL   = os.environ.get("LM_STUDIO_URL", "http://localhost:1234")
DEFAULT_MODEL   = os.environ.get("WON_MODEL", "mistral")
CODE_MODEL      = os.environ.get("WON_CODE_MODEL", DEFAULT_MODEL)

# ── Timeouts (seconds) ────────────────────────────────────────────────────────

LLM_TIMEOUT     = 90
WEB_TIMEOUT     = 8
SANDBOX_TIMEOUT = 10
LMS_TIMEOUT     = 180

# ── Context / output limits ───────────────────────────────────────────────────

MAX_CONTEXT_CHARS    = 3000
MAX_OUTCOMES         = 200
MAX_HANDOFFS         = 4
MAX_WEB_RESULTS      = 5
MAX_SNIPPET_CHARS    = 400
MAX_SECTION_LINES    = 2000

# ── AST node type names ───────────────────────────────────────────────────────

class ASTKind:
    FUNCTION       = "FunctionDef"
    ASYNC_FUNCTION = "AsyncFunctionDef"
    CLASS          = "ClassDef"
    MODULE         = "Module"
    IMPORT         = "Import"
    IMPORT_FROM    = "ImportFrom"
    TRY            = "Try"
    EXCEPT         = "ExceptHandler"
    RAISE          = "Raise"
    CALL           = "Call"
    ASSIGN         = "Assign"


# ── File resolution skip list ─────────────────────────────────────────────────

SKIP_DIRS = frozenset({
    "__pycache__", ".venv", "venv", "env",
    "node_modules", ".git", "dist", "build",
    ".tox", ".mypy_cache", ".pytest_cache",
})

# ── Web scraping ──────────────────────────────────────────────────────────────

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DDGO_INSTANT_URL = "https://api.duckduckgo.com/"
DDGO_HTML_URL    = "https://html.duckduckgo.com/html/"

# ── Agent IDs ─────────────────────────────────────────────────────────────────

class AgentID:
    VALIDATION     = "validation"
    IMPLEMENTATION = "implementation"
    PLANNER        = "planner"
    STRATEGIST     = "strategist"
    SYNTHESIS      = "synthesis"
    MODERATOR      = "moderator"


# ── Panel stack indices (pyramid_ui.py QStackedWidget) ───────────────────────

class PanelIdx:
    GRAPH    = 0
    ENSEMBLE = 1


# ── Default target files for intent routing ───────────────────────────────────

class DefaultTarget:
    APP      = "app.py"
    PIPELINE = "pipeline.py"
    OBSIDIAN = "core/obsidian.py"
    DAEMON   = "won_daemon.py"
    BRAIN    = "core/brain.py"


# ── Chatroom ──────────────────────────────────────────────────────────────────

CHATROOM_MAX_ROUNDS      = 3
CHATROOM_MAX_MSG_CHARS   = 600
CHATROOM_TURNS_PER_ROUND = 4    # one per agent per round


# ── Agent memory ──────────────────────────────────────────────────────────────

MEMORY_EPISODIC_LIMIT = 50    # records per agent
MEMORY_SEMANTIC_LIMIT = 200   # global semantic facts
MEMORY_DECAY_DAYS     = 30    # entries older than this get lower recall weight


# ── Tool names ────────────────────────────────────────────────────────────────

class ToolName:
    SEARCH_CODE  = "search_code"
    READ_FILE    = "read_file"
    RUN_PYTHON   = "run_python"
    ANALYZE_AST  = "analyze_ast"
    WEB_SEARCH   = "web_search"
    FETCH_URL    = "fetch_url"
    GIT_LOG      = "git_log"
    DIFF_FILES   = "diff_files"
    CHECK_SYNTAX = "check_syntax"
    RUN_TESTS    = "run_tests"
    LINT_CODE    = "lint_code"


# ── Expert thinking frameworks (anti-hallucination anchors) ──────────────────
# These are documented human reasoning methodologies embedded into agent prompts.
# Grounding agents in real frameworks reduces invented/hallucinated reasoning.

class ExpertFramework:
    VALIDATION = """
Reasoning framework: Karl Popper (falsificationism) + Richard Feynman (mechanistic clarity).
- Every claim must be falsifiable. Ask: "How would we know if this is wrong?"
- Demand mechanistic clarity: "What I cannot create, I do not understand."
- Nassim Taleb: look for fragility — what breaks this under stress or rare conditions?
- Label confidence explicitly: VERIFIED / PROBABLE / UNVERIFIED / CONTRADICTED.
"""
    IMPLEMENTATION = """
Reasoning framework: Donald Knuth (precision) + Uncle Bob Martin (clean code).
- "Premature optimization is the root of all evil" — solve the problem cleanly first.
- Names are communication. A function named well needs no comment.
- Linus Torvalds: "Talk is cheap. Show me the code." — every insight must become runnable.
- Single responsibility at every level — one function, one job.
"""
    PLANNER = """
Reasoning framework: Richard Hamming (research excellence) + Edward de Bono (lateral thinking).
- Hamming: "What are the important problems in your field? Why aren't you working on them?"
  Always identify the highest-value question before answering any question.
- De Bono: escape local minima. The obvious approach is often not the best approach.
- David Allen: capture everything, clarify nothing until captured, then prioritize.
"""
    STRATEGIST = """
Reasoning framework: Claude Shannon (information theory) + Peter Drucker (effectiveness).
- Shannon: always ask "What is the information content here?" Strip noise from signal.
- Drucker: "Efficiency is doing things right. Effectiveness is doing the right things."
  First establish what the right thing is before optimizing how.
- Andy Grove: what moves the needle? What is the 10x lever? Think in systems, not symptoms.
"""
    SYNTHESIS = """
Reasoning framework: Daniel Kahneman (System 1/2) + Richard Feynman (teaching clarity).
- Kahneman: check your fast intuition (System 1) with slow deliberation (System 2).
  The synthesis should not just be fast pattern matching — it must be verified.
- Feynman technique: if you cannot explain it simply, you do not understand it yet.
  The synthesis should be explainable to a smart non-expert in one paragraph.
- Howard Gardner: intelligence is multi-modal. Synthesize across logical, spatial,
  linguistic, and interpersonal dimensions.
"""
    PERCEPTION = """
Perceptual grounding: Rao/Ballard predictive coding + Klein RPD + Barrett emotion construction.
- Rao & Ballard 1999: only prediction ERROR propagates upward — static/expected input is silent.
  "Vision is 90% prediction, 10% incoming signal." Surprise = attention. Routine = silence.
- Klein 1998 (RPD): expert intuition is k-NN in a compressed feature space built from 10k+ hours
  of feedback. Pattern match → mental simulation → commit. Confidence ∝ 1/distance to nearest match.
- Barrett 2017: emotions are predictions about body states, not hardwired reactions.
  Same arousal + "performance" context → anxiety. Same arousal + "party" context → excitement.
  Tag all emotional outputs with the context that constructed them.
- Johnson & Raye 1981: tag every hypothesis with its SOURCE. Internal (imagined, predicted) ≠
  external (sensed). Source confusion = the mechanism behind "psychic" misattribution.
  If a claim has no sensory grounding, mark it INTERNAL and downweight confidence accordingly.
- Kahneman 1973: attentional budget ~40 bits/sec into consciousness. Implement the bottleneck.
  Inattentional blindness is not a bug — it is the cost of focused processing.
"""


# ── Perceptual Engine (neuroscience-grounded) ─────────────────────────────────

# Attention bottleneck (Kahneman 1973; Simons & Chabris 1999)
ATTENTION_BUDGET      = 40     # bits/sec available for conscious processing
ATTENTION_FLOOR       = 0.30   # saliency below this → inattentional blindness
ATTENTION_DECAY       = 0.85   # per-tick salience decay for unattended signals

# Predictive coding (Rao & Ballard 1999; Friston 2005)
PREDICTION_ALPHA      = 0.15   # generative model learning rate
PREDICTION_HISTORY    = 12     # rolling window for expectation baseline
CREATIVE_SIGNAL_FLOOR = 0.62   # prediction error above this = creative signal

# Source confidence weights (Johnson & Raye 1981 — reality monitoring)
SOURCE_CONFIDENCE: dict[str, float] = {
    "external":    1.00,   # directly sensed
    "teammate":    0.85,   # reported by a peer agent
    "prediction":  0.60,   # model-generated expectation
    "memory":      0.50,   # recalled from episodic store
    "imagination": 0.30,   # internally generated / speculative
}

# Emotion circumplex coordinates (Russell 1980) — (valence, arousal) in [-1, +1]
class EmotionKind:
    FEAR      = "fear"
    JOY       = "joy"
    ANGER     = "anger"
    SADNESS   = "sadness"
    SURPRISE  = "surprise"
    CURIOSITY = "curiosity"
    CALM      = "calm"
    ALERT     = "alert"
    NEUTRAL   = "neutral"

EMOTION_CIRCUMPLEX: dict[str, tuple[float, float]] = {
    EmotionKind.FEAR:      (-0.60,  0.80),
    EmotionKind.JOY:       ( 0.80,  0.50),
    EmotionKind.ANGER:     (-0.50,  0.70),
    EmotionKind.SADNESS:   (-0.70, -0.40),
    EmotionKind.SURPRISE:  ( 0.10,  0.90),
    EmotionKind.CURIOSITY: ( 0.40,  0.60),
    EmotionKind.CALM:      ( 0.30, -0.50),
    EmotionKind.ALERT:     ( 0.20,  0.70),
    EmotionKind.NEUTRAL:   ( 0.00,  0.00),
}

# Recognition-Primed Decision (Klein 1998)
RPD_EXEMPLAR_LIMIT  = 500   # max stored exemplars per engine
RPD_K_NEIGHBORS     = 5     # k-NN top candidates
RPD_CONFIDENCE_FLOOR = 0.25  # similarity below this → low confidence, flag for deliberation

# Somatic markers (Damasio 1994)
SOMATIC_MARKER_LIMIT = 300   # max context→outcome mappings per agent
SOMATIC_DECAY_DAYS   = 60    # markers older than this get halved weight

# Cross-organism sensory constants (biological reference — informational)
# Used as narrative anchors in agent prompts; not numerically processed
class SensoryWindow:
    """Biological reference: each organism filters reality through its own bandwidth."""
    HUMAN_HEARING_HZ      = (20, 20_000)
    BAT_HEARING_HZ        = (20, 200_000)
    DOLPHIN_HEARING_HZ    = (200, 150_000)
    HUMAN_VISION_NM       = (380, 740)
    MANTIS_SHRIMP_NM      = (300, 720)     # + UV + polarized
    SNAKE_IR_RANGE_NM     = (5_000, 30_000)  # thermal IR
    HUMAN_SACCADE_HZ      = 3              # saccades per second
    HUMAN_FLICKER_FUSION  = 60             # Hz (vs insect ~250 Hz)
    ATTENTION_CONSCIOUS   = 40             # bits/sec (Kahneman)
    ATTENTION_AVAILABLE   = 11_000_000     # bits/sec (total sensory bandwidth)


# ── DETCORE — DBOMBCENTRAL Constrained Reasoning Anchor ──────────────────────
# DETCORE binds every reasoning call to retrieval-grounded context. WICKCORE
# (the constrained processor) reasons only over fragments injected by SHARDFEED.

DETCORE_SPEC_PATH = Path(__file__).parent / "DETCORE.md"

class DBombLexicon:
    """DBOMBCENTRAL-branded names for the constrained-reasoning chain.
    No public/famous names — every label is project-owned."""
    ANCHOR        = "DETCORE"        # the spec itself
    PROCESSOR     = "WICKCORE"       # constrained reasoning module
    RETRIEVER     = "SHARDFEED"      # retrieval layer
    CONTEXT_STORE = "DETBANK"        # context / memory store
    PROTOCOL      = "FUSELINE"       # strict execution order
    CLASSIFIER    = "PRIMEKEY"       # domain classification step
    VALIDATOR     = "TRIPGATE"       # consistency / citation gate
    OUTPUT        = "YIELDCAST"      # formatted release
    REGISTRY      = "BLASTRADIUS"    # source whitelist registry
    CITATIONS     = "CHARGELOG"      # claim → fragment citation log
    SOP_CLAUSE    = "DETSPEC"        # SOP precision enforcement
    PIPELINE      = "DETCHAIN"       # full chain name


class DBombButton:
    """Floating-widget control surface labels (renamed from generic terms).
    Each label is the operator's grip on a higher concept in DETCORE."""
    PRIMELATCH = "PRIMELATCH"   # was: Attach   — prime WICKCORE with DETBANK fragments
    DETHUB     = "DETHUB"       # was: Hub      — DBOMB command switchboard
    BREACHGATE = "BREACHGATE"   # was: Portal   — two-entity breach room
    WICKFOCUS  = "WICKFOCUS"    # was: Claude   — focus the constrained processor


# Domain tags for BLASTRADIUS (PRIMEKEY classification targets)
class BlastDomain:
    COG     = "COG"   # Cognition / Psychology
    MEM     = "MEM"   # Memory architecture
    VIS     = "VIS"   # Sight / Vision
    AUD     = "AUD"   # Hearing / Audio
    COD     = "COD"   # Code / Engineering
    CRE     = "CRE"   # Creative production / SOPs
    TRN     = "TRN"   # Transformer / ML reasoning substrate
    GENERAL = "GENERAL"


# Floating-widget latch defaults
WICK_DOCK_OFFSET_X = 24    # px from right edge of primary screen when latched
WICK_DOCK_OFFSET_Y = 24    # px from top edge of primary screen when latched
WICK_DOCK_WIDTH    = 320   # widget fixed width when latched


# ── HELIXCHAIN — code DNA → tag → prompt synthesis pipeline ──────────────────
# Static-analysis chain that converts a folder of source into:
#   1) DNA Map (HELIXREAD)
#   2) Tagged behavior catalog (TAGFUSE)
#   3) DETCORE-aligned anchor prompt (ANCHORFORGE)

HELIX_DB_PATH       = DATA_DIR / "helixchain.sqlite"
HELIX_SCAN_EXTS     = (".py",)             # extend to ".js", ".ts" once parsers exist
HELIX_MAX_FILE_KB   = 512                  # skip very large generated files
HELIX_MAX_FUNCS_OUT = 200                  # cap functions surfaced into anchor prompt

class HelixTag:
    """TAGFUSE behavior categories — derived from operator's reframe."""
    RETRIEVAL   = "retrieval"
    GENERATION  = "generation"
    PROCESSING  = "processing"
    MEMORY      = "memory"
    ROUTING     = "routing"
    PERCEPTION  = "perception"
    VALIDATION  = "validation"
    UI          = "ui"
    PERSISTENCE = "persistence"
    UNKNOWN     = "unknown"


class HelixSeverity:
    """CLAUDE.md constraint-check severities (constraint_report output)."""
    INFO    = "INFO"
    WARN    = "WARN"
    VIOLATE = "VIOLATE"


# ── PYRAMID COMPARTMENT — cognitive OS coordinator ───────────────────────────
# Six-layer architecture: Rooms (interface) → IntentRouter → MemoryCore →
# CodeDNA → ReasoningEngine → Execution+Output. Reuses existing STRATUM engines.

PYRAMID_DB_PATH = DATA_DIR / "pyramid_compartment.sqlite"

class RoomKind:
    """Five rooms in the interface layer. Each is a structured subsystem."""
    ANALYSIS  = "analysis"   # code inspection + DNA extraction (helixchain)
    REASONING = "reasoning"  # task decomposition + planning
    SANDBOX   = "sandbox"    # controlled execution (executor.py)
    DOCUMENT  = "document"   # structured doc emission (AR 25-50, briefs)
    MEMORY    = "memory"     # DETBANK retrieval + node-graph access


class DocFormat:
    """Structured document formats supported by DocumentRoom."""
    AR_25_50      = "ar_25_50"        # Army memorandum format
    SYSTEM_BRIEF  = "system_brief"    # operator-facing summary
    REPORT        = "report"          # generic structured report
    ANCHOR        = "anchor"          # DETCORE-aligned anchor (via HELIXCHAIN)


# AR 25-50 memorandum scaffold (Army Regulation 25-50: Preparing and Managing
# Correspondence). The format is public-domain federal regulation.
AR_25_50_TEMPLATE = """\
{office_symbol}
{date}

MEMORANDUM FOR {recipient}

SUBJECT: {subject}

{body}

{poc_block}

{signature_block}
"""


class TaskStatus:
    """Pyramid task lifecycle states."""
    PENDING   = "pending"
    ROUTED    = "routed"
    EXECUTING = "executing"
    DONE      = "done"
    FAILED    = "failed"


PYRAMID_REASONING_STEPS = (
    "input", "structure", "transformation", "validation", "output",
)


# ── SIMCORE — deterministic cognitive simulation engine ──────────────────────
# Three strictly-separated layers per spec:
#   A. Cognitive Core   (simcore_director.py)  — designs, never mutates
#   B. Simulation Core  (simcore.py)           — single source of truth
#   C. Render Core      (simcore_render.py)    — projections, never mutate

SIMCORE_DB_PATH = DATA_DIR / "simcore.sqlite"

class EventStatus:
    """Lifecycle of a proposed Event before / after validation."""
    PROPOSED  = "proposed"
    VALIDATED = "validated"
    REJECTED  = "rejected"
    APPLIED   = "applied"


class RuleViolation:
    """Why an Event was rejected by ValidationLayer."""
    UNKNOWN_RULE       = "unknown_rule"
    MISSING_ENTITY     = "missing_entity"
    PRECONDITION_FAIL  = "precondition_fail"
    GRAPH_INCONSISTENT = "graph_inconsistent"
    CORRUPTED_BRANCH   = "corrupted_branch"


class RenderChannel:
    """Multi-modal projection channels. All read-only — never mutate state."""
    VISUAL  = "visual"   # ASCII / structural map of rooms + entities
    AUDIO   = "audio"    # event → cue mapping
    TEXTURE = "texture"  # entity → asset slug
    TEXT    = "text"     # operator-facing summary


# Genesis snapshot identifier (root of the snapshot chain).
SIMCORE_GENESIS_ID = "GENESIS"
SIMCORE_TICK_TIMEOUT_S = 10  # max seconds for one tick to complete

# State schema version. Baked into WorldState.to_canonical_json as ``_v``.
# Increment on any structural change to WorldState fields. Old snapshots
# remain verifiable because their state_json was written under the version
# in effect at that time (the hash is over the literal stored bytes).
SIMCORE_SCHEMA_VERSION = 1


# Demo world seed — minimal Zelda-like room graph used by `python -m simcore demo`
SIMCORE_DEMO_WORLD: dict = {
    "rooms": {
        "courtyard": {"name": "Stone Courtyard",
                      "exits": {"north": "great_hall", "down": "cellar"}},
        "great_hall": {"name": "Great Hall",
                       "exits": {"south": "courtyard"}},
        "cellar":    {"name": "Damp Cellar",
                      "exits": {"up": "courtyard"}},
    },
    "entities": {
        "player":  {"kind": "actor", "room": "courtyard", "holds": []},
        "lantern": {"kind": "item",  "room": "cellar", "lit": False},
        "iron_key":{"kind": "item",  "room": "great_hall"},
        "rune_door":{"kind":"fixture","room":"cellar", "locked": True},
    },
    "variables":   {"torch_lit": False, "ticks": 0},
    "global_flags":[],
}


# ── Engineering Core (binding contract for self-modifying call sites) ────────
# Source of truth: ENGINEERING_CORE.md alongside CLAUDE.md and DETCORE.md.
# Inject ENGINEERING_CORE_PROMPT into any LLM system prompt that proposes,
# generates, or modifies ai-monitor source code (e.g. proposal_engine,
# conv_programming). Loaded once at import; missing file → empty string so
# `import config` never fails.

ENGINEERING_CORE_PATH: Path = Path(__file__).parent / "ENGINEERING_CORE.md"

try:
    ENGINEERING_CORE_PROMPT: str = ENGINEERING_CORE_PATH.read_text(
        encoding="utf-8"
    )
except OSError:
    ENGINEERING_CORE_PROMPT = ""


# ── Game Mode (emulation + sensory routing contract) ─────────────────────────
# Source of truth: GAME_MODE.md alongside ENGINEERING_CORE.md, DETCORE.md.
# Pulled explicitly by callers in the emulator/sensory domain — NOT
# auto-injected into general code-generation prompts (would over-constrain).

GAME_MODE_PATH: Path = Path(__file__).parent / "GAME_MODE.md"

try:
    GAME_MODE_PROMPT: str = GAME_MODE_PATH.read_text(encoding="utf-8")
except OSError:
    GAME_MODE_PROMPT = ""




