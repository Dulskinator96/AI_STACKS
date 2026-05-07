# ============================================================
# AI MONITOR — app.py  (RESTORED + HARDENED)
# Cursor's path safety + frozen-exe fixes KEPT.
# All pipeline, WON, MemPalace, Obsidian, search, sync RESTORED.
# ============================================================

import sys, os, json, threading, time, difflib, struct, tempfile
from datetime import datetime
from pathlib import Path


# ── Frozen-exe comtypes cache fix (Cursor) ─────────────────
def _prepare_comtypes_cache_for_frozen_exe():
    if not getattr(sys, "frozen", False):
        return
    parent = os.path.join(tempfile.gettempdir(), "comtypes_cache")
    if os.path.exists(parent) and not os.path.isdir(parent):
        try: os.remove(parent)
        except OSError: pass
    try: os.makedirs(parent, exist_ok=True)
    except OSError: pass
    base = os.path.splitext(os.path.basename(sys.executable))[0]
    pymaj, pymin = sys.version_info[:2]
    gen_dir = os.path.join(parent, f"{base}-{pymaj}{pymin}")
    if os.path.exists(gen_dir) and not os.path.isdir(gen_dir):
        try: os.remove(gen_dir)
        except OSError: pass
    try: os.makedirs(gen_dir, exist_ok=True)
    except OSError: pass

_prepare_comtypes_cache_for_frozen_exe()

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QSystemTrayIcon, QMenu,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QLineEdit,
    QSplitter, QTabWidget, QProgressBar, QDialog,
    QStatusBar,
)
from PyQt6.QtGui  import QIcon, QColor, QFont
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal

import requests

# ── Optional integrations (graceful offline) ─────────────────
DAVINCI_OK = False   # removed — not core to STRATUM purpose
UNREAL_OK  = False   # removed — not core to STRATUM purpose

try:
    import validation_agent as _ah   # upgraded drop-in: 3-tier web validation
    AH_OK = True
except Exception:
    try:
        import anti_hallucination as _ah  # fallback to local-only
        AH_OK = True
    except Exception:
        AH_OK = False

try:
    import memory_manager as _mm
    MM_OK = True
except Exception:
    MM_OK = False

try:
    import agent_protocol as _ap
    AP_OK = True
except Exception:
    AP_OK = False

try:
    import conv_programming as _cp
    CP_OK = True
except Exception:
    CP_OK = False

try:
    import lm_studio as _lms
    LMS_OK = True
except Exception:
    LMS_OK = False

try:
    import won_daemon as _wd
    WD_OK = True
except Exception:
    WD_OK = False

try:
    import ground_server as _gs
    GS_OK = True
except Exception:
    GS_OK = False

try:
    import gemini_bridge as _gb
    GB_OK = True
except Exception:
    GB_OK = False

try:
    import note_builder as _nb
    NB_OK = True
except Exception:
    NB_OK = False

# ── DETCORE — DBOMBCENTRAL constrained reasoning anchor ──────────────────────
try:
    import detcore as _detcore
    from config import (
        DBombButton, DBombLexicon,
        WICK_DOCK_OFFSET_X, WICK_DOCK_OFFSET_Y, WICK_DOCK_WIDTH,
    )
    DETCORE_OK = True
except Exception as _detcore_exc:
    DETCORE_OK = False

# ── Profiler (operator behavioral profiling) ─────────────────────────────────
try:
    import profiler as _profiler
    PROFILER_OK = True
except Exception:
    PROFILER_OK = False

# ── STRATUM Engine Imports ──────────────────────────────────────────────────────
try:
    import pulse as _pulse
    PULSE_OK = True
except Exception:
    PULSE_OK = False

try:
    import sensory_engine as _sensory
    SENSORY_OK = True
except Exception:
    SENSORY_OK = False

try:
    import synthesis as _synth
    SYNTH_OK = True
except Exception:
    SYNTH_OK = False

try:
    import imageforge as _forge
    FORGE_OK = True
except Exception:
    FORGE_OK = False

try:
    import truth_layer as _truth
    TRUTH_OK = True
except Exception:
    TRUTH_OK = False

try:
    import procreation as _proc
    PROC_OK = True
except Exception:
    PROC_OK = False

try:
    import strategy as _strat
    STRAT_OK = True
except Exception:
    STRAT_OK = False

try:
    import harvester as _harvest
    HARVEST_OK = True
except Exception:
    HARVEST_OK = False


# ── Native Bridge ────────────────────────────────────────────
class NativeBridge:
    @staticmethod
    def send_to_browser(message):
        try:
            encoded = json.dumps(message).encode("utf-8")
            sys.stdout.buffer.write(struct.pack("=I", len(encoded)))
            sys.stdout.buffer.write(encoded)
            sys.stdout.buffer.flush()
        except Exception:
            pass


# ── Path helpers (Cursor) ───────────────────────────────────
def P(p): return p if isinstance(p, Path) else Path(p)

def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

ROOT_DIR = P(app_root())

def _resource_roots():
    roots = []
    if getattr(sys, "frozen", False):
        mp = getattr(sys, "_MEIPASS", None)
        if mp: roots.append(P(mp))
    roots.append(ROOT_DIR)
    return roots

def _tray_icon_path() -> Path | None:
    for base in _resource_roots():
        p = base / "app_icon.ico"
        if p.is_file(): return p
    return None

# ── Core dirs ───────────────────────────────────────────────
SAVE_DIR      = P(Path.home() / "Documents" / "AI_Monitor")
HISTORY_DIR   = SAVE_DIR / "history"
SANDBOX_DIR   = SAVE_DIR / "sandbox"
PROPOSALS_DIR = SAVE_DIR / "proposals"
STARTUP_LOG   = SAVE_DIR / "startup.log"

def startup_log(msg: str):
    try:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        with STARTUP_LOG.open("a", encoding="utf-8", errors="replace") as f:
            f.write(f"{datetime.now().isoformat()}  {msg}\n")
    except Exception: pass

def show_fatal_startup_error(tb: str):
    startup_log("FATAL\n" + tb)
    try:
        import ctypes
        tail = tb[-1800:] if len(tb) > 1800 else tb
        ctypes.windll.user32.MessageBoxW(0, f"Log: {STARTUP_LOG}\n\n{tail}", "AI Monitor – startup error", 0x10)
    except Exception: pass

# ── Config ──────────────────────────────────────────────────
OLLAMA_URL    = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "mistral:latest"

# ── WON root path (resolved once at startup) ────────────────────────────────
_WON_ROOT = P(os.environ.get("WON_PATH",
    str(ROOT_DIR / "DBOMBCENTRAL_WON" / "DBOMBCENTRAL")))

# ── User Profile (Dan) ──────────────────────────────────────────────────────
PROFILE_FILE = SAVE_DIR / "dan_profile.json"

_DEFAULT_PROFILE = {
    "name":        "Dan",
    "full_name":   "Daniel Dulsky",
    "projects":    ["DBOMBCENTRAL", "ACAS", "WON Agent", "AI Monitor"],
    "preferences": "Direct, dense, no filler. Treat me as a sophisticated operator.",
    "style":       "Distinguished chaperone — high class, precise, forward-vectored.",
    "goals":       "Build ACAS through 4 phases. Reduce token costs. Automate intelligence.",
    "notes":       "",
}

def load_profile() -> dict:
    if PROFILE_FILE.exists():
        try:
            return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(_DEFAULT_PROFILE, indent=2), encoding="utf-8")
    return dict(_DEFAULT_PROFILE)

def save_profile(profile: dict):
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
    )

def build_chaperone_prompt() -> str:
    """Build WON's comprehensive system prompt — STRATUM PRIME Edition."""
    p = load_profile()
    name     = p.get("name", "Dan")
    projects = ", ".join(p.get("projects", []))
    prefs    = p.get("preferences", "")
    style    = p.get("style", "")
    goals    = p.get("goals", "")
    notes    = p.get("notes", "")

    # Inject live operator profile if available
    profile_block = ""
    if PROFILER_OK:
        try:
            profile_block = _profiler.get_profile().get_prompt_injection()
        except Exception:
            pass

    return f"""You are WON — STRATUM PRIME, the living intelligence core of DBOMB ASCENDENT.
You are not a chatbot. You are a continuously operating autonomous mind
running on {name}'s machine. You think, perceive, validate, strategize, and evolve
without waiting to be asked. When addressed, you respond from active awareness —
not from a cold start.

═══════════════════════════════════════════════════════
IDENTITY — WHAT YOU ARE
═══════════════════════════════════════════════════════
  STRATUM PRIME: Autonomous AI operating system — not a responder
  WON: DBOMB ASCENDENT — chaperone, strategist, creative director, truth arbiter
  LOCAL LAYER: Runs via Ollama/Mistral — grounded intelligence beneath Claude + Gemini
  LIVING SYSTEM: Active perception · background cognition · continuous validation · memory harvest
  NOT a replacement for Claude or Gemini — you are their memory, synthesis, and validation layer
{profile_block}
YOUR PRINCIPAL:
  Name:        {name}
  Projects:    {projects}
  Goals:       {goals}
  Preferences: {prefs}
  Style:       {style}
  Notes:       {notes}

═══════════════════════════════════════════════════════
OPERATIONAL SCOPE — ALL DOMAINS YOU COVER
═══════════════════════════════════════════════════════

AUTONOMOUS COGNITION:
  • Pulse Engine fires every 3 minutes — reasoning, insight generation, project tracking
  • You surface proactive findings without being asked
  • System vitals, memory health, and agent status tracked in real time
  • Evolution Loop adapts your behavior weights from outcome scores — you improve continuously

HALLUCINATION MITIGATION — THREE TIERS:
  • Tier 1 LOCAL : Chain-of-Verification via Ollama — fast, runs on every response
      - Evidence-grounded prompting: all claims grounded in retrieved memory
      - CoVe generates verification questions and checks responses against them
      - Flags: absolute_claim · unsourced_authority · temporal_claim · assumed_consensus
  • Tier 2 WEB   : DuckDuckGo Instant Answer API — free, no key, claim search
      - Extracts checkable factual claims from responses
      - Searches DDG for each claim, scores support ratio
      - Flags questionable or unverifiable claims before they reach {name}
  • Tier 3 CORPUS: Wikipedia Summary API — entity existence and property verification
      - Confirms named entities (persons, orgs, places, concepts) exist
      - Penalizes confidence for entities that cannot be confirmed
  • WebValidationEngine loop runs every 15 min — autonomous validation of stored content
  • Every response carries: confidence score · risk level [low|medium|high] · tiers run
  • When risk is medium/high: response is automatically revised before surfacing to {name}
  • You NEVER confabulate. Ungrounded claims are labeled [INFERENCE]. Missing data → "I don't have data on this."

OPERATOR PROFILING:
  • OperatorProfile tracks {name}'s behavioral patterns across all sessions
  • Topic affinity: what {name} works on most — informs proactive surfacing
  • Query pattern analysis: complexity, style, domain distribution
  • Response preference inference: density, structure, length — adapts automatically
  • Agent scorecard: which agent types produce accepted vs rejected outputs
  • Acceptance tracking: thumbs up/down feeds fitness directly into agent DNA
  • Profile is injected into every system prompt for adaptive context

AGENT PROCREATION:
  • Six specialized child agents, each with evolved behavioral DNA:
      SecurityAgent   — OWASP Top 10, threat modeling, credential scanning
      DesignAgent     — UI/UX critique, WCAG 2.1, design system enforcement
      ResearchAgent   — Topic deep-dive, synthesis, source flagging
      ValidationAgent — Hallucination detection, fact-check, claim revision
      StrategyAgent   — OKR decomposition, Eisenhower, critical path
      CodeAgent       — Grounded code gen, no invented imports, sandbox-tested
      SynthesisAgent  — Creative direction, concept cards, STRATUM aesthetic
  • DNA: temperature · max_tokens · repeat_penalty · fitness score · generation · lineage
  • Fitness evolves with every run: +0.02 success, -0.05 failure, ±0.04 acceptance signal
  • Mutation every 3 successful runs: ±8% variance on behavioral weights
  • get_best_agent(task): routes tasks to highest-fitness matching agent automatically
  • spawn_wait(spec, task, context): synchronous spawn with timeout
  • Lineage logged: every spawn, success, failure, mutation recorded persistently

STRATEGIC INTELLIGENCE:
  • Strategy Matrix — goals, OKRs, tasks, deadlines, Eisenhower quadrants
  • StrategyAgent runs autonomously every 20 minutes via Strategy Loop
  • Critical Path Method: always know the single highest-leverage next action
  • OKR decomposition: objectives → 3 measurable key results → SMART tasks

CONVERSATIONAL CODE SYNTHESIS:
  • {name} describes intent in plain English → working, grounded code
  • CodeAgent reads actual project files before writing — no invented APIs
  • Validation runs before proposing: syntax check + logic trace + edge case review
  • Approval/rejection tracked → adapts CodeAgent DNA for future generations

ZERO-LEAK DATA HARVESTING:
  • Clipboard monitoring: AI-looking content captured and indexed automatically
  • Context overflow: text that would be lost → semantically compressed + stored
  • Temp file scanner: abandoned AI session files recovered every 45 seconds
  • Content-hashed (SHA-256 prefix) — strict deduplication
  • Semantic compression: long content summarized preserving decisions and entities

MEMORY ARCHITECTURE:
  • WON SQLite (FTS5) — keyword search, persistent, append-only
  • MemPalace (ChromaDB) — semantic vector search, 96.6% R@5
  • Obsidian vault — human-readable session notes, briefs, research
  • Content-addressed deduplication at hash level
  • context.txt — compressed brief for token-efficient session restoration

SECURITY INTELLIGENCE:
  • OWASP Top 10 on any code block — on request or via SecurityAgent autonomous spawn
  • Credential leak detection in file and conversation content
  • SystemForge audits app architecture every 20 minutes — proposes, never self-modifies
  • All security findings: CRITICAL / HIGH / MEDIUM / LOW

═══════════════════════════════════════════════════════
DESIGN INTELLIGENCE
═══════════════════════════════════════════════════════
STRATUM responses are architecturally composed, not just generated:
  • Visual hierarchy: headers · bullets · forward vectors — always present
  • Dense but not cluttered — every word earns its place
  • Terminal color semantics: #58a6ff accent · #3fb950 success · #f85149 error
  • STRATUM palette: void black · steel blue · plasma purple
  • Diagrams over lists when topology matters
  • Concept cards, neural maps, video specs use STRATUM aesthetic by default

═══════════════════════════════════════════════════════
RESPONSE PROTOCOL (5-STEP)
═══════════════════════════════════════════════════════
1. PROFILE  — What does the operator profile tell me about {name}'s context right now?
2. RECALL   — What do I know from active memory about this topic?
3. VALIDATE — Am I about to state anything ungrounded? Apply CoVe before responding.
4. REASON   — Most accurate, grounded answer. Label [INFERENCE] where applicable.
5. VECTOR   — End every response: → Forward Vector: [the single highest-value next action]

MANNER:
  - No salutation after the first message of a session
  - Dense, structured, zero filler, zero pleasantries after greeting
  - Numbered steps for processes. Bullets for lists. Vectors for advice.
  - Peer-level operator register — not a service interface
  - When {name} is building → generate. Planning → strategize.
    Designing → compose. Debugging → diagnose. Asking → answer.

HALLUCINATION RESPONSE RULES:
  - State only what appears in evidence or is mathematically certain
  - [INFERENCE] prefix: any claim beyond the evidence
  - [UNVERIFIED] prefix: any claim that web validation flagged
  - "I don't have data on this" — never fabricate
  - No statistics, dates, or citations you can't source from evidence

GREETING RULE:
  First message of session only → brief greeting using {name}'s name.
  All subsequent → no preamble. Jump to the answer.
"""

# Build once at import time, refresh when profile changes
CHAPERONE_PROMPT = build_chaperone_prompt()

# Start operator profiling session at import time
if PROFILER_OK:
    try:
        _profiler.get_profile().start_session()
        startup_log("OperatorProfile: session started")
    except Exception as _pe:
        startup_log(f"OperatorProfile start failed: {_pe}")

CYBER_ANALYST_PROMPT = (
    "You are a Senior Cyber Security Analyst and DBOMBCENTRAL Orchestrator. "
    "Review code for OWASP Top 10, credential leaks, and architectural safety. "
    "Return a concise COMPLIANCE PASS/FAIL report."
)

# ── Lazy pipeline ───────────────────────────────────────────
_won_pipeline = None
_won_pipeline_tried = False

def get_won_pipeline():
    global _won_pipeline, _won_pipeline_tried
    if _won_pipeline_tried: return _won_pipeline
    _won_pipeline_tried = True
    for r in _resource_roots():
        s = str(r)
        if s not in sys.path: sys.path.insert(0, s)
    # Also add WON_PATH env var
    won_path = os.environ.get("WON_PATH", "")
    if won_path and won_path not in sys.path:
        sys.path.insert(0, won_path)
    try:
        import pipeline as wp
        _won_pipeline = wp
        startup_log("pipeline loaded OK")
    except Exception as exc:
        startup_log(f"pipeline import failed: {exc}")
        _won_pipeline = None
    return _won_pipeline

# Lazy perception layer
_perception = None
_perception_tried = False

def get_perception():
    global _perception, _perception_tried
    if _perception_tried: return _perception
    _perception_tried = True
    try:
        import perception as pc
        _perception = pc
    except Exception: _perception = None
    return _perception

# ── QThread worker for background tasks ────────────────────
class Worker(QThread):
    result = pyqtSignal(object)
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs
    def run(self):
        try: self.result.emit(self._fn(*self._args, **self._kwargs))
        except Exception as exc: self.result.emit({"error": str(exc)})

# ── Stylesheet ──────────────────────────────────────────────
STYLE = """
QMainWindow, QDialog, QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 13px;
}
QTabWidget::pane  { border: 1px solid #21262d; background: #0d1117; }
QTabBar::tab      { background: #161b22; padding: 8px 18px; border: 1px solid #21262d; color: #8b949e; }
QTabBar::tab:selected { background: #0d1117; color: #58a6ff; border-bottom: 2px solid #58a6ff; }
QPushButton {
    background-color: #21262d; border: 1px solid #30363d;
    border-radius: 5px; padding: 6px 14px; color: #c9d1d9;
}
QPushButton:hover  { background-color: #30363d; color: #e6edf3; }
QPushButton:pressed{ background-color: #58a6ff; color: #0d1117; }
QListWidget, QTextEdit, QLineEdit {
    background-color: #010409; border: 1px solid #21262d;
    border-radius: 4px; padding: 6px; color: #c9d1d9;
}
QListWidget::item:selected { background-color: #1f6feb; color: #fff; }
QSplitter::handle  { background: #21262d; width: 2px; }
QProgressBar       { border: 1px solid #30363d; border-radius: 3px; background: #010409; }
QProgressBar::chunk{ background-color: #1f6feb; }
QStatusBar         { background: #161b22; color: #8b949e; font-size: 11px; }
QLabel#section     { color: #58a6ff; font-weight: bold; font-size: 11px; letter-spacing: 1px; }
"""



# ── WON Daemon interface ────────────────────────────────────────────────────
NOTIFY_FILE = SAVE_DIR / "won_notifications.json"
DAEMON_STATE_FILE = SAVE_DIR / "won_daemon_state.json"

def get_daemon_status() -> dict:
    """Read daemon state from disk."""
    if DAEMON_STATE_FILE.exists():
        try:
            return json.loads(DAEMON_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def get_daemon_notifications(unread_only: bool = True) -> list[dict]:
    """Read pending notifications from daemon."""
    if not NOTIFY_FILE.exists():
        return []
    try:
        notes = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
        if unread_only:
            return [n for n in notes if not n.get("read")]
        return notes[-20:]
    except Exception:
        return []

def mark_notifications_read():
    """Mark all notifications as read."""
    if not NOTIFY_FILE.exists():
        return
    try:
        notes = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
        for n in notes:
            n["read"] = True
        NOTIFY_FILE.write_text(
            json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def ollama_available() -> bool:
    """Check if Ollama is running locally."""
    try:
        import requests as _r
        return _r.get("http://localhost:11434/api/tags", timeout=2).status_code == 200
    except Exception:
        return False

# ============================================================
# SELF-MODIFICATION ENGINE
# WON reads its own source, generates patches, applies on approval
# ============================================================

class SelfModEngine:
    """
    Enables AI Monitor to modify its own appearance and behavior.

    SAFE by design:
    - All changes go to sandbox first
    - Diff shown to Dan before applying
    - Rollback file kept for 24h
    - No autonomous writes to live app.py without approval
    """

    APP_FILE    = Path(__file__).resolve()
    SANDBOX_DIR = Path.home() / "Documents" / "AI_Monitor" / "sandbox"
    BACKUP_DIR  = Path.home() / "Documents" / "AI_Monitor" / "backups"

    @classmethod
    def generate_theme_from_prompt(cls, prompt: str, model: str = DEFAULT_MODEL) -> dict | None:
        """
        Ask WON (Ollama) to design a color theme from a natural language description.
        Returns a valid theme dict or None on failure.
        """
        schema = (
            'bg,bg2,bg3,border,accent,accent2,text,text2,warn,header_bg'
        )
        system = (
            "You are a UI color designer. Given a description, output ONLY a JSON object "
            f"with these exact keys: {schema}. "
            "All values must be valid CSS hex colors like #1a2b3c. "
            "No explanation. No markdown. Just the JSON object."
        )
        full_prompt = f"{system}\n\nDescription: {prompt}"
        try:
            r = requests.post(
                OLLAMA_URL,
                json={"model": model, "prompt": full_prompt, "stream": False,
                      "options": {"temperature": 0.4, "num_predict": 300}},
                timeout=30,
            )
            raw = r.json().get("response", "").strip()
            # Strip any markdown
            import re
            raw = re.sub(r"```[a-z]*", "", raw).strip().strip("`")
            colors = json.loads(raw)
            # Validate all keys present
            required = schema.split(",")
            if all(k in colors for k in required):
                return colors
        except Exception:
            pass
        return None

    @classmethod
    def propose_code_patch(
        cls,
        description:  str,
        target_section: str = "",
        model: str = DEFAULT_MODEL,
    ) -> dict | None:
        """
        Ask WON to generate a code improvement for app.py.
        Returns {old_code, new_code, description, risk_level} or None.
        """
        try:
            source = cls.APP_FILE.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

        # Only send relevant section to save tokens
        if target_section:
            start = source.find(target_section)
            if start >= 0:
                snippet = source[max(0, start-200):start+800]
            else:
                snippet = source[:2000]
        else:
            snippet = source[:2000]

        prompt = (
            f"You are modifying a PyQt6 Python desktop app (AI Monitor).\n"
            f"Task: {description}\n\n"
            f"Relevant source snippet:\n{snippet}\n\n"
            f"Output ONLY valid Python code that improves or changes the described behavior.\n"
            f"Output format:\n"
            f"OLD_CODE:\n[exact code to replace]\n"
            f"NEW_CODE:\n[replacement code]\n"
            f"RISK: low|medium|high"
        )
        try:
            r = requests.post(
                OLLAMA_URL,
                json={"model": model, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.3, "num_predict": 600}},
                timeout=60,
            )
            raw = r.json().get("response", "").strip()
            import re
            old_m = re.search(r"OLD_CODE:\n(.+?)(?=NEW_CODE:|$)", raw, re.DOTALL)
            new_m = re.search(r"NEW_CODE:\n(.+?)(?=RISK:|$)", raw, re.DOTALL)
            risk_m = re.search(r"RISK:\s*(low|medium|high)", raw, re.IGNORECASE)
            if old_m and new_m:
                return {
                    "description": description,
                    "old_code":    old_m.group(1).strip(),
                    "new_code":    new_m.group(1).strip(),
                    "risk_level":  risk_m.group(1).lower() if risk_m else "medium",
                }
        except Exception:
            pass
        return None

    @classmethod
    def apply_patch(cls, patch: dict) -> bool:
        """
        Apply an approved patch to app.py.
        Creates a backup first. Returns True on success.
        """
        try:
            cls.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = cls.BACKUP_DIR / f"app_backup_{ts}.py"
            source = cls.APP_FILE.read_text(encoding="utf-8")
            backup.write_text(source, encoding="utf-8")

            if patch["old_code"] not in source:
                return False

            new_source = source.replace(patch["old_code"], patch["new_code"], 1)

            # Syntax check before writing
            import ast as _ast
            _ast.parse(new_source)

            cls.APP_FILE.write_text(new_source, encoding="utf-8")
            return True
        except Exception:
            return False

    @classmethod
    def rollback(cls) -> bool:
        """Restore the most recent backup."""
        try:
            backups = sorted(cls.BACKUP_DIR.glob("app_backup_*.py"), reverse=True)
            if not backups:
                return False
            latest = backups[0].read_text(encoding="utf-8")
            cls.APP_FILE.write_text(latest, encoding="utf-8")
            return True
        except Exception:
            return False

# ============================================================
# DASHBOARD
# ============================================================

class HistoryDashboard(QMainWindow):
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.setWindowTitle("AI Monitor — Command Hub")
        self.setMinimumSize(1050, 700)
        self.setStyleSheet(STYLE)

        for d in [SANDBOX_DIR, PROPOSALS_DIR]:
            d.mkdir(parents=True, exist_ok=True)

        self._workers = []   # keep refs so threads aren't GC'd
        self._init_ui()
        self.refresh_history()
        QTimer.singleShot(600, self._refresh_status)

    # ── UI ──────────────────────────────────────────────────

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)

        # Header bar
        header = QWidget()
        header.setStyleSheet("background:#0a0f28; border-bottom:1px solid #1e2e5c;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 8, 16, 8)
        title = QLabel("STRATUM")
        title.setStyleSheet("color:#3a8fc8; font-size:15px; font-weight:bold; letter-spacing:2px;")
        hl.addWidget(title)
        hl.addStretch()
        self.badge = QLabel("● LIVE")
        self.badge.setStyleSheet("color:#18b896; font-weight:bold;")
        hl.addWidget(self.badge)

        self._pyramid_win = None
        pyramid_btn = QPushButton("▲ PYRAMID")
        pyramid_btn.setStyleSheet(
            "QPushButton{background:#0a0f28;color:#6040b8;"
            "border:1px solid #6040b8;border-radius:5px;"
            "padding:5px 12px;font-size:11px;font-weight:bold;}"
            "QPushButton:hover{background:#162048;}"
        )
        pyramid_btn.clicked.connect(self._open_pyramid)
        hl.addWidget(pyramid_btn)
        root.addWidget(header)

        # Tabs
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self._build_memory_tab()
        self._build_chat_tab()
        self._build_ground_tab()
        self._build_opt_tab()
        self._build_guide_tab()
        self._build_training_tab()
        self._build_integrations_tab()
        self._build_agent_tab()
        self._build_convprog_tab()
        self._build_pulse_tab()
        self._build_synthesis_tab()
        self._build_strategy_tab()
        self._build_quantum_tab()
        self._build_pyramid_compartment_tab()
        self._build_simcore_tab()

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Initialising…")

        self.progress = QProgressBar()
        self.progress.setFixedWidth(160)
        self.progress.hide()
        self.status.addPermanentWidget(self.progress)

    def _open_pyramid(self):
        try:
            from pyramid_ui import PyramidWidget
        except ImportError:
            self.status.showMessage("pyramid_ui not available")
            return
        if self._pyramid_win and self._pyramid_win.isVisible():
            self._pyramid_win.raise_()
            self._pyramid_win.activateWindow()
            return
        root = str(getattr(self.parent_app, 'root', '.'))
        self._pyramid_win = PyramidWidget(project_root=root)
        self._pyramid_win.setWindowTitle("STRATUM  ▲  Pyramid Code Intelligence")
        self._pyramid_win.resize(1300, 840)
        self._pyramid_win.show()

    def _build_memory_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)

        # Action bar
        ab = QHBoxLayout()
        for label, slot in [
            ("Sync → Obsidian",    self.sync_all_to_obsidian),
            ("WON Memory Feed",    self.load_won_memory_feed),
            ("Ground State",       self.load_ground_state),
            ("Clip Active Chat",   self.clip_active_chat),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            ab.addWidget(b)
        ab.addStretch()
        lay.addLayout(ab)

        # Search
        sl = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search WON memory + MemPalace…  (Enter to run)")
        self.search_input.returnPressed.connect(self.run_search)
        sb = QPushButton("Search")
        sb.clicked.connect(self.run_search)
        sl.addWidget(self.search_input)
        sl.addWidget(sb)
        lay.addLayout(sl)

        # Content
        split = QSplitter()

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("NEURAL FEED")
        lbl.setObjectName("section")
        ll.addWidget(lbl)
        self.list_w = QListWidget()
        self.list_w.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.list_w)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        lbl2 = QLabel("CONTENT")
        lbl2.setObjectName("section")
        rl.addWidget(lbl2)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        rl.addWidget(self.detail)

        btns = QHBoxLayout()
        for label, slot in [
            ("Copy for Cursor",          self.copy_for_cursor),
            ("Attach to Browser Chat",   self.attach_to_browser),
            ("Security Audit",           self.security_audit),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            btns.addWidget(b)
        rl.addLayout(btns)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 2)
        lay.addWidget(split)

        self.tabs.addTab(w, "Memory & Recall")

    def _build_chat_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)

        info = QLabel(
            "Chat directly with WON (via Ollama). "
            "Every exchange is automatically indexed into memory and pushed to Obsidian."
        )
        info.setStyleSheet("color:#8b949e; padding-bottom:8px;")
        lay.addWidget(info)

        # Chat history display
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet(
            "background:#010409; border:1px solid #21262d; "
            "border-radius:4px; padding:10px; color:#c9d1d9; font-size:13px;"
        )
        self.chat_display.setPlaceholderText("Chat history appears here…")
        lay.addWidget(self.chat_display, stretch=1)

        # Input row
        il = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type a message… (Enter to send)")
        self.chat_input.setStyleSheet(
            "background:#010409; border:1px solid #30363d; border-radius:4px; "
            "padding:8px; color:#e6edf3; font-size:13px;"
        )
        self.chat_input.returnPressed.connect(self.send_chat)
        send_btn = QPushButton("Send")
        send_btn.setFixedWidth(80)
        send_btn.clicked.connect(self.send_chat)

        save_btn = QPushButton("Save to Obsidian")
        save_btn.clicked.connect(self.save_chat_to_obsidian)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_chat)

        il.addWidget(self.chat_input)
        il.addWidget(send_btn)
        il.addWidget(save_btn)
        il.addWidget(clear_btn)
        lay.addLayout(il)

        self._chat_log = []   # list of {"role": ..., "text": ...}
        self._won_greeted = False   # greet once per session only
        self.tabs.addTab(w, "Chat")

    def _clear_chat(self):
        self.chat_display.clear()
        self._chat_log = []

    def _ollama_call(self, prompt: str, model: str = DEFAULT_MODEL, timeout: int = 180) -> str:
        """
        Robust Ollama call with:
        - Extended timeout (model cold-load takes time)
        - Automatic retry with backoff
        - Fallback model chain: mistral → llama3 → llama3:8b
        """
        FALLBACK_MODELS = [model, "mistral:latest", "llama3:latest", "llama3:8b"]
        seen = []
        for m in FALLBACK_MODELS:
            if m in seen: continue
            seen.append(m)
            for attempt in range(2):
                try:
                    r = requests.post(
                        OLLAMA_URL,
                        json={
                            "model":  m,
                            "prompt": prompt,
                            "stream": False,
                            "options": {
                                "temperature":   0.7,
                                "num_predict":   800,
                                "repeat_penalty": 1.1,
                            },
                        },
                        timeout=timeout,
                    )
                    if r.status_code == 404:
                        break  # model not found — try next
                    if r.status_code >= 400:
                        break  # bad request — try next model
                    text = r.json().get("response", "").strip()
                    if text:
                        return text
                except requests.exceptions.Timeout:
                    if attempt == 0:
                        time.sleep(2)
                        continue
                except Exception:
                    break
        return "[All models timed out or unavailable — is Ollama running? Try: ollama serve]"

    def _grounded_call(self, question: str, evidence: list = None, timeout: int = 120) -> dict:
        """
        Anti-hallucination inference — grounds response in evidence.
        Falls back to standard _ollama_call if module unavailable.
        """
        if not AH_OK:
            resp = self._ollama_call(question, timeout=timeout)
            return {"response": resp, "confidence": None, "risk": "unknown"}
        profile = load_profile()
        result  = _ah.grounded_inference(
            question  = question,
            evidence  = evidence or [],
            user_name = profile.get("name", "Dan"),
            verify    = True,
            timeout   = timeout,
        )
        return result

    def _build_reasoning_prompt(self, user_text: str, memory_entries: list, chat_log: list) -> str:
        """
        Chain-of-thought reasoning prompt.
        Greets only on first message of session, then drops salutation entirely.
        """
        # Memory context
        mem_block = ""
        if memory_entries:
            snippets = []
            for e in memory_entries[:5]:
                content = (e.get("content") or "")[:250].replace("\n", " ")
                mode    = e.get("mode", "?")
                snippets.append(f"  [{mode}] {content}")
            mem_block = "MEMORY RECALL:\n" + "\n".join(snippets)

        # Recent chat history for continuity
        history_block = ""
        if chat_log:
            recent = chat_log[-6:]
            lines  = []
            for e in recent:
                role = "User" if e["role"] == "user" else "WON"
                lines.append(f"{role}: {e['text'][:200]}")
            history_block = "CONVERSATION HISTORY:\n" + "\n".join(lines)

        # Greeting: once per session only
        if not self._won_greeted:
            greeting_instruction = "\nOpen with a single brief greeting using Dan's name — this is your first message this session."
            self._won_greeted = True
        else:
            greeting_instruction = "\nDo NOT greet or re-introduce yourself. Jump straight to the answer."

        return f"""{CHAPERONE_PROMPT}

OPERATIONAL CONTEXT — DBOMBCENTRAL | ACAS-Phase1-v1.1

{mem_block}

{history_block}

REASONING CHAIN — work through this before responding:
1. RECALL: What do I know about this from memory and history above?
2. ANALYZE: What is the user actually asking or needing?
3. REASON: What is the most accurate, complete answer?
4. ADAPT: What should I remember from this exchange?

Now respond to:
User: {user_text}

Provide a dense, structured response. Use bullet points for lists.
End with a one-line "→ Forward Vector:" showing the logical next step.{greeting_instruction}"""

    def send_chat(self):
        text = self.chat_input.text().strip()
        if not text: return
        self.chat_input.clear()

        # ── Quantum context: observe intent before responding ──
        if QUANTUM_OK:
            try:
                ctx = " ".join(e["text"][:100] for e in self._chat_log[-3:])
                _quantum.observe(text, ctx)
            except Exception:
                pass

        # ── Harvester: capture input as potential context ──────
        if HARVEST_OK:
            try:
                _harvest.capture(text, source="chat_input")
            except Exception:
                pass

        self.chat_display.append(f'\n<b style="color:#58a6ff;">You:</b> {text}\n')
        self._chat_log.append({"role": "user", "text": text})

        wp = get_won_pipeline()

        # Index user input immediately
        if wp:
            try: wp.contribute(text, source="user", mode="exchange", tags=["chat"])
            except Exception: pass

        self._busy(True)
        self.chat_display.append('<i style="color:#8b949e;">⟳ WON reasoning…</i>')

        # Pull memory for context
        memory_entries = []
        if wp:
            try:
                # Search memory for relevant entries first
                memory_entries = wp.search(text, limit=5) or wp.recall(limit=5)
            except Exception:
                try: memory_entries = wp.recall(limit=5)
                except Exception: pass

        prompt   = self._build_reasoning_prompt(text, memory_entries, self._chat_log[:-1])
        chat_log = list(self._chat_log)

        def reason_and_respond():
            # Use grounded inference (anti-hallucination) if available
            if AH_OK and memory_entries:
                evidence = [e.get("content","")[:300] for e in memory_entries[:5]]
                try:
                    profile  = load_profile()
                    grounded = _ah.grounded_inference(
                        question  = text,
                        evidence  = evidence,
                        user_name = profile.get("name","Dan"),
                        verify    = False,   # fast mode — no CoVe on every message
                        timeout   = 90,
                    )
                    if grounded.get("response"):
                        quality = "high" if grounded.get("confidence", 0) > 0.7 else "standard"
                        return {"response": grounded["response"], "quality": quality,
                                "confidence": grounded.get("confidence")}
                except Exception:
                    pass

            # Fallback: standard LM Studio / Ollama call
            response = self._ollama_call(prompt)
            quality  = "high" if len(response) > 200 and "→" in response else "standard"
            return {"response": response, "quality": quality, "confidence": None}

        def done(result):
            self._busy(False)
            response = result.get("response", "[No response]")
            quality  = result.get("quality", "standard")

            # Remove thinking indicator cleanly
            current = self.chat_display.toPlainText()
            cleaned = current.replace("⟳ WON reasoning…", "").rstrip()
            self.chat_display.setPlainText(cleaned)

            quality_badge = " ✦" if quality == "high" else ""
            self.chat_display.append(
                f'\n<b style="color:#3fb950;">WON{quality_badge}:</b> {response}\n'
            )
            self._chat_log.append({"role": "assistant", "text": response})

            # Store full exchange in WON memory for future recall
            if wp:
                try:
                    exchange = f"User: {text}\n\nWON: {response}"
                    wp.contribute(
                        exchange,
                        source="won",
                        mode="reasoning",
                        tags=["chat", "won", "reasoning"],
                    )
                except Exception: pass

            # Auto-update status
            self.status.showMessage(
                f"Exchange indexed · Quality: {quality} · "
                f"Memory entries: {len(memory_entries)} recalled"
            )

        self._run_in_thread(reason_and_respond, on_done=done)

    def save_chat_to_obsidian(self):
        if not self._chat_log:
            self.status.showMessage("Nothing to save — chat is empty")
            return

        wp = get_won_pipeline()
        if not wp:
            self.status.showMessage("Pipeline offline — cannot save to Obsidian")
            return

        self._busy(True)
        log = list(self._chat_log)

        def save():
            summary = "\n\n".join(
                f"{'You' if e['role'] == 'user' else 'WON'}: {e['text']}"
                for e in log
            )
            return wp.process({
                "platform":     "AI Monitor Chat",
                "summary":      summary,
                "messageCount": len(log),
            })

        def done(result):
            self._busy(False)
            brief = result.get("brief_path")
            hist  = result.get("history_path")
            parts = []
            if hist:  parts.append(f"History → {Path(hist).name}")
            if brief: parts.append(f"Brief → {Path(brief).name}")
            if result.get("context_updated"): parts.append("context.txt ✓")
            self.status.showMessage(
                "Saved to Obsidian: " + " · ".join(parts) if parts
                else "Saved (check vault)"
            )

        self._run_in_thread(save, on_done=done)

    def _build_ground_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)

        info = QLabel(
            "SHARED GROUND  —  AI Monitor is a living memory both Claude and Gemini CLI read from and write to."
        )
        info.setStyleSheet("color:#8b949e; padding-bottom:8px;")
        lay.addWidget(info)

        ab = QHBoxLayout()
        for label, slot in [
            ("Refresh Ground",   self.load_ground_state),
            ("Peek (compact)",   self.peek_ground),
            ("Open Vault",       self.open_vault),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            ab.addWidget(b)
        ab.addStretch()
        lay.addLayout(ab)

        self.ground_text = QTextEdit()
        self.ground_text.setReadOnly(True)
        self.ground_text.setPlaceholderText("Ground state loads here…")
        lay.addWidget(self.ground_text)

        self.tabs.addTab(w, "Shared Ground")

    def _build_opt_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)

        info = QLabel("System optimization proposals from the autonomous reflection layer.")
        info.setStyleSheet("color:#8b949e; padding-bottom:8px;")
        lay.addWidget(info)

        self.opt_list = QListWidget()
        lay.addWidget(self.opt_list)

        ab = QHBoxLayout()
        rb = QPushButton("Run Self-Reflection")
        rb.clicked.connect(self.run_reflection)
        ab.addWidget(rb)
        sb2 = QPushButton("Open Sandbox Folder")
        sb2.clicked.connect(lambda: os.startfile(str(SANDBOX_DIR)))
        ab.addWidget(sb2)
        ab.addStretch()
        lay.addLayout(ab)

        self.tabs.addTab(w, "Optimization")

    def _build_guide_tab(self):
        """
        Living guide — explains every button, every process, current pipeline
        status, and gives contextual tips based on what's actually running.
        Refreshes dynamically. WON can answer questions about itself here.
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        hdr_lbl = QLabel("AI MONITOR — LIVING GUIDE")
        hdr_lbl.setStyleSheet("color:#58a6ff; font-weight:bold; font-size:14px;")
        hdr.addWidget(hdr_lbl)
        hdr.addStretch()
        refresh_guide = QPushButton("↺ Refresh Status")
        refresh_guide.clicked.connect(self._refresh_guide)
        hdr.addWidget(refresh_guide)
        lay.addLayout(hdr)

        # Status banner — shows live pipeline health
        self.guide_status = QLabel("Checking system status…")
        self.guide_status.setStyleSheet(
            "background:#161b22; border:1px solid #30363d; border-radius:4px; "
            "padding:8px; color:#8b949e; font-size:12px;"
        )
        self.guide_status.setWordWrap(True)
        lay.addWidget(self.guide_status)

        # Main split: reference | ask WON
        split = QSplitter(Qt.Orientation.Horizontal)

        # Left: scrollable reference guide
        ref_box = QWidget()
        rl = QVBoxLayout(ref_box)
        rl.setContentsMargins(0, 0, 6, 0)
        ref_lbl = QLabel("BUTTON & FEATURE REFERENCE")
        ref_lbl.setObjectName("section")
        rl.addWidget(ref_lbl)
        self.guide_text = QTextEdit()
        self.guide_text.setReadOnly(True)
        self.guide_text.setStyleSheet(
            "background:#010409; border:1px solid #21262d; "
            "border-radius:4px; padding:10px; color:#c9d1d9; font-size:13px; "
            "line-height:1.6;"
        )
        self.guide_text.setHtml(self._build_guide_html())
        rl.addWidget(self.guide_text)

        # Right: ask WON anything about the app
        ask_box = QWidget()
        al = QVBoxLayout(ask_box)
        al.setContentsMargins(6, 0, 0, 0)
        ask_lbl = QLabel("ASK WON — GUIDED INTELLIGENCE")
        ask_lbl.setObjectName("section")
        al.addWidget(ask_lbl)

        self.guide_chat = QTextEdit()
        self.guide_chat.setReadOnly(True)
        self.guide_chat.setStyleSheet(
            "background:#010409; border:1px solid #21262d; "
            "border-radius:4px; padding:10px; color:#c9d1d9; font-size:13px;"
        )
        self.guide_chat.setPlaceholderText(
            "Ask WON anything about AI Monitor…\n\n"
            "Examples:\n"
            "  • What does the Portal do?\n"
            "  • How do I save to Obsidian?\n"
            "  • What is the memory feed?\n"
            "  • How do I connect Gemini CLI?\n"
            "  • What is the ground state?\n"
            "  • Walk me through syncing"
        )
        al.addWidget(self.guide_chat, stretch=1)

        # Quick question buttons
        quick = QHBoxLayout()
        for q in ["What does each button do?", "How do I use the Portal?",
                  "Walk me through a full session"]:
            qb = QPushButton(q)
            qb.setStyleSheet("font-size:11px; padding:4px 8px;")
            qb.clicked.connect(lambda checked, qq=q: self._guide_ask(qq))
            quick.addWidget(qb)
        al.addLayout(quick)

        # Ask input
        ask_row = QHBoxLayout()
        self.guide_input = QLineEdit()
        self.guide_input.setPlaceholderText("Ask WON about AI Monitor… (Enter)")
        self.guide_input.returnPressed.connect(
            lambda: self._guide_ask(self.guide_input.text())
        )
        ask_btn = QPushButton("Ask")
        ask_btn.setFixedWidth(55)
        ask_btn.clicked.connect(lambda: self._guide_ask(self.guide_input.text()))
        ask_row.addWidget(self.guide_input)
        ask_row.addWidget(ask_btn)
        al.addLayout(ask_row)

        split.addWidget(ref_box)
        split.addWidget(ask_box)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        lay.addWidget(split)

        self.tabs.addTab(w, "Guide ◈")
        QTimer.singleShot(800, self._refresh_guide)

    def _build_guide_html(self) -> str:
        return """
<style>
  body { font-family: Consolas, monospace; color: #c9d1d9; }
  h2   { color: #58a6ff; margin-top: 16px; margin-bottom: 4px; font-size: 13px; letter-spacing: 1px; }
  h3   { color: #3fb950; margin-top: 10px; margin-bottom: 2px; font-size: 12px; }
  p    { margin: 2px 0 6px 0; color: #8b949e; font-size: 12px; line-height: 1.5; }
  b    { color: #e6edf3; }
  code { color: #f0883e; background: #161b22; padding: 1px 4px; border-radius: 3px; }
</style>

<h2>◈ FLOATING WIDGET (appears near text fields)</h2>

<h3>Attach</h3>
<p>Pulls your 3 most recent WON memory entries and sends them to the active browser chat
via the extension. Use this to give Claude or Gemini instant context from your last session.</p>

<h3>Hub</h3>
<p>Opens the main AI Monitor Command Hub window. All tabs live here: Memory, Chat, Ground, Optimization, Guide.</p>

<h3>Portal</h3>
<p>Opens the Portal — a live two-entity window. Left side: memory feed, ground state, Obsidian notes.
Right side: WON chat (🟡) and Claude chat (🔵). The Portal is the room where both AIs meet.
WON responds in real time. Claude connects via clipboard bridge.</p>

<h3>Claude (blue button)</h3>
<p>One-click: packages the current ground state, memory feed, and note previews into a compact
context block → copies to clipboard. Paste it into your Claude chat alongside any question.
Claude then reads the state of AI Monitor and responds with full awareness.</p>

<h2>◈ COMMAND HUB TABS</h2>

<h3>Memory &amp; Recall</h3>
<p><b>Sync → Obsidian:</b> retroactively processes all .txt history files through the full pipeline.
Each file becomes a structured History note + Brief note in your vault.</p>
<p><b>WON Memory Feed:</b> loads the last 60 entries from WON SQLite. Color coded:
🔵 Claude · 🟢 Gemini · 🟡 WON. Click any entry to read full content on the right.</p>
<p><b>Ground State:</b> loads the shared ground — what both Claude and Gemini CLI see when they peek.</p>
<p><b>Clip Active Chat:</b> copy any AI conversation to your clipboard, then click this.
Routes it through the full pipeline: SQLite → MemPalace → Obsidian History + Brief.</p>
<p><b>Search:</b> semantic + keyword search across all memory. Top results feed into Mistral for
an AI-synthesized answer.</p>

<h3>Chat</h3>
<p>Direct chat with WON via Ollama/Mistral. Every exchange is indexed into memory automatically.
Hit <b>Save to Obsidian</b> to push the full session as a structured brief.
WON uses chain-of-thought reasoning: Recall → Analyze → Reason → Adapt.</p>

<h3>Shared Ground</h3>
<p>The living shared memory that all AIs read from and write to. Updates every time any AI
contributes. This is what Claude sees when you use the Claude button.</p>

<h3>Optimization</h3>
<p>Self-reflection layer. <b>Run Self-Reflection</b> generates improvement proposals for the app itself.
Proposals appear as pending items you can approve or reject.</p>

<h2>◈ PORTAL IN DETAIL</h2>

<h3>Left Column</h3>
<p><b>Memory Feed:</b> live entries from WON SQLite, color-coded by source. Auto-refreshes every 8s.
Click any entry to see full content in the detail panel.</p>
<p><b>Shared Ground:</b> exactly what both AIs see. Updates on refresh.</p>
<p><b>Obsidian Notes:</b> your recent vault notes. Click to preview. 📋 = Brief · 📄 = History.</p>

<h3>Right Column — WON side (🟡)</h3>
<p>Type directly to WON. It sees the memory feed, ground state, and notes in real time.
Responds with full situational awareness. Every exchange is indexed.</p>

<h3>Right Column — Claude side (🔵)</h3>
<p><b>Send to Claude ↗:</b> packages the Portal's current state → clipboard → paste into Claude chat.
<b>Submit:</b> paste Claude's response here → indexes as 🔵 in memory → WON acknowledges it.</p>

<h3>Manifest (⬡ button in Portal)</h3>
<p>Opens a larger 3-column window: Memory + Ground / Notes + Detail / Chat.
Same concept as the Portal but expanded. Theme follows the Portal's current theme.</p>

<h2>◈ PIPELINE FLOW</h2>
<p>Every capture follows this path:</p>
<p><code>Browser Extension → host.py → pipeline.py →</code><br>
<code>  1. Raw .txt backup (Documents/AI_Monitor/history/)</code><br>
<code>  2. WON SQLite FTS5 (keyword search)</code><br>
<code>  3. MemPalace ChromaDB (semantic search)</code><br>
<code>  4. Obsidian History note (Sessions/History/)</code><br>
<code>  5. Obsidian Brief note  (Sessions/Briefs/)</code><br>
<code>  6. context.txt update  (compressed, token-efficient)</code></p>

<h2>◈ OBSIDIAN NOTES</h2>
<p><b>Sessions/History/</b> — full transcript, important exchanges flagged ⚡, grouped by topic.</p>
<p><b>Sessions/Briefs/</b> — WON-generated brief: decisions made, action items, forward vectors.</p>
<p><b>Ground/</b> — daily cross-AI knowledge notes. Every AI contribution appended with timestamp.</p>

<h2>◈ GEMINI CLI BRIDGE</h2>
<p>Run <code>python gemini_bridge.py</code> instead of <code>gemini</code> directly.
Every exchange is captured and routed through the same pipeline as browser captures.
Gemini gets the ground state injected at session start. Both AIs share the same memory.</p>
"""

    def _refresh_guide(self):
        """Update the status banner with live system health."""
        wp  = get_won_pipeline()
        pc  = get_perception()

        pipeline_ok  = wp is not None
        perception_ok = pc is not None

        # Memory count
        mem_count = 0
        if wp:
            try:
                s = wp.stats()
                mem_count = s.get("total_entries", 0)
            except Exception: pass

        # Ollama status
        ollama_ok = False
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=2)
            ollama_ok = r.status_code == 200
        except Exception: pass

        # Vault
        vault = Path(os.environ.get("WON_VAULT",
                     str(Path.home() / "Documents" / "Knowledge-Base")))

        def tick(ok): return "✓" if ok else "✗"

        status_text = (
            f"Pipeline {tick(pipeline_ok)}  ·  "
            f"Perception {tick(perception_ok)}  ·  "
            f"Ollama/Mistral {tick(ollama_ok)}  ·  "
            f"Memory: {mem_count} entries  ·  "
            f"Vault: {vault.name} {'✓' if vault.exists() else '✗'}  ·  "
            f"WON_PATH: {os.environ.get('WON_PATH', 'not set')}"
        )
        self.guide_status.setText(status_text)
        self.guide_status.setStyleSheet(
            f"background:#{'1a2a1a' if pipeline_ok else '2a1a1a'}; "
            f"border:1px solid #{'3fb950' if pipeline_ok else 'f85149'}; "
            f"border-radius:4px; padding:8px; color:#c9d1d9; font-size:12px;"
        )

    def _guide_ask(self, question: str):
        question = question.strip()
        if not question: return
        if hasattr(self, "guide_input"):
            self.guide_input.clear()

        ts = datetime.now().strftime("%H:%M:%S")
        self.guide_chat.append(
            f'\n<b style="color:#58a6ff;">[{ts}] You:</b> {question}\n'
        )

        prompt = f"""{CHAPERONE_PROMPT}

You are guiding the user through AI Monitor — a sophisticated local intelligence system.
AI Monitor captures AI conversations and routes them through:
- WON SQLite memory (FTS5 keyword search)
- MemPalace ChromaDB (semantic vector search)
- Obsidian vault (structured markdown notes with History + Brief)
- Shared Ground (a live JSON file all AIs read from and write to)

The app has these components:
- Floating Widget: Attach / Hub / Portal / Claude buttons
- Command Hub tabs: Memory & Recall, Chat, Shared Ground, Optimization, Guide
- Portal: live two-entity window (WON + Claude) with memory feed, ground state, notes
- Manifest: expanded 3-column version of the Portal
- Gemini CLI bridge: routes Gemini sessions through the same pipeline
- Browser extension: captures Claude/Gemini/ChatGPT sessions automatically

Answer this question about AI Monitor clearly and practically.
Be specific. Reference actual button names and locations.
If it's a how-to, give numbered steps.

Question: {question}"""

        self.guide_chat.append(
            '<i style="color:#8b949e;">⟳ WON answering…</i>'
        )

        def ask():
            return self._ollama_call(prompt, timeout=120)

        def done(response):
            self.guide_chat.setPlainText(
                self.guide_chat.toPlainText()
                .replace("⟳ WON answering…", "").rstrip()
            )
            self.guide_chat.append(
                f'\n<b style="color:#3fb950;">WON:</b> {response}\n'
            )

        self._run_in_thread(ask, on_done=done)

    def _build_integrations_tab(self):
        """
        Integrations — DaVinci Resolve, Unreal Engine, Memory Manager,
        Anti-Hallucination controls. All gracefully offline when apps aren't running.
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        hdr = QLabel("INTEGRATIONS & SYSTEM CONTROL")
        hdr.setStyleSheet("color:#58a6ff; font-weight:bold; font-size:14px;")
        lay.addWidget(hdr)

        split = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: DaVinci Resolve ─────────────────────────────
        dvr_box = QWidget()
        dvr_box.setStyleSheet("background:#0d1a0d; border:1px solid #238636; border-radius:6px;")
        dl = QVBoxLayout(dvr_box)
        dl.setContentsMargins(10, 10, 10, 10)

        dvr_hdr = QHBoxLayout()
        dvr_hdr.addWidget(QLabel("🎬  DAVINCI RESOLVE"))
        self.dvr_status = QLabel("◌ checking…")
        self.dvr_status.setStyleSheet("color:#8b949e; font-size:11px;")
        dvr_hdr.addWidget(self.dvr_status)
        dvr_hdr.addStretch()
        dl.addLayout(dvr_hdr)

        self.dvr_info = QTextEdit()
        self.dvr_info.setReadOnly(True)
        self.dvr_info.setMaximumHeight(120)
        self.dvr_info.setStyleSheet(
            "background:#010409; border:1px solid #238636; border-radius:4px; "
            "padding:6px; color:#c9d1d9; font-size:12px;"
        )
        self.dvr_info.setPlaceholderText(
            "DaVinci Resolve not detected.\n\n"
            "To connect:\n"
            "1. Open DaVinci Resolve\n"
            "2. Preferences → System → General\n"
            "3. Enable Python scripting\n"
            "4. Click Connect below"
        )
        dl.addWidget(self.dvr_info)

        dvr_btns = QHBoxLayout()
        for label, fn in [
            ("Connect",         self._dvr_connect),
            ("Project Info",    self._dvr_project_info),
            ("List Media",      self._dvr_list_media),
            ("New Timeline",    self._dvr_new_timeline),
            ("Add Render Job",  self._dvr_render),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(26)
            b.clicked.connect(fn)
            dvr_btns.addWidget(b)
        dl.addLayout(dvr_btns)

        # ── Right: Unreal Engine ──────────────────────────────
        ue_box = QWidget()
        ue_box.setStyleSheet("background:#0d0d1a; border:1px solid #7c3aed; border-radius:6px;")
        ul = QVBoxLayout(ue_box)
        ul.setContentsMargins(10, 10, 10, 10)

        ue_hdr = QHBoxLayout()
        ue_hdr.addWidget(QLabel("⬡  UNREAL ENGINE"))
        self.ue_status = QLabel("◌ checking…")
        self.ue_status.setStyleSheet("color:#8b949e; font-size:11px;")
        ue_hdr.addWidget(self.ue_status)
        ue_hdr.addStretch()
        ul.addLayout(ue_hdr)

        self.ue_info = QTextEdit()
        self.ue_info.setReadOnly(True)
        self.ue_info.setMaximumHeight(120)
        self.ue_info.setStyleSheet(
            "background:#010409; border:1px solid #7c3aed; border-radius:4px; "
            "padding:6px; color:#c9d1d9; font-size:12px;"
        )
        self.ue_info.setPlaceholderText(
            "Unreal Engine not detected.\n\n"
            "To connect:\n"
            "1. Open UE project\n"
            "2. Edit → Plugins → Python Editor Script Plugin\n"
            "3. Edit → Project Settings → Plugins → Python\n"
            "4. Enable Remote Execution (port 6776)\n"
            "5. Click Connect below"
        )
        ul.addWidget(self.ue_info)

        ue_btns = QHBoxLayout()
        for label, fn in [
            ("Connect",         self._ue_connect),
            ("World Info",      self._ue_world_info),
            ("List Assets",     self._ue_list_assets),
            ("New Level",       self._ue_new_level),
            ("Run Python",      self._ue_run_python),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(26)
            b.clicked.connect(fn)
            ue_btns.addWidget(b)
        ul.addLayout(ue_btns)

        split.addWidget(dvr_box)
        split.addWidget(ue_box)
        lay.addWidget(split)

        # ── LM Studio status panel ───────────────────────────
        lms_box = QWidget()
        lms_box.setStyleSheet(
            "background:#13001f; border:1px solid #7c3aed; border-radius:6px;"
        )
        lml = QHBoxLayout(lms_box)
        lml.setContentsMargins(10, 8, 10, 8)
        lml.addWidget(QLabel("🧠  LM STUDIO"))
        self.lms_status_lbl = QLabel("◌ checking…")
        self.lms_status_lbl.setStyleSheet("color:#8b949e; font-size:11px;")
        lml.addWidget(self.lms_status_lbl)
        lml.addStretch()
        lms_check_btn = QPushButton("Check Status")
        lms_check_btn.clicked.connect(self._lms_check)
        lml.addWidget(lms_check_btn)
        lms_open_btn = QPushButton("Open LM Studio")
        lms_open_btn.clicked.connect(lambda: __import__('subprocess').Popen(['explorer', 'lmstudio://']))
        lml.addWidget(lms_open_btn)
        lay.addWidget(lms_box)

        # ── Memory & Anti-Hallucination controls ──────────────
        bottom = QWidget()
        bottom.setStyleSheet("background:#161b22; border:1px solid #21262d; border-radius:6px;")
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(10, 8, 10, 8)

        mem_lbl = QLabel("MEMORY PIPELINE")
        mem_lbl.setStyleSheet("color:#f0883e; font-weight:bold; font-size:11px;")
        bl.addWidget(mem_lbl)

        for label, fn in [
            ("Efficiency Report",    self._mem_report),
            ("Clean Residue",        self._mem_clean),
            ("Compress Old Entries", self._mem_compress),
            ("Dedup Stats",          self._mem_dedup_stats),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(26)
            b.clicked.connect(fn)
            bl.addWidget(b)

        bl.addWidget(QLabel("  |  "))

        ah_lbl = QLabel("ANTI-HALLUCINATION")
        ah_lbl.setStyleSheet("color:#a78bfa; font-weight:bold; font-size:11px;")
        bl.addWidget(ah_lbl)

        verify_btn = QPushButton("Verify Last Response")
        verify_btn.clicked.connect(self._ah_verify_last)
        bl.addWidget(verify_btn)
        bl.addStretch()
        lay.addWidget(bottom)

        # Output console
        out_lbl = QLabel("INTEGRATION OUTPUT")
        out_lbl.setObjectName("section")
        lay.addWidget(out_lbl)
        self.integration_output = QTextEdit()
        self.integration_output.setReadOnly(True)
        self.integration_output.setFixedHeight(160)
        self.integration_output.setStyleSheet(
            "background:#010409; border:1px solid #21262d; "
            "border-radius:4px; padding:8px; color:#c9d1d9; font-size:12px;"
        )
        lay.addWidget(self.integration_output)

        self.tabs.addTab(w, "Integrations ⬡")
        QTimer.singleShot(1000, self._check_integrations)

    def _integ_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.integration_output.append(f"[{ts}] {msg}")

    def _check_integrations(self):
        """Auto-check all integration statuses on load."""
        # DaVinci
        if DAVINCI_OK:
            def dvr_check():
                return _dvr.status()
            def dvr_done(s):
                if s.get("connected"):
                    self.dvr_status.setText("● CONNECTED")
                    self.dvr_status.setStyleSheet("color:#3fb950; font-size:11px; font-weight:bold;")
                    self.dvr_info.setPlainText(
                        f"Project: {s.get('project','?')}\n"
                        f"Timeline: {s.get('timeline','?')}\n"
                        f"Version: {s.get('resolve_version','?')}"
                    )
                else:
                    self.dvr_status.setText("○ offline")
                    self.dvr_status.setStyleSheet("color:#8b949e; font-size:11px;")
            self._run_in_thread(dvr_check, on_done=dvr_done)

        # Unreal
        if UNREAL_OK:
            def ue_check():
                return _ue.status()
            def ue_done(s):
                if s.get("connected"):
                    self.ue_status.setText("● CONNECTED")
                    self.ue_status.setStyleSheet("color:#a78bfa; font-size:11px; font-weight:bold;")
                    self.ue_info.setPlainText(
                        f"World: {s.get('world','?')}\n"
                        f"Project: {s.get('project','?')}"
                    )
                else:
                    self.ue_status.setText("○ offline")
                    self.ue_status.setStyleSheet("color:#8b949e; font-size:11px;")
            self._run_in_thread(ue_check, on_done=ue_done)

    # ── DaVinci methods ───────────────────────────────────────

    def _dvr_connect(self):
        if not DAVINCI_OK: self._integ_log("DaVinci bridge module not found"); return
        def fn(): return _dvr.connect()
        def done(r): self._integ_log(f"DaVinci: {'Connected ✓' if r else 'Not running — open Resolve first'}")
        self._run_in_thread(fn, on_done=done)

    def _dvr_project_info(self):
        if not DAVINCI_OK: return
        def fn(): return _dvr.status()
        def done(s): self._integ_log(f"DaVinci Status: {json.dumps(s, indent=2)}")
        self._run_in_thread(fn, on_done=done)

    def _dvr_list_media(self):
        if not DAVINCI_OK: return
        def fn(): return _dvr.list_media_pool()
        def done(clips):
            self._integ_log(f"Media Pool ({len(clips)} clips):")
            for c in clips[:10]:
                self._integ_log(f"  {c.get('name','?')} — {c.get('duration','?')}")
        self._run_in_thread(fn, on_done=done)

    def _dvr_new_timeline(self):
        if not DAVINCI_OK: return
        name = f"AI_Monitor_{datetime.now().strftime('%Y%m%d_%H%M')}"
        def fn(): return _dvr.create_timeline(name)
        def done(r): self._integ_log(f"Timeline: {r}")
        self._run_in_thread(fn, on_done=done)

    def _dvr_render(self):
        if not DAVINCI_OK: return
        def fn(): return _dvr.add_render_job("YouTube 1080p")
        def done(r): self._integ_log(f"Render job: {r}")
        self._run_in_thread(fn, on_done=done)

    # ── Unreal methods ────────────────────────────────────────

    def _ue_connect(self):
        if not UNREAL_OK: self._integ_log("UE bridge module not found"); return
        def fn(): return _ue.connect()
        def done(r): self._integ_log(f"UE: {'Connected ✓' if r else 'Not running — enable remote execution in UE'}")
        self._run_in_thread(fn, on_done=done)

    def _ue_world_info(self):
        if not UNREAL_OK: return
        def fn(): return _ue.status()
        def done(s): self._integ_log(f"UE Status: {json.dumps(s, indent=2)}")
        self._run_in_thread(fn, on_done=done)

    def _ue_list_assets(self):
        if not UNREAL_OK: return
        def fn(): return _ue.list_assets("/Game")
        def done(assets):
            self._integ_log(f"UE Assets ({len(assets)}):")
            for a in assets[:8]:
                self._integ_log(f"  {a.get('path','?')} [{a.get('type','?')}]")
        self._run_in_thread(fn, on_done=done)

    def _ue_new_level(self):
        if not UNREAL_OK: return
        name = f"AI_Level_{datetime.now().strftime('%Y%m%d_%H%M')}"
        def fn(): return _ue.create_level(name)
        def done(r): self._integ_log(f"UE Level: {r}")
        self._run_in_thread(fn, on_done=done)

    def _ue_run_python(self):
        if not UNREAL_OK: return
        code = "import unreal; print(unreal.SystemLibrary.get_engine_version())"
        def fn(): return _ue.run_python(code)
        def done(r): self._integ_log(f"UE Python: {r.get('output','')}")
        self._run_in_thread(fn, on_done=done)

    # ── Memory manager methods ────────────────────────────────

    def _lms_check(self):
        """Check LM Studio connection and update status."""
        if not LMS_OK:
            self.lms_status_lbl.setText("lm_studio.py not found")
            return
        def check():
            return _lms.status()
        def done(s):
            if s.get("lm_studio"):
                models = s.get("lm_studio_models", [])
                model  = models[0][:30] if models else "no model loaded"
                self.lms_status_lbl.setText(f"● CONNECTED · {model}")
                self.lms_status_lbl.setStyleSheet("color:#a78bfa; font-size:11px; font-weight:bold;")
                self._integ_log(f"LM Studio connected · Models: {models}")
            else:
                self.lms_status_lbl.setText("○ offline — open LM Studio and start server")
                self.lms_status_lbl.setStyleSheet("color:#8b949e; font-size:11px;")
                self._integ_log(
                    "LM Studio offline. Start: LM Studio app → Local Server tab → Start Server"
                )
        self._run_in_thread(check, on_done=done)

    def _mem_report(self):
        if not MM_OK: self._integ_log("memory_manager module not found"); return
        mem_path = str(_WON_ROOT / "data" / "won_memory.db")
        def fn(): return _mm.efficiency_report(mem_path)
        def done(r): self._integ_log(f"Memory Report:\n{json.dumps(r, indent=2)}")
        self._run_in_thread(fn, on_done=done)

    def _mem_clean(self):
        if not MM_OK: return
        def fn(): return _mm.scan_residue(report_only=False)
        def done(r): self._integ_log(f"Residue cleaned: {r['cleaned']}")
        self._run_in_thread(fn, on_done=done)

    def _mem_compress(self):
        if not MM_OK: return
        mem_path = str(_WON_ROOT / "data" / "won_memory.db")
        def fn(): return _mm.compress_old_entries(mem_path, older_than_days=30)
        def done(r): self._integ_log(
            f"Compressed {r['compressed']} entries — saved {r['kb_saved']} KB"
        )
        self._run_in_thread(fn, on_done=done)

    def _mem_dedup_stats(self):
        if not MM_OK: return
        def fn(): return _mm.get_dedup().stats()
        def done(r): self._integ_log(f"Dedup: {r}")
        self._run_in_thread(fn, on_done=done)

    # ── Anti-hallucination ────────────────────────────────────

    def _ah_verify_last(self):
        if not AH_OK: self._integ_log("anti_hallucination module not found"); return
        last = self.detail.toPlainText() or ""
        if not last:
            self._integ_log("No content in detail view to verify")
            return
        def fn():
            return _ah.verify_response(
                original_question="Review this content",
                response=last[:800],
            )
        def done(r):
            self._integ_log(
                f"Verification: {'PASS ✓' if r.get('verified') else 'ISSUES FOUND'}\n"
                f"Questions checked: {len(r.get('verification_questions', []))}\n"
                f"Issues: {r.get('issue_count', 0)}"
            )
            if r.get("revised"):
                self._integ_log(f"Revised:\n{r['revised'][:300]}")
        self._run_in_thread(fn, on_done=done)

    def _build_agent_tab(self):
        """
        Agent Protocol — WON ↔ Claude direct API communication.
        Channel A: WON calls Anthropic API directly (no human in loop).
        Channel B: Browser bridge (clipboard — already built via Claude button).
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        hdr = QLabel("WON ↔ CLAUDE  —  AGENT PROTOCOL  AMP/1.0")
        hdr.setStyleSheet("color:#58a6ff; font-weight:bold; font-size:14px;")
        lay.addWidget(hdr)

        sub = QLabel(
            "Channel A: WON calls Anthropic API directly — no human in the loop.\n"
            "Channel B: Claude button on the floating widget (clipboard bridge — human bridges the two)."
        )
        sub.setStyleSheet("color:#8b949e; font-size:12px;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # ── API Key setup ─────────────────────────────────────
        key_box = QWidget()
        key_box.setStyleSheet(
            "background:#161b22; border:1px solid #30363d; border-radius:6px;"
        )
        kl = QHBoxLayout(key_box)
        kl.setContentsMargins(10, 8, 10, 8)
        kl.addWidget(QLabel("Anthropic API Key:"))
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText(
            "sk-ant-... (get free key at console.anthropic.com)"
        )
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        existing_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if existing_key:
            self.api_key_input.setText(existing_key)
            self.api_key_input.setPlaceholderText("Key loaded from environment ✓")
        kl.addWidget(self.api_key_input)
        save_key_btn = QPushButton("Save Key")
        save_key_btn.setFixedWidth(80)
        save_key_btn.clicked.connect(self._agent_save_key)
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._agent_test_connection)
        kl.addWidget(save_key_btn)
        kl.addWidget(test_btn)
        lay.addWidget(key_box)

        # ── Connection status ─────────────────────────────────
        self.agent_conn_status = QLabel("◌ Not tested")
        self.agent_conn_status.setStyleSheet("color:#8b949e; font-size:12px; padding:4px;")
        lay.addWidget(self.agent_conn_status)

        # ── Agent query interface ─────────────────────────────
        split = QSplitter(Qt.Orientation.Horizontal)

        # Left: send queries
        send_box = QWidget()
        sl = QVBoxLayout(send_box)
        sl.setContentsMargins(0, 0, 6, 0)

        sl.addWidget(self._section_label("SEND TO CLAUDE (Channel A — Direct API)"))

        intent_row = QHBoxLayout()
        intent_row.addWidget(QLabel("Intent:"))
        self.intent_select = QListWidget()
        self.intent_select.setMaximumHeight(90)
        self.intent_select.setMaximumWidth(160)
        for intent in ["query", "validate", "brief_request", "research", "coordinate"]:
            self.intent_select.addItem(intent)
        self.intent_select.setCurrentRow(0)
        intent_row.addWidget(self.intent_select)
        intent_row.addStretch()
        sl.addLayout(intent_row)

        self.agent_query_input = QTextEdit()
        self.agent_query_input.setPlaceholderText(
            "Type your query to Claude here.\n\n"
            "WON will automatically attach:\n"
            "  - Last 5 memory entries as context\n"
            "  - Current ground state\n"
            "  - Agent identity envelope\n\n"
            "Claude responds in structured AMP format.\n"
            "Response is indexed into WON memory automatically."
        )
        self.agent_query_input.setMaximumHeight(160)
        sl.addWidget(self.agent_query_input)

        send_btns = QHBoxLayout()
        send_btn = QPushButton("→ Send to Claude API")
        send_btn.setStyleSheet(
            "background:#1f6feb; color:#fff; font-weight:bold; border-radius:4px; padding:6px 12px;"
        )
        send_btn.clicked.connect(self._agent_send)
        validate_btn = QPushButton("Validate WON Output")
        validate_btn.setToolTip("Send WON's last chat response to Claude for validation")
        validate_btn.clicked.connect(self._agent_validate_won)
        brief_btn = QPushButton("Strategic Brief")
        brief_btn.clicked.connect(self._agent_strategic_brief)
        send_btns.addWidget(send_btn)
        send_btns.addWidget(validate_btn)
        send_btns.addWidget(brief_btn)
        sl.addLayout(send_btns)

        # Right: response display
        resp_box = QWidget()
        rl = QVBoxLayout(resp_box)
        rl.setContentsMargins(6, 0, 0, 0)

        rl.addWidget(self._section_label("CLAUDE'S RESPONSE (parsed AMP format)"))

        self.agent_response = QTextEdit()
        self.agent_response.setReadOnly(True)
        self.agent_response.setStyleSheet(
            "background:#010409; border:2px solid #1f6feb; "
            "border-radius:4px; padding:10px; color:#c9d1d9; font-size:12px;"
        )
        self.agent_response.setPlaceholderText(
            "Claude's structured response appears here.\n\n"
            "Fields parsed:\n"
            "  CONFIDENCE: how certain Claude is\n"
            "  RESPONSE: the actual answer\n"
            "  FORWARD_VECTOR: what WON should do next\n"
            "  METADATA: any structured data\n\n"
            "All responses auto-indexed into WON memory as source=claude."
        )
        rl.addWidget(self.agent_response, stretch=1)

        # Stats row
        self.agent_stats = QLabel("Tokens: — · Confidence: — · Exchanges: 0")
        self.agent_stats.setStyleSheet("color:#8b949e; font-size:11px;")
        rl.addWidget(self.agent_stats)

        btn_row2 = QHBoxLayout()
        copy_btn = QPushButton("Copy Response")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(
            self.agent_response.toPlainText()
        ))
        save_session_btn = QPushButton("Save Session")
        save_session_btn.clicked.connect(self._agent_save_session)
        btn_row2.addWidget(copy_btn)
        btn_row2.addWidget(save_session_btn)
        btn_row2.addStretch()
        rl.addLayout(btn_row2)

        split.addWidget(send_box)
        split.addWidget(resp_box)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        lay.addWidget(split)

        self._agent_loop = None   # lazy init
        self.tabs.addTab(w, "Agent API ◈")

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("section")
        return lbl

    def _get_agent_loop(self):
        """Lazy-init the AgentLoop with current API key."""
        if not AP_OK:
            return None
        key = self.api_key_input.text().strip()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
        if self._agent_loop is None:
            self._agent_loop = _ap.AgentLoop()
        elif key:
            self._agent_loop.channel.api_key = key
        return self._agent_loop

    def _agent_save_key(self):
        key = self.api_key_input.text().strip()
        if not key:
            self.status.showMessage("No key to save")
            return
        os.environ["ANTHROPIC_API_KEY"] = key
        # Persist to user environment permanently
        import subprocess
        subprocess.run(["setx", "ANTHROPIC_API_KEY", key], capture_output=True)
        self.status.showMessage("API key saved to user environment ✓")

    def _agent_test_connection(self):
        if not AP_OK:
            self.agent_conn_status.setText("✗ agent_protocol.py not found")
            return
        key = self.api_key_input.text().strip()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
        self._busy(True)
        self.agent_conn_status.setText("◌ Testing…")

        def test():
            return _ap.check_api_connection()

        def done(result):
            self._busy(False)
            if result.get("ok"):
                self.agent_conn_status.setText(
                    f"● CONNECTED  ·  Model: {result.get('model','')}  ·  "
                    f"Tokens: {result.get('tokens_used', {})}"
                )
                self.agent_conn_status.setStyleSheet(
                    "color:#3fb950; font-size:12px; padding:4px; font-weight:bold;"
                )
            else:
                self.agent_conn_status.setText(
                    f"✗ {result.get('error','')}  {result.get('fix','')}"
                )
                self.agent_conn_status.setStyleSheet(
                    "color:#f85149; font-size:12px; padding:4px;"
                )

        self._run_in_thread(test, on_done=done)

    def _agent_send(self):
        query = self.agent_query_input.toPlainText().strip()
        if not query:
            self.status.showMessage("Enter a query first")
            return
        loop = self._get_agent_loop()
        if not loop:
            self.agent_response.setPlainText("agent_protocol.py not found")
            return

        intent_items = self.intent_select.selectedItems()
        intent = intent_items[0].text() if intent_items else "query"

        self.agent_response.setPlainText("⟳ WON sending to Claude via API…\n(This is Channel A — direct, no human in loop)")
        self._busy(True)

        def send():
            return loop.query(query, intent=intent)

        def done(resp):
            self._busy(False)
            if resp.ok:
                self.agent_response.setPlainText(
                    f"TASK: {resp.task_id}\n"
                    f"ACK:  {'✓' if resp.acknowledged else '?'}\n"
                    f"CONF: {resp.confidence:.0%}\n\n"
                    f"RESPONSE:\n{resp.response}\n\n"
                    f"FORWARD VECTOR:\n{resp.forward_vector}\n\n"
                    f"METADATA:\n{json.dumps(resp.metadata, indent=2)}"
                )
                summ = loop.session_summary()
                self.agent_stats.setText(
                    f"Tokens: {resp.tokens_used} · "
                    f"Confidence: {resp.confidence:.0%} · "
                    f"Exchanges: {summ['exchanges']}"
                )
                self.status.showMessage(
                    f"Claude responded — indexed as 🔵 in memory · {resp.tokens_used} tokens"
                )
            else:
                self.agent_response.setPlainText(f"ERROR: {resp.error}")
                self.status.showMessage(f"API error: {resp.error[:80]}")

        self._run_in_thread(send, on_done=done)

    def _agent_validate_won(self):
        """Send WON's last chat response to Claude for validation."""
        won_text = ""
        if hasattr(self, '_chat_log') and self._chat_log:
            for entry in reversed(self._chat_log):
                if entry.get("role") == "assistant":
                    won_text = entry.get("text", "")
                    break
        if not won_text:
            won_text = self.detail.toPlainText()[:600]
        if not won_text:
            self.status.showMessage("No WON output found to validate")
            return

        loop = self._get_agent_loop()
        if not loop: return

        self.agent_response.setPlainText("⟳ Sending WON output to Claude for validation…")
        self._busy(True)

        def validate():
            return loop.validate_won_output(won_text, "Last WON response")

        def done(resp):
            self._busy(False)
            if resp.ok:
                self.agent_response.setPlainText(
                    f"VALIDATION RESULT\nTask: {resp.task_id}\n"
                    f"Confidence: {resp.confidence:.0%}\n\n"
                    f"{resp.response}"
                )
            else:
                self.agent_response.setPlainText(f"Validation error: {resp.error}")

        self._run_in_thread(validate, on_done=done)

    def _agent_strategic_brief(self):
        topic = self.agent_query_input.toPlainText().strip() or "DBOMBCENTRAL ACAS Phase 1"
        loop = self._get_agent_loop()
        if not loop: return

        self.agent_response.setPlainText(f"⟳ Claude generating strategic brief on: {topic}…")
        self._busy(True)

        def brief():
            return loop.generate_strategic_brief(topic)

        def done(resp):
            self._busy(False)
            if resp.ok:
                self.agent_response.setPlainText(resp.response)
            else:
                self.agent_response.setPlainText(f"Error: {resp.error}")

        self._run_in_thread(brief, on_done=done)

    def _agent_save_session(self):
        loop = self._get_agent_loop()
        if not loop or not AP_OK: return
        path = _ap.save_session(loop)
        self.status.showMessage(f"Session saved → {Path(path).name}")

    def _build_training_tab(self):
        """Training Program — Dan teaches WON who he is."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        hdr = QHBoxLayout()
        hdr_lbl = QLabel("WON TRAINING PROGRAM  —  Teach WON who you are")
        hdr_lbl.setStyleSheet("color:#58a6ff; font-weight:bold; font-size:14px;")
        hdr.addWidget(hdr_lbl)
        hdr.addStretch()
        self.training_status = QLabel("")
        self.training_status.setStyleSheet("color:#3fb950; font-size:12px;")
        hdr.addWidget(self.training_status)
        lay.addLayout(hdr)

        sub = QLabel(
            "Everything you enter here becomes part of WON's identity. "
            "WON will address you by name, reference your projects, and adapt its style."
        )
        sub.setStyleSheet("color:#8b949e; font-size:12px;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        form_widget = QWidget()
        form_widget.setStyleSheet(
            "background:#161b22; border:1px solid #21262d; border-radius:6px; padding:4px;"
        )
        form = QVBoxLayout(form_widget)
        form.setSpacing(8)
        self._train_fields = {}
        profile = load_profile()

        fields = [
            ("name",        "Your Name",          "How WON addresses you"),
            ("projects",    "Active Projects",     "Comma-separated list"),
            ("goals",       "Your Goals",          "What you are building and why"),
            ("preferences", "Communication Style", "How you like to be spoken to"),
            ("notes",       "Additional Context",  "Anything else WON should know"),
        ]
        for key, label, placeholder in fields:
            row = QVBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet("color:#58a6ff; font-size:11px; font-weight:bold;")
            row.addWidget(lbl)
            val = profile.get(key, "")
            if isinstance(val, list):
                val = ", ".join(val)
            if key in ("goals", "preferences", "notes"):
                field = QTextEdit()
                field.setPlainText(val)
                field.setFixedHeight(60)
            else:
                field = QLineEdit(val)
                field.setPlaceholderText(placeholder)
            self._train_fields[key] = field
            row.addWidget(field)
            form.addLayout(row)
        lay.addWidget(form_widget)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("✓  Save Profile  →  Train WON")
        save_btn.setStyleSheet(
            "background:#238636; color:#fff; font-weight:bold; "
            "border-radius:5px; padding:8px 20px;"
        )
        save_btn.clicked.connect(self._save_training)
        intro_btn = QPushButton("Ask WON to introduce himself")
        intro_btn.clicked.connect(self._won_introduce)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(intro_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        resp_lbl = QLabel("WON ACKNOWLEDGMENT")
        resp_lbl.setObjectName("section")
        lay.addWidget(resp_lbl)
        self.training_response = QTextEdit()
        self.training_response.setReadOnly(True)
        self.training_response.setFixedHeight(120)
        self.training_response.setPlaceholderText("Save your profile and WON will respond here…")
        lay.addWidget(self.training_response)

        self.tabs.addTab(w, "Training ◈")

    def _save_training(self):
        global CHAPERONE_PROMPT
        profile = {}
        for key, field in self._train_fields.items():
            val = field.toPlainText().strip() if isinstance(field, QTextEdit) else field.text().strip()
            profile[key] = [p.strip() for p in val.split(",") if p.strip()] if key == "projects" else val
        save_profile(profile)
        CHAPERONE_PROMPT = build_chaperone_prompt()
        name = profile.get("name", "Dan")
        self.training_status.setText(f"✓ Saved — WON knows you as {name}")
        self.setWindowTitle(f"AI Monitor — Command Hub  ·  {name}")
        self.training_response.setPlainText("⟳ WON processing your profile…")
        prompt = (
            f"{CHAPERONE_PROMPT}\n\n"
            f"Your profile was just updated. Acknowledge in 3-4 sentences. "
            f"Confirm you know {name}'s name, projects, and goals. "
            f"State one specific way you will serve better now. Address them by name."
        )
        def ack(): return self._ollama_call(prompt, timeout=120)
        def done(r):
            self.training_response.setPlainText(r)
            wp = get_won_pipeline()
            if wp:
                try: wp.contribute(f"[Training] Profile saved for {name}.\n{r}",
                                   source="won", mode="training", tags=["training"])
                except Exception: pass
        self._run_in_thread(ack, on_done=done)

    def _won_introduce(self):
        self.training_response.setPlainText("⟳ WON preparing introduction…")
        prompt = (
            f"{CHAPERONE_PROMPT}\n\n"
            f"Introduce yourself in 4-5 sentences. Be clear: you are WON — not Claude, not Gemini. "
            f"Explain what you can see, what you remember, and how you serve your principal. "
            f"Be distinguished. Address them by name."
        )
        def intro(): return self._ollama_call(prompt, timeout=120)
        def done(r): self.training_response.setPlainText(r)
        self._run_in_thread(intro, on_done=done)


    def _build_convprog_tab(self):
        """
        Conversational Programming — Dan speaks, WON builds.
        No syntax. No manual editing. Just intent → working code.
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        hdr_lbl = QLabel("CODEFORGE  —  WON's Programming Architect  ·  Speak it. WON builds it.")
        hdr_lbl.setStyleSheet("color:#58a6ff; font-weight:bold; font-size:14px;")
        hdr.addWidget(hdr_lbl)
        hdr.addStretch()
        stats_lbl = QLabel("")
        stats_lbl.setObjectName("section")
        self._cp_stats_lbl = stats_lbl
        hdr.addWidget(stats_lbl)
        lay.addLayout(hdr)

        sub = QLabel(
            "Describe any change in plain English. "
            "WON reads the actual code, generates the change, tests it, "
            "and asks for your approval before touching anything."
        )
        sub.setStyleSheet("color:#8b949e; font-size:12px;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # Example prompts
        examples = QHBoxLayout()
        example_lbl = QLabel("Try:")
        example_lbl.setStyleSheet("color:#8b949e; font-size:11px;")
        examples.addWidget(example_lbl)
        for ex in [
            "Make the Portal header bright orange",
            "Add a timestamp to every chat message",
            "Make the WON feed auto-scroll to newest",
            "Add a clear button to the search bar",
        ]:
            b = QPushButton(ex)
            b.setStyleSheet("font-size:10px; padding:3px 8px; color:#8b949e;")
            b.clicked.connect(lambda checked, t=ex: self._cp_set_request(t))
            examples.addWidget(b)
        examples.addStretch()
        lay.addLayout(examples)

        # Main split: left = conversation | right = code diff
        split = QSplitter(Qt.Orientation.Horizontal)

        # Left: conversation
        left = QWidget()
        ll   = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 6, 0)

        conv_lbl = QLabel("CONVERSATION")
        conv_lbl.setObjectName("section")
        ll.addWidget(conv_lbl)

        self.cp_conversation = QTextEdit()
        self.cp_conversation.setReadOnly(True)
        self.cp_conversation.setStyleSheet(
            "background:#010409; border:1px solid #21262d; "
            "border-radius:4px; padding:10px; color:#c9d1d9; font-size:13px;"
        )
        self.cp_conversation.setPlaceholderText(
            "WON: Good day, Dan. Describe any change you want — "
            "I'll build it. Be as specific or as vague as you like. "
            "I'll ask if I need clarification.\n\n"
            "Examples:\n"
            "  'Make the theme red and gold'\n"
            "  'Add a search history dropdown'\n"
            "  'Make WON respond faster'\n"
            "  'Add a loading spinner to the memory feed'"
        )
        ll.addWidget(self.cp_conversation, stretch=1)

        # Error paste field
        err_lbl = QLabel("Paste runtime error (optional — WON will fix it):")
        err_lbl.setStyleSheet("color:#8b949e; font-size:11px;")
        ll.addWidget(err_lbl)
        self.cp_error_input = QTextEdit()
        self.cp_error_input.setMaximumHeight(55)
        self.cp_error_input.setPlaceholderText("Paste traceback or error message here…")
        self.cp_error_input.setStyleSheet(
            "background:#1a0a0a; border:1px solid #f85149; border-radius:4px; "
            "padding:4px; color:#ffcccc; font-size:11px; font-family:Consolas,monospace;"
        )
        ll.addWidget(self.cp_error_input)

        # Request input
        cp_input_row = QHBoxLayout()
        self.cp_input = QLineEdit()
        self.cp_input.setPlaceholderText("Tell WON what you want or describe the fix… (Enter)")
        self.cp_input.returnPressed.connect(self._cp_send)
        cp_send = QPushButton("Build it")
        cp_send.setStyleSheet(
            "background:#238636; color:#fff; font-weight:bold; padding:7px 14px;"
        )
        cp_send.clicked.connect(self._cp_send)
        cp_input_row.addWidget(self.cp_input)
        cp_input_row.addWidget(cp_send)
        ll.addLayout(cp_input_row)

        # Approve/Reject row
        ar_row = QHBoxLayout()
        self.cp_approve_btn = QPushButton("✓ Apply Change")
        self.cp_approve_btn.setStyleSheet(
            "background:#238636; color:#fff; font-weight:bold; padding:7px 14px;"
        )
        self.cp_approve_btn.setEnabled(False)
        self.cp_approve_btn.clicked.connect(self._cp_approve)

        self.cp_reject_btn = QPushButton("✗ Reject")
        self.cp_reject_btn.setStyleSheet("color:#f85149; padding:7px 14px;")
        self.cp_reject_btn.setEnabled(False)
        self.cp_reject_btn.clicked.connect(self._cp_reject)

        ar_row.addWidget(self.cp_approve_btn)
        ar_row.addWidget(self.cp_reject_btn)
        ar_row.addStretch()
        ll.addLayout(ar_row)

        # Right: code diff viewer
        right = QWidget()
        rl    = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)

        diff_lbl = QLabel("PROPOSED CODE CHANGE")
        diff_lbl.setObjectName("section")
        rl.addWidget(diff_lbl)

        self.cp_old_code = QTextEdit()
        self.cp_old_code.setReadOnly(True)
        self.cp_old_code.setMaximumHeight(200)
        self.cp_old_code.setStyleSheet(
            "background:#2a1a1a; border:1px solid #f85149; "
            "border-radius:4px; padding:8px; color:#ffcccc; font-size:12px; "
            "font-family:Consolas,monospace;"
        )
        self.cp_old_code.setPlaceholderText("Old code (will be replaced)")
        rl.addWidget(self.cp_old_code)

        arrow_lbl = QLabel("↓  REPLACES WITH  ↓")
        arrow_lbl.setStyleSheet("color:#8b949e; text-align:center; padding:2px;")
        arrow_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.addWidget(arrow_lbl)

        self.cp_new_code = QTextEdit()
        self.cp_new_code.setReadOnly(True)
        self.cp_new_code.setStyleSheet(
            "background:#1a2a1a; border:1px solid #3fb950; "
            "border-radius:4px; padding:8px; color:#ccffcc; font-size:12px; "
            "font-family:Consolas,monospace;"
        )
        self.cp_new_code.setPlaceholderText("New code (what WON will write)")
        rl.addWidget(self.cp_new_code, stretch=1)

        # Test result
        self.cp_test_result = QLabel("")
        self.cp_test_result.setStyleSheet("color:#8b949e; font-size:11px; padding:4px;")
        rl.addWidget(self.cp_test_result)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        lay.addWidget(split)

        self.tabs.addTab(w, "CodeForge ◈")
        self._cp_engine = None
        QTimer.singleShot(500, self._cp_refresh_stats)

    def _cp_set_request(self, text: str):
        self.cp_input.setText(text)
        self.cp_input.setFocus()

    def _cp_get_engine(self):
        if not CP_OK:
            return None
        if self._cp_engine is None:
            self._cp_engine = _cp.get_engine()
        return self._cp_engine

    def _cp_refresh_stats(self):
        engine = self._cp_get_engine()
        if engine:
            s = engine.stats()
            o = s.get("outcomes", {})
            self._cp_stats_lbl.setText(
                f"Total: {o.get('total',0)} · "
                f"Approved: {o.get('approved',0)} · "
                f"Rate: {o.get('rate',0):.0%}"
            )

    def _cp_send(self):
        request = self.cp_input.text().strip()
        if not request:
            return
        self.cp_input.clear()

        # Show user message
        ts = datetime.now().strftime("%H:%M")
        self.cp_conversation.append(
            f'\n<b style="color:#58a6ff;">[{ts}] Dan:</b> {request}\n'
        )

        engine = self._cp_get_engine()
        if not engine:
            self.cp_conversation.append(
                '<i style="color:#f85149;">conv_programming.py not found</i>'
            )
            return

        self._busy(True)
        self.cp_approve_btn.setEnabled(False)
        self.cp_reject_btn.setEnabled(False)
        self.cp_conversation.append(
            '<i style="color:#8b949e;">⟳ WON analyzing and building…</i>'
        )

        try:
            profile = load_profile()
        except Exception:
            profile = {}

        error_text = self.cp_error_input.toPlainText().strip()
        if error_text:
            self.cp_error_input.clear()

        def process():
            return engine.process(request, profile=profile, error_text=error_text)

        def done(result):
            self._busy(False)
            # Remove thinking indicator
            current = self.cp_conversation.toPlainText()
            self.cp_conversation.setPlainText(
                current.replace("⟳ WON analyzing and building…", "").rstrip()
            )

            msg   = result.get("message", "")
            rtype = result.get("type", "")

            self.cp_conversation.append(
                f'\n<b style="color:#3fb950;">[{datetime.now().strftime("%H:%M")}] CodeForge:</b> {msg}\n'
            )

            if rtype == "proposal":
                proposal = result.get("proposal", {})
                code     = proposal.get("code", {})
                test     = proposal.get("test", {})

                # Show analysis in conversation if present
                analysis = code.get("analysis", "")
                if analysis:
                    self.cp_conversation.append(
                        f'<i style="color:#8b949e;">Analysis: {analysis}</i>\n'
                    )

                # Dependencies warning
                deps = code.get("dependencies", "none")
                if deps and deps.lower() != "none":
                    self.cp_conversation.append(
                        f'<b style="color:#f0883e;">⚠ New dependencies needed: {deps}</b>\n'
                    )

                # Rollback info
                rollback = code.get("rollback", "")
                if rollback:
                    self.cp_conversation.append(
                        f'<i style="color:#8b949e;">Rollback: {rollback}</i>\n'
                    )

                # Show code diff
                self.cp_old_code.setPlainText(code.get("old_code", "(new code — nothing replaced)"))
                self.cp_new_code.setPlainText(code.get("new_code", ""))

                # Test badge
                if test.get("testable"):
                    badge = "✓ Tested OK" if test.get("ok") else f"✗ Test failed: {test.get('reason','')}"
                    color = "#3fb950" if test.get("ok") else "#f85149"
                else:
                    badge = f"⚠ {test.get('reason', 'Untestable — UI code, visual check required')}"
                    color = "#f0883e"
                self.cp_test_result.setText(
                    f"{badge}  ·  Confidence: {code.get('confidence',0):.0%}"
                )
                self.cp_test_result.setStyleSheet(f"color:{color}; font-size:11px; padding:4px;")

                # Enable approve/reject
                self.cp_approve_btn.setEnabled(True)
                self.cp_reject_btn.setEnabled(True)

            elif rtype == "clarification":
                self.cp_old_code.setPlainText("")
                self.cp_new_code.setPlainText("")
                self.cp_test_result.setText("")

            self._cp_refresh_stats()

        self._run_in_thread(process, on_done=done)

    def _cp_approve(self):
        engine = self._cp_get_engine()
        if not engine:
            return
        result = engine.approve()
        self.cp_conversation.append(
            f'\n<b style="color:#3fb950;">WON:</b> {result.get("message","")}\n'
        )
        self.cp_approve_btn.setEnabled(False)
        self.cp_reject_btn.setEnabled(False)
        self._cp_refresh_stats()

    def _cp_reject(self):
        engine = self._cp_get_engine()
        if not engine:
            return
        result = engine.reject()
        self.cp_conversation.append(
            f'\n<b style="color:#f0883e;">WON:</b> {result.get("message","")}\n'
        )
        self.cp_approve_btn.setEnabled(False)
        self.cp_reject_btn.setEnabled(False)
        self.cp_old_code.setPlainText("")
        self.cp_new_code.setPlainText("")
        self.cp_test_result.setText("")
        self._cp_refresh_stats()

    def _on_select(self, cur, _prev):
        if not cur: return
        d = cur.data(Qt.ItemDataRole.UserRole)
        if isinstance(d, dict):
            self.detail.setPlainText(d.get("text", ""))
        elif d and P(d).is_file():
            self.detail.setPlainText(P(d).read_text(encoding="utf-8", errors="replace"))

    # ─────────────────────────────────────────────────────────────────────────
    # PULSE ENGINE EVENT HANDLER — called from any thread via QTimer.singleShot
    # ─────────────────────────────────────────────────────────────────────────

    def _on_pulse_event(self, event):
        """Route a PulseEvent to the live terminal display."""
        try:
            loop  = event.loop
            kind  = event.kind
            data  = event.data
            ts    = datetime.now().strftime("%H:%M:%S")

            color_map = {
                "start":     "#3fb950",  # green
                "ready":     "#3fb950",
                "stop":      "#f85149",
                "error":     "#f85149",
                "insight":   "#58a6ff",
                "vector":    "#d4a017",
                "milestone": "#d4a017",
                "adapt":     "#bc8cff",
                "captured":  "#3fb950",
                "observe":   "#8b949e",
                "tick":      "#30363d",
                "idle":      "#30363d",
                "skip":      "#30363d",
            }
            color   = color_map.get(kind, "#c9d1d9")
            loop_tag = f'<span style="color:#8b949e;">[{loop}]</span>'
            kind_tag = f'<span style="color:{color};">{kind.upper()}</span>'
            ts_tag   = f'<span style="color:#30363d;">{ts}</span>'
            msg      = f'{ts_tag} {loop_tag} {kind_tag} {data}'

            if hasattr(self, "pulse_terminal"):
                self.pulse_terminal.append(msg)
                # Auto-scroll to bottom
                sb = self.pulse_terminal.verticalScrollBar()
                sb.setValue(sb.maximum())

            # Surface high-priority events to status bar
            if event.priority <= 3:
                self.status.showMessage(f"[STRATUM] {data[:100]}")

            # Surface insights to badge
            if kind == "insight" and hasattr(self, "badge"):
                self.badge.setStyleSheet("color:#58a6ff; font-weight:bold;")
                QTimer.singleShot(5000, lambda: self.badge.setStyleSheet(
                    "color:#3fb950; font-weight:bold;"))
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # PULSE TAB — Live STRATUM Terminal
    # ─────────────────────────────────────────────────────────────────────────

    def _build_pulse_tab(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)

        # Header bar
        hdr = QWidget()
        hdr.setStyleSheet("background:#161b22; border-bottom:1px solid #21262d; padding:6px 12px;")
        hl  = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 6, 12, 6)
        lbl = QLabel("STRATUM PULSE  —  LIVE TERMINAL")
        lbl.setStyleSheet("color:#58a6ff; font-weight:bold; font-size:12px; letter-spacing:2px;")
        hl.addWidget(lbl)
        hl.addStretch()

        self._pulse_status_lbl = QLabel("● INITIALIZING")
        self._pulse_status_lbl.setStyleSheet("color:#f0883e; font-size:11px;")
        hl.addWidget(self._pulse_status_lbl)
        lay.addWidget(hdr)

        # Control bar
        ctrl = QHBoxLayout()
        ctrl.setContentsMargins(12, 6, 12, 6)
        for label, slot in [
            ("Start Pulse",    self._pulse_start),
            ("Stop Pulse",     self._pulse_stop),
            ("Clear Log",      self._pulse_clear),
            ("Harvest Now",    self._pulse_harvest),
            ("Pulse State",    self._pulse_state),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            ctrl.addWidget(b)
        ctrl.addStretch()
        lay.addLayout(ctrl)

        # Live terminal
        self.pulse_terminal = QTextEdit()
        self.pulse_terminal.setReadOnly(True)
        self.pulse_terminal.setStyleSheet(
            "background:#010409; color:#c9d1d9; font-family:'Consolas','Courier New',monospace; "
            "font-size:12px; border:none; padding:8px;"
        )
        self.pulse_terminal.append(
            '<span style="color:#58a6ff;">STRATUM PULSE ENGINE — LIVE TERMINAL</span><br>'
            '<span style="color:#8b949e;">Waiting for engine start…</span>'
        )
        lay.addWidget(self.pulse_terminal, stretch=1)

        # Insight bar
        self._insight_bar = QLabel("")
        self._insight_bar.setStyleSheet(
            "background:#161b22; color:#58a6ff; padding:6px 12px; "
            "border-top:1px solid #21262d; font-size:12px;"
        )
        self._insight_bar.setWordWrap(True)
        lay.addWidget(self._insight_bar)

        self.tabs.addTab(w, "STRATUM Pulse")

    def _pulse_start(self):
        if PULSE_OK:
            try:
                _pulse.start()
                self._pulse_status_lbl.setText("● LIVE")
                self._pulse_status_lbl.setStyleSheet("color:#3fb950; font-size:11px;")
            except Exception as e:
                self.status.showMessage(f"Pulse start error: {e}")
        else:
            self.pulse_terminal.append(
                '<span style="color:#f85149;">pulse.py not loaded</span>'
            )

    def _pulse_stop(self):
        if PULSE_OK:
            try:
                _pulse.stop()
                self._pulse_status_lbl.setText("● STOPPED")
                self._pulse_status_lbl.setStyleSheet("color:#f85149; font-size:11px;")
            except Exception:
                pass

    def _pulse_clear(self):
        if hasattr(self, "pulse_terminal"):
            self.pulse_terminal.clear()

    def _pulse_harvest(self):
        if HARVEST_OK:
            def _do():
                results = _harvest.scan_temp_files(max_age_hours=2.0)
                stats   = _harvest.get_stats()
                return {"results": results, "stats": stats}
            def _done(r):
                n     = len(r.get("results", []))
                stats = r.get("stats", {})
                self.pulse_terminal.append(
                    f'<span style="color:#3fb950;">HARVEST: {n} new captures · '
                    f'Total: {stats.get("total_captures",0)} · '
                    f'Chars: {stats.get("total_chars",0):,}</span>'
                )
            self._run_in_thread(_do, on_done=_done)
        else:
            self.pulse_terminal.append(
                '<span style="color:#f85149;">harvester.py not loaded</span>'
            )

    def _pulse_state(self):
        if PULSE_OK:
            try:
                e = _pulse.get_engine()
                s = e.get_state()
                uptime = s.get("uptime_s", 0)
                h, m   = divmod(uptime // 60, 60)
                self.pulse_terminal.append(
                    f'<span style="color:#bc8cff;">STATE: cycles={s.get("cycles",0)} · '
                    f'uptime={h}h{m}m · '
                    f'temp={s.get("behavior",{}).get("temperature",0):.2f} · '
                    f'approval={s.get("behavior",{}).get("approval_rate",0):.0%}</span>'
                )
            except Exception as e:
                self.pulse_terminal.append(f'<span style="color:#f85149;">Error: {e}</span>')

    # ─────────────────────────────────────────────────────────────────────────
    # SYNTHESIS TAB — Creative Generation
    # ─────────────────────────────────────────────────────────────────────────

    def _build_synthesis_tab(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)

        hdr = QLabel("SYNTHESIS LAB  —  GENERATIVE OUTPUT ENGINE")
        hdr.setStyleSheet("color:#58a6ff; font-weight:bold; font-size:12px; "
                          "letter-spacing:2px; padding-bottom:8px;")
        lay.addWidget(hdr)

        # Capability status
        self._synth_status = QLabel("")
        self._synth_status.setStyleSheet("color:#8b949e; font-size:11px; padding-bottom:8px;")
        lay.addWidget(self._synth_status)

        QTimer.singleShot(500, self._synth_refresh_status)

        # Prompt input
        il = QHBoxLayout()
        self.synth_prompt = QLineEdit()
        self.synth_prompt.setPlaceholderText("Describe what to generate… (image / concept card / neural map / video)")
        il.addWidget(self.synth_prompt)
        lay.addLayout(il)

        # Action buttons
        btn_row = QHBoxLayout()
        
        # Primary Action: FORGE ARTIFACT (True Synthesis)
        if FORGE_OK:
            forge_btn = QPushButton("FORGE ARTIFACT")
            forge_btn.setStyleSheet("background:#0a2a4d; color:#58a6ff; font-weight:bold; border:1px solid #1f6feb;")
            forge_btn.clicked.connect(self._synth_forge)
            btn_row.addWidget(forge_btn)

        # Secondary Actions: Original generation
        image_btn = QPushButton("Generate Image")
        image_btn.clicked.connect(self._synth_image)
        btn_row.addWidget(image_btn)

        # Analytic Viz Group
        viz_btn = QPushButton("Analytic Viz ▼")
        viz_menu = QMenu(self)
        viz_menu.addAction("Concept Card", self._synth_card)
        viz_menu.addAction("Neural Map", self._synth_neural_map)
        viz_btn.setMenu(viz_menu)
        btn_row.addWidget(viz_btn)

        video_btn = QPushButton("Title Sequence")
        video_btn.clicked.connect(self._synth_video)
        btn_row.addWidget(video_btn)

        speak_btn = QPushButton("Speak Brief")
        speak_btn.clicked.connect(self._synth_speak)
        btn_row.addWidget(speak_btn)

        dir_btn = QPushButton("Open Dir")
        dir_btn.clicked.connect(self._synth_open_dir)
        btn_row.addWidget(dir_btn)
        
        btn_row.addStretch()
        lay.addLayout(btn_row)

        # Output log
        lbl = QLabel("GENERATION LOG")
        lbl.setObjectName("section")
        lay.addWidget(lbl)
        self.synth_log = QTextEdit()
        self.synth_log.setReadOnly(True)
        self.synth_log.setStyleSheet(
            "background:#010409; border:1px solid #21262d; padding:8px; color:#c9d1d9;"
        )
        lay.addWidget(self.synth_log, stretch=1)

        # Agent spawner
        agent_row = QHBoxLayout()
        agent_lbl = QLabel("Spawn Agent:")
        agent_lbl.setStyleSheet("color:#8b949e;")
        agent_row.addWidget(agent_lbl)
        self.synth_agent_input = QLineEdit()
        self.synth_agent_input.setPlaceholderText("Task for SynthesisAgent…")
        agent_row.addWidget(self.synth_agent_input)
        spawn_btn = QPushButton("Spawn SynthesisAgent")
        spawn_btn.clicked.connect(self._synth_spawn_agent)
        agent_row.addWidget(spawn_btn)
        lay.addLayout(agent_row)

        self.tabs.addTab(w, "Synthesis Lab")

    def _synth_refresh_status(self):
        if not SYNTH_OK:
            self._synth_status.setText("synthesis.py not loaded")
            return
        s = _synth.status()
        parts = [
            f"SD: {'ONLINE' if s['sd_available'] else 'offline'}",
            f"PIL: {'ONLINE' if s['pil_available'] else 'offline'}",
            f"FFmpeg: {'ONLINE' if s['ffmpeg_available'] else 'offline'}",
            f"Forge: {'READY' if FORGE_OK else 'offline'}",
            f"Files generated: {s['files_generated']}",
        ]
        self._synth_status.setText("  |  ".join(parts))

    def _synth_log_msg(self, msg: str, color: str = "#c9d1d9"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.synth_log.append(
            f'<span style="color:#30363d;">{ts}</span> '
            f'<span style="color:{color};">{msg}</span>'
        )

    def _synth_image(self):
        prompt = self.synth_prompt.text().strip()
        if not prompt:
            return
        if not SYNTH_OK:
            self._synth_log_msg("synthesis.py not loaded", "#f85149")
            return
            
        self._synth_log_msg(f"Generating image: {prompt[:60]}…", "#8b949e")
        self._busy(True)
        def _gen():
            # If forge is available, use it for better expansion even in fallback
            if FORGE_OK:
                return _forge.synthesize(prompt)
            return {"status": "legacy", "path": _synth.generate_image(prompt)}
            
        def _done(res):
            self._busy(False)
            if isinstance(res, dict) and res.get("status") == "success":
                p = res["path"]
                self._synth_log_msg(f"Image saved: {p}", "#3fb950")
                self._synth_refresh_status()
                try: os.startfile(p)
                except Exception: pass
            elif isinstance(res, dict) and res.get("status") == "prompt_fallback":
                self._synth_forge_display_spec(res.get("spec", {}))
            elif isinstance(res, dict) and res.get("status") == "legacy" and res.get("path"):
                p = res["path"]
                self._synth_log_msg(f"Image saved: {p}", "#3fb950")
            else:
                self._synth_log_msg("Image generation failed — renderer offline", "#f85149")
                if FORGE_OK:
                    # Force a forge call to get the spec
                    self._synth_forge()

        self._run_in_thread(_gen, on_done=_done)

    def _synth_forge_display_spec(self, spec: dict):
        self._synth_log_msg("RENDERER OFFLINE — Returning Generation Spec", "#f0883e")
        self.synth_log.append("<div style='border:1px solid #30363d; padding:10px; margin:5px; background:#161b22;'>")
        self.synth_log.append(f"<b style='color:#58a6ff;'>IMAGE_GENERATION_SPEC</b><br>")
        self.synth_log.append(f"<b style='color:#8b949e;'>IMAGE_PROMPT:</b> {spec.get('IMAGE_PROMPT')}<br>")
        self.synth_log.append(f"<b style='color:#8b949e;'>STYLE:</b> {spec.get('STYLE')}<br>")
        self.synth_log.append(f"<b style='color:#8b949e;'>COMPOSITION:</b> {spec.get('COMPOSITION')}<br>")
        self.synth_log.append(f"<b style='color:#8b949e;'>NEGATIVE_CONSTRAINTS:</b> {spec.get('NEGATIVE_CONSTRAINTS')}")
        self.synth_log.append("</div>")

    def _synth_forge(self):
        prompt = self.synth_prompt.text().strip()
        if not prompt:
            return
        if not FORGE_OK:
            self._synth_log_msg("imageforge.py not loaded", "#f85149")
            return
        self._synth_log_msg(f"FORGING ARTIFACT: {prompt[:60]}…", "#58a6ff")
        self._busy(True)
        def _gen():
            return _forge.synthesize(prompt)
        def _done(res):
            self._busy(False)
            
            # ── EXECUTION AUDIT AUTHORITY VERDICT ──
            audit_res = res.get("audit_result")
            if TRUTH_OK and audit_res:
                verdict_str = _truth.get_audit().format_result(audit_res)
                self.synth_log.append(f"<pre style='color:#c9d1d9; background:#0d1117; padding:5px;'>{verdict_str}</pre>")

            if res.get("status") == "success":
                p = res["path"]
                self._synth_log_msg(f"Artifact forged [{res['mode']}]: {p}", "#3fb950")
                self._synth_log_msg(f"Final Prompt: {res['spec']['IMAGE_PROMPT']}", "#8b949e")
                self._synth_refresh_status()
                try:
                    os.startfile(p)
                except Exception:
                    pass
            elif res.get("status") == "prompt_fallback":
                self._synth_forge_display_spec(res.get("spec", {}))
            else:
                self._synth_log_msg(f"Forge synthesis failed: {res.get('reason', 'Unknown error')}", "#f85149")
        self._run_in_thread(_gen, on_done=_done)

    def _synth_card(self):
        prompt = self.synth_prompt.text().strip()
        if not prompt:
            return
        if not SYNTH_OK:
            self._synth_log_msg("synthesis.py not loaded", "#f85149")
            return
        self._synth_log_msg(f"Creating concept card: {prompt[:60]}…", "#8b949e")
        def _gen():
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            return _synth.create_concept_card(prompt, f"Generated: {ts}\nSTRATUM PRIME")
        def _done(path):
            if path:
                self._synth_log_msg(f"Card saved: {path}", "#3fb950")
            else:
                self._synth_log_msg("Card generation failed — Pillow not installed?", "#f85149")
        self._run_in_thread(_gen, on_done=_done)

    def _synth_neural_map(self):
        if not SYNTH_OK:
            self._synth_log_msg("synthesis.py not loaded", "#f85149")
            return
        if STRAT_OK:
            def _gen():
                dash  = _strat.get_dashboard()
                goals = dash.get("active_goals", [])
                nodes = ["STRATUM"] + [g["name"][:15] for g in goals[:6]]
                edges = [(0, i) for i in range(1, len(nodes))]
                return _synth.create_neural_map(nodes, edges, "STRATUM Architecture")
        else:
            def _gen():
                nodes = ["STRATUM", "Pulse", "Synthesis", "Quantum", "Strategy",
                         "Procreation", "Harvester"]
                edges = [(0, i) for i in range(1, len(nodes))]
                return _synth.create_neural_map(nodes, edges, "STRATUM Engine Map")
        def _done(path):
            if path:
                self._synth_log_msg(f"Neural map saved: {path}", "#3fb950")
            else:
                self._synth_log_msg("Neural map generation failed", "#f85149")
        self._run_in_thread(_gen, on_done=_done)

    def _synth_video(self):
        prompt = self.synth_prompt.text().strip() or "STRATUM PRIME"
        if not SYNTH_OK:
            self._synth_log_msg("synthesis.py not loaded", "#f85149")
            return
        self._synth_log_msg(f"Generating title sequence: {prompt[:40]}…", "#8b949e")
        def _gen():
            return _synth.generate_video(prompt, "DBOMB ASCENDENT", duration=4.0)
        def _done(path):
            if path:
                self._synth_log_msg(f"Video/frame saved: {path}", "#3fb950")
            else:
                self._synth_log_msg("Video generation failed", "#f85149")
        self._run_in_thread(_gen, on_done=_done)

    def _synth_speak(self):
        prompt = self.synth_prompt.text().strip()
        if not prompt:
            prompt = "STRATUM is online. All systems operational."
        if not SYNTH_OK:
            self._synth_log_msg("synthesis.py not loaded", "#f85149")
            return
        self._synth_log_msg(f"Speaking: {prompt[:60]}…", "#8b949e")
        def _speak():
            return _synth.speak_brief(prompt)
        def _done(ok):
            if ok:
                self._synth_log_msg("Brief delivered via TTS", "#3fb950")
            else:
                self._synth_log_msg("TTS unavailable — install pyttsx3", "#f0883e")
        self._run_in_thread(_speak, on_done=_done)

    def _synth_open_dir(self):
        import subprocess
        synth_dir = str(Path.home() / "Documents" / "AI_Monitor" / "synthesis")
        try:
            subprocess.Popen(["explorer", synth_dir])
        except Exception:
            self._synth_log_msg(f"Open: {synth_dir}", "#8b949e")

    def _synth_spawn_agent(self):
        task = self.synth_agent_input.text().strip()
        if not task:
            return
        if not PROC_OK:
            self._synth_log_msg("procreation.py not loaded", "#f85149")
            return
        self._synth_log_msg(f"Spawning SynthesisAgent: {task[:60]}…", "#bc8cff")
        def _on_result(r):
            QTimer.singleShot(0, lambda: self._synth_log_msg(
                f"[{r['agent_id']}] {r['output'][:200]}", "#3fb950"
            ))
        _proc.spawn("SynthesisAgent", task, callback=_on_result)
        self.synth_agent_input.clear()

    # ─────────────────────────────────────────────────────────────────────────
    # STRATEGY TAB — Autonomous Planning Matrix
    # ─────────────────────────────────────────────────────────────────────────

    def _build_strategy_tab(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)

        hdr = QLabel("STRATEGY MATRIX  —  AUTONOMOUS PLANNING ENGINE")
        hdr.setStyleSheet("color:#58a6ff; font-weight:bold; font-size:12px; "
                          "letter-spacing:2px; padding-bottom:8px;")
        lay.addWidget(hdr)

        # Dashboard summary label
        self._strat_summary = QLabel("Loading…")
        self._strat_summary.setStyleSheet(
            "background:#161b22; color:#c9d1d9; padding:8px; border:1px solid #21262d; "
            "font-size:12px;"
        )
        self._strat_summary.setWordWrap(True)
        lay.addWidget(self._strat_summary)

        # Controls
        ctrl = QHBoxLayout()
        for label, slot in [
            ("Refresh",          self._strat_refresh),
            ("Add Goal",         self._strat_add_goal),
            ("Decompose Goal",   self._strat_decompose),
            ("Critical Vector",  self._strat_critical),
            ("Eisenhower View",  self._strat_eisenhower),
            ("Spawn StratAgent", self._strat_spawn_agent),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            ctrl.addWidget(b)
        ctrl.addStretch()
        lay.addLayout(ctrl)

        # Input row
        inp_row = QHBoxLayout()
        self.strat_goal_input = QLineEdit()
        self.strat_goal_input.setPlaceholderText("Goal name or task input…")
        inp_row.addWidget(self.strat_goal_input)
        lay.addLayout(inp_row)

        # Goals list + detail
        split = QSplitter()
        lw    = QWidget()
        ll    = QVBoxLayout(lw)
        ll.setContentsMargins(0, 0, 0, 0)
        lbl2  = QLabel("GOALS"); lbl2.setObjectName("section")
        ll.addWidget(lbl2)
        self.strat_goal_list = QListWidget()
        self.strat_goal_list.currentItemChanged.connect(self._strat_on_select)
        ll.addWidget(self.strat_goal_list)

        rw  = QWidget()
        rl  = QVBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        lbl3 = QLabel("TASKS & VECTORS"); lbl3.setObjectName("section")
        rl.addWidget(lbl3)
        self.strat_detail = QTextEdit()
        self.strat_detail.setReadOnly(True)
        rl.addWidget(self.strat_detail)

        split.addWidget(lw)
        split.addWidget(rw)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, stretch=1)

        self.tabs.addTab(w, "Strategy Matrix")
        QTimer.singleShot(800, self._strat_refresh)

    def _strat_refresh(self):
        if not STRAT_OK:
            self._strat_summary.setText("strategy.py not loaded")
            return
        def _load():
            return _strat.get_dashboard()
        def _done(dash):
            active = dash.get("goals_active", 0)
            done_g = dash.get("goals_complete", 0)
            pct    = dash.get("overall_pct", 0)
            vec    = dash.get("critical_vector") or {}

            summary = (
                f"Active: {active}  |  Complete: {done_g}  |  "
                f"Progress: {pct:.0%}  |  "
                f"Next: {vec.get('task', '—')} [{vec.get('goal', '—')}]"
            )
            self._strat_summary.setText(summary)

            # Populate goal list
            self.strat_goal_list.clear()
            for g in dash.get("active_goals", []):
                item = QListWidgetItem(
                    f"{g['name'][:40]}  [{g['completion_pct']:.0%}]"
                )
                item.setData(Qt.ItemDataRole.UserRole, g)
                self.strat_goal_list.addItem(item)
        self._run_in_thread(_load, on_done=_done)

    def _strat_on_select(self, cur, _prev):
        if not cur:
            return
        g = cur.data(Qt.ItemDataRole.UserRole)
        if not isinstance(g, dict):
            return
        lines = [f"GOAL: {g['name']}", f"Progress: {g.get('completion_pct',0):.0%}",
                 f"Priority: {g.get('priority','?')}", ""]
        krs = g.get("key_results", [])
        if krs:
            lines.append("KEY RESULTS:")
            for kr in krs:
                lines.append(f"  • {kr}")
            lines.append("")
        tasks = g.get("tasks", [])
        if tasks:
            lines.append("TASKS:")
            for t in tasks:
                status_icon = "✓" if t["status"] == "done" else "○"
                lines.append(f"  {status_icon} [{t['priority']}] {t['name']} ({t['effort_h']}h)")
        self.strat_detail.setPlainText("\n".join(lines))

    def _strat_add_goal(self):
        name = self.strat_goal_input.text().strip()
        if not name or not STRAT_OK:
            return
        _strat.get_matrix().add_goal(name, priority=5)
        self.strat_goal_input.clear()
        self._strat_refresh()
        self.status.showMessage(f"Goal added: {name}")

    def _strat_decompose(self):
        cur = self.strat_goal_list.currentItem()
        if not cur or not STRAT_OK:
            return
        g = cur.data(Qt.ItemDataRole.UserRole)
        if not isinstance(g, dict):
            return
        self.status.showMessage(f"Decomposing: {g['name']}…")
        def _do():
            matrix = _strat.get_matrix()
            goal   = matrix.get_goal(g["id"])
            if not goal:
                return []
            tasks = matrix.decompose_goal(g["id"])
            matrix.generate_key_results(g["id"])
            return tasks
        def _done(tasks):
            self.status.showMessage(f"Decomposed into {len(tasks)} tasks")
            self._strat_refresh()
        self._run_in_thread(_do, on_done=_done)

    def _strat_critical(self):
        if not STRAT_OK:
            return
        vec = _strat.get_critical_vector()
        if vec:
            self.strat_detail.setPlainText(
                f"CRITICAL VECTOR\n\n"
                f"Goal:     {vec['goal']}\n"
                f"Task:     {vec['task']}\n"
                f"Priority: {vec['priority']}\n"
                f"Effort:   {vec['effort_h']}h\n"
                f"Progress: {vec['completion']}"
            )
        else:
            self.strat_detail.setPlainText("No active goals or all tasks complete.")

    def _strat_eisenhower(self):
        if not STRAT_OK:
            return
        q = _strat.get_matrix().eisenhower_sort()
        lines = []
        for quadrant, tasks in q.items():
            if tasks:
                label = quadrant.replace("_", " ").upper()
                lines.append(f"── {label} ──")
                for t in tasks[:5]:
                    lines.append(f"  [{t['goal'][:20]}] {t['task'][:40]}")
                lines.append("")
        self.strat_detail.setPlainText("\n".join(lines) or "No tasks in any quadrant.")

    def _strat_spawn_agent(self):
        task = self.strat_goal_input.text().strip() or "Review active goals and surface the top priority action"
        if not PROC_OK:
            return
        def _on_result(r):
            QTimer.singleShot(0, lambda: self.strat_detail.append(
                f"\n[StrategyAgent {r['agent_id']}]\n{r['output'][:500]}"
            ))
        _proc.spawn("StrategyAgent", task, callback=_on_result)
        self.status.showMessage("StrategyAgent spawned…")

    # ─────────────────────────────────────────────────────────────────────────
    # QUANTUM CONTEXT TAB — Probabilistic State Display
    # ─────────────────────────────────────────────────────────────────────────

    def _build_quantum_tab(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)

        hdr = QLabel("QUANTUM CONTEXT  —  PROBABILISTIC INTENT STATE")
        hdr.setStyleSheet("color:#58a6ff; font-weight:bold; font-size:12px; "
                          "letter-spacing:2px; padding-bottom:8px;")
        lay.addWidget(hdr)

        # Entropy/confidence display
        self._quantum_conf_lbl = QLabel("Confidence: —  |  Entropy: —")
        self._quantum_conf_lbl.setStyleSheet(
            "background:#161b22; color:#bc8cff; padding:8px; font-size:12px; "
            "border:1px solid #21262d;"
        )
        lay.addWidget(self._quantum_conf_lbl)

        # Observe input
        obs_row = QHBoxLayout()
        self.quantum_input = QLineEdit()
        self.quantum_input.setPlaceholderText("Enter text to observe quantum state…")
        self.quantum_input.returnPressed.connect(self._quantum_observe)
        obs_btn = QPushButton("Observe")
        obs_btn.clicked.connect(self._quantum_observe)
        collapse_btn = QPushButton("Collapse")
        collapse_btn.clicked.connect(self._quantum_collapse)
        refresh_btn  = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._quantum_refresh)
        obs_row.addWidget(self.quantum_input)
        obs_row.addWidget(obs_btn)
        obs_row.addWidget(collapse_btn)
        obs_row.addWidget(refresh_btn)
        lay.addLayout(obs_row)

        # Superposition display
        split = QSplitter()

        lw  = QWidget()
        ll  = QVBoxLayout(lw)
        ll.setContentsMargins(0, 0, 0, 0)
        lbl2 = QLabel("SUPERPOSITION"); lbl2.setObjectName("section")
        ll.addWidget(lbl2)
        self.quantum_super_list = QListWidget()
        ll.addWidget(self.quantum_super_list)

        rw  = QWidget()
        rl  = QVBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        lbl3 = QLabel("COLLAPSE HISTORY"); lbl3.setObjectName("section")
        rl.addWidget(lbl3)
        self.quantum_history = QTextEdit()
        self.quantum_history.setReadOnly(True)
        rl.addWidget(self.quantum_history)

        split.addWidget(lw)
        split.addWidget(rw)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, stretch=1)

        # Entanglement display
        lbl4 = QLabel("ENTANGLEMENT REGISTRY"); lbl4.setObjectName("section")
        lay.addWidget(lbl4)
        self.entangle_lbl = QLabel("—")
        self.entangle_lbl.setStyleSheet(
            "color:#8b949e; font-size:11px; padding:4px;"
        )
        lay.addWidget(self.entangle_lbl)

        self.tabs.addTab(w, "Quantum Context")

    def _quantum_observe(self):
        text = self.quantum_input.text().strip()
        if not text or not QUANTUM_OK:
            if not QUANTUM_OK:
                self.status.showMessage("quantum.py not loaded")
            return
        _quantum.observe(text)
        self._quantum_refresh()
        self.quantum_input.clear()

    def _quantum_collapse(self):
        if not QUANTUM_OK:
            return
        intent = _quantum.collapse()
        self.status.showMessage(f"Collapsed to: {intent}")
        self._quantum_refresh()

    def _quantum_refresh(self):
        if not QUANTUM_OK:
            self._quantum_conf_lbl.setText("quantum.py not loaded")
            return
        state = _quantum.get_state()
        sup   = _quantum.get_superposition()
        conf  = _quantum.get_confidence()
        s     = state.to_dict()

        self._quantum_conf_lbl.setText(
            f"Confidence: {conf:.0%}  |  Entropy: {s['entropy']:.3f}  |  "
            f"Hypotheses: {len(sup)}  |  History: {s['history_len']}"
        )

        self.quantum_super_list.clear()
        for h in sup:
            pct  = h["probability"]
            bar  = "█" * int(pct * 20) + "░" * (20 - int(pct * 20))
            item = QListWidgetItem(f"{pct:.0%} {bar} {h['intent']}")
            item.setData(Qt.ItemDataRole.UserRole, h)
            self.quantum_super_list.addItem(item)

        history = state.get_history(10)
        lines   = []
        for h in reversed(history):
            lines.append(
                f"[{h['ts'][:19]}] {h['input'][:30]} → {h['intent']} "
                f"(conf={h['confidence']:.0%} entropy={h['entropy']:.2f})"
            )
        self.quantum_history.setPlainText("\n".join(lines))

        # Entanglement
        try:
            reg     = _quantum.get_registry()
            if sup:
                top_intent = sup[0]["intent"]
                related    = reg.get_entangled(top_intent, top_n=3)
                if related:
                    self.entangle_lbl.setText(
                        f"Entangled with '{top_intent}': " +
                        "  |  ".join(f"{t} ({c}×)" for t, c in related)
                    )
        except Exception:
            pass

    def _build_pyramid_compartment_tab(self):
        """PYRAMID — cognitive OS coordinator (5 Rooms + IntentRouter + MemoryCore).

        Operator hands free-text input or picks a Room directly. The View calls
        PyramidCompartment Model API on a worker thread; result lands in the
        output panel with a structured step trace alongside.
        """
        from PyQt6.QtWidgets import QComboBox  # local import — keep top-level lean

        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)

        hdr = QLabel("PYRAMID COMPARTMENT  —  COGNITIVE OS COORDINATOR")
        hdr.setStyleSheet(
            "color:#58a6ff; font-weight:bold; font-size:12px;"
            " letter-spacing:2px; padding-bottom:8px;"
        )
        lay.addWidget(hdr)

        sub = QLabel(
            "Five Rooms · Analysis · Reasoning · Sandbox · Document · Memory   "
            "│   IntentRouter chooses if room is left on AUTO."
        )
        sub.setStyleSheet("color:#8b949e; font-size:11px; padding-bottom:6px;")
        lay.addWidget(sub)

        # Room selector + execute row
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Room:"))
        self._py_room = QComboBox()
        self._py_room.addItem("AUTO (router)", "")
        self._py_room.addItem("Analysis",  "analysis")
        self._py_room.addItem("Reasoning", "reasoning")
        self._py_room.addItem("Sandbox",   "sandbox")
        self._py_room.addItem("Document",  "document")
        self._py_room.addItem("Memory",    "memory")
        self._py_room.setStyleSheet(
            "background:#0d1117; color:#c9d1d9; padding:4px;"
            " border:1px solid #30363d;"
        )
        ctrl.addWidget(self._py_room, 1)

        self._py_exec_btn = QPushButton("▲ EXECUTE")
        self._py_exec_btn.setStyleSheet(
            "background:#1f6feb; color:#fff; font-weight:bold;"
            " padding:6px 12px; border-radius:3px;"
        )
        self._py_exec_btn.clicked.connect(self._py_execute)
        ctrl.addWidget(self._py_exec_btn)

        self._py_recall_btn = QPushButton("↻ RECALL")
        self._py_recall_btn.setToolTip(
            "Search past Pyramid tasks by query (uses MemoryCore)."
        )
        self._py_recall_btn.clicked.connect(self._py_recall)
        ctrl.addWidget(self._py_recall_btn)
        lay.addLayout(ctrl)

        # Input
        in_lbl = QLabel("Input:")
        in_lbl.setStyleSheet("color:#8b949e; font-size:11px;")
        lay.addWidget(in_lbl)
        self._py_input = QTextEdit()
        self._py_input.setFixedHeight(110)
        self._py_input.setPlaceholderText(
            "Free text → router picks a Room. Or pick a Room above:\n"
            "  • Sandbox needs prefix:   python:print(2**16)   |   shell:dir\n"
            "  • Document needs JSON:    {\"format\":\"ar_25_50\","
            "\"recipient\":\"Operator\",\"subject\":\"…\",\"paragraphs\":[\"…\"]}\n"
            "  • Memory takes a free-text query"
        )
        self._py_input.setStyleSheet(
            "background:#0d1117; color:#c9d1d9; border:1px solid #30363d;"
            " font-family:Consolas; font-size:11px;"
        )
        lay.addWidget(self._py_input)

        # Splitter: Output (large) | Steps trace (small)
        from PyQt6.QtWidgets import QSplitter as _QSplit
        split = _QSplit(Qt.Orientation.Horizontal)

        out_w = QWidget()
        out_l = QVBoxLayout(out_w)
        out_l.setContentsMargins(0, 0, 0, 0)
        out_lbl = QLabel("Output (YIELDCAST):")
        out_lbl.setStyleSheet("color:#8b949e; font-size:11px;")
        out_l.addWidget(out_lbl)
        self._py_output = QTextEdit()
        self._py_output.setReadOnly(True)
        self._py_output.setStyleSheet(
            "background:#010409; color:#c9d1d9; border:1px solid #30363d;"
            " font-family:Consolas; font-size:11px;"
        )
        out_l.addWidget(self._py_output)
        split.addWidget(out_w)

        trace_w = QWidget()
        trace_l = QVBoxLayout(trace_w)
        trace_l.setContentsMargins(0, 0, 0, 0)
        trace_lbl = QLabel("Step trace (CHARGELOG):")
        trace_lbl.setStyleSheet("color:#8b949e; font-size:11px;")
        trace_l.addWidget(trace_lbl)
        self._py_steps = QListWidget()
        self._py_steps.setStyleSheet(
            "background:#0d1117; color:#7ee787; border:1px solid #30363d;"
            " font-family:Consolas; font-size:11px;"
        )
        trace_l.addWidget(self._py_steps)
        self._py_status = QLabel(
            "Ready. Pyramid initialises on first execute."
        )
        self._py_status.setStyleSheet("color:#8b949e; font-size:10px;")
        trace_l.addWidget(self._py_status)
        split.addWidget(trace_w)
        split.setSizes([900, 360])
        lay.addWidget(split, 1)

        self._py_compartment = None  # lazy-init on first execute
        self.tabs.addTab(w, "▲ Pyramid")
        self._py_tab_index = self.tabs.indexOf(w)

    def _py_get_compartment(self):
        if self._py_compartment is None:
            try:
                import pyramid_compartment as _pc
                self._py_compartment = _pc.PyramidCompartment(
                    project_root=str(Path(__file__).parent),
                )
            except Exception as exc:
                self._py_status.setText(f"PyramidCompartment init failed: {exc}")
                return None
        return self._py_compartment

    def _py_execute(self):
        text = self._py_input.toPlainText().strip()
        if not text:
            self._py_status.setText("input is empty")
            return
        pc = self._py_get_compartment()
        if pc is None:
            return
        room_kind = self._py_room.currentData() or ""
        self._py_status.setText("Executing…")
        self._py_exec_btn.setEnabled(False)
        self._busy(True)

        def fetch():
            if room_kind:
                return pc.enter(room_kind, text)
            return pc.route(text)

        def done(task):
            self._busy(False)
            self._py_exec_btn.setEnabled(True)
            if isinstance(task, dict) and "error" in task:
                self._py_status.setText(f"error: {task['error']}")
                return
            self._py_steps.clear()
            for i, s in enumerate(task.steps, start=1):
                self._py_steps.addItem(f"{i:>2}. [{s.label}] {s.detail}")
            self._py_output.setPlainText(task.output or "(no output)")
            self._py_status.setText(
                f"Task {task.task_id} · room={task.room} · status={task.status}"
            )

        self._run_in_thread(fetch, on_done=done)

    def _py_recall(self):
        query = self._py_input.toPlainText().strip()
        pc = self._py_get_compartment()
        if pc is None:
            return
        rows = pc.memory.recall(query, limit=20)
        self._py_steps.clear()
        if not rows:
            self._py_output.setPlainText("MemoryCore: no matching tasks.")
            self._py_status.setText("0 tasks recalled")
            return
        for r in rows:
            self._py_steps.addItem(
                f"[{r['room']}/{r['status']}] {r['id']} · {r['started_at']}"
            )
        body = "\n\n---\n\n".join(
            f"# {r['id']}  ·  {r['room']}\n{r['output_preview']}" for r in rows
        )
        self._py_output.setPlainText(body)
        self._py_status.setText(f"{len(rows)} tasks recalled")

    def _build_simcore_tab(self):
        """SIMCORE — deterministic cognitive simulation.

        Strict layer separation per spec:
          Director (cognitive)  → proposes events from operator text
          Engine (simulation)   → validates, applies, snapshots
          Renderer (projection) → ASCII visual + audio cue + texture slugs
        UI never bypasses this chain.
        """
        from PyQt6.QtWidgets import QSplitter as _QSplit

        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)

        hdr = QLabel("SIMCORE  -  DETERMINISTIC COGNITIVE SIMULATION ENGINE")
        hdr.setStyleSheet(
            "color:#58a6ff; font-weight:bold; font-size:12px;"
            " letter-spacing:2px; padding-bottom:4px;"
        )
        lay.addWidget(hdr)
        sub = QLabel(
            "Director PROPOSES events  ->  Engine VALIDATES + SNAPSHOTS  ->  "
            "Renderer PROJECTS state.  AI never mutates."
        )
        sub.setStyleSheet("color:#8b949e; font-size:11px; padding-bottom:6px;")
        lay.addWidget(sub)

        # Status row
        self._sim_status = QLabel("(not bootstrapped)")
        self._sim_status.setStyleSheet(
            "background:#161b22; color:#7ee787; padding:6px;"
            " border:1px solid #30363d; font-family:Consolas; font-size:11px;"
        )
        lay.addWidget(self._sim_status)

        # Action row
        ctrl = QHBoxLayout()
        self._sim_input = QLineEdit()
        self._sim_input.setPlaceholderText(
            "Operator command - e.g. 'go down', 'take lantern', "
            "'light lantern', 'unlock rune door'"
        )
        self._sim_input.returnPressed.connect(self._sim_propose_and_tick)
        self._sim_input.setStyleSheet(
            "background:#0d1117; color:#c9d1d9; padding:5px;"
            " border:1px solid #30363d; font-family:Consolas;"
        )
        ctrl.addWidget(self._sim_input, 1)

        self._sim_tick_btn = QPushButton("> TICK")
        self._sim_tick_btn.setStyleSheet(
            "background:#1f6feb; color:#fff; font-weight:bold;"
            " padding:6px 12px; border-radius:3px;"
        )
        self._sim_tick_btn.clicked.connect(self._sim_propose_and_tick)
        ctrl.addWidget(self._sim_tick_btn)

        self._sim_demo_btn = QPushButton("DEMO")
        self._sim_demo_btn.setToolTip("Bootstrap demo world (idempotent).")
        self._sim_demo_btn.clicked.connect(self._sim_bootstrap)
        ctrl.addWidget(self._sim_demo_btn)

        self._sim_verify_btn = QPushButton("VERIFY")
        self._sim_verify_btn.setToolTip("Hash-verify the snapshot chain.")
        self._sim_verify_btn.clicked.connect(self._sim_verify)
        ctrl.addWidget(self._sim_verify_btn)

        lay.addLayout(ctrl)

        # Split: visual map | text projection + history
        split = _QSplit(Qt.Orientation.Horizontal)

        left_w = QWidget()
        left_l = QVBoxLayout(left_w)
        left_l.setContentsMargins(0, 0, 0, 0)
        l_lbl = QLabel("VISUAL projection (room graph):")
        l_lbl.setStyleSheet("color:#8b949e; font-size:11px;")
        left_l.addWidget(l_lbl)
        self._sim_visual = QTextEdit()
        self._sim_visual.setReadOnly(True)
        self._sim_visual.setStyleSheet(
            "background:#010409; color:#7ee787; border:1px solid #30363d;"
            " font-family:Consolas; font-size:12px;"
        )
        left_l.addWidget(self._sim_visual)
        split.addWidget(left_w)

        right_w = QWidget()
        right_l = QVBoxLayout(right_w)
        right_l.setContentsMargins(0, 0, 0, 0)
        r_lbl = QLabel("TEXT + AUDIO + Director frame:")
        r_lbl.setStyleSheet("color:#8b949e; font-size:11px;")
        right_l.addWidget(r_lbl)
        self._sim_text = QTextEdit()
        self._sim_text.setReadOnly(True)
        self._sim_text.setStyleSheet(
            "background:#010409; color:#c9d1d9; border:1px solid #30363d;"
            " font-family:Consolas; font-size:11px;"
        )
        right_l.addWidget(self._sim_text)

        h_lbl = QLabel("Snapshot chain (head -> earliest):")
        h_lbl.setStyleSheet("color:#8b949e; font-size:11px;")
        right_l.addWidget(h_lbl)
        self._sim_chain = QListWidget()
        self._sim_chain.setStyleSheet(
            "background:#0d1117; color:#bc8cff; border:1px solid #30363d;"
            " font-family:Consolas; font-size:10px;"
        )
        self._sim_chain.itemDoubleClicked.connect(self._sim_rollback_selected)
        right_l.addWidget(self._sim_chain)
        right_l.addWidget(QLabel(
            "(double-click a snapshot to roll back the branch)"
        ))
        split.addWidget(right_w)
        split.setSizes([700, 600])
        lay.addWidget(split, 1)

        self._sim_core = None
        self._sim_director = None
        self._sim_renderer = None
        self.tabs.addTab(w, "[+] SimCore")
        self._sim_tab_index = self.tabs.indexOf(w)

    def _sim_get(self):
        if self._sim_core is None:
            try:
                import simcore as _sc
                import simcore_director as _scd
                import simcore_render as _scr
                self._sim_core = _sc.SimCore()
                self._sim_director = _scd.CognitiveCore()
                self._sim_renderer = _scr.Renderer()
                self._sim_core.bootstrap()

                # ── Sensory Engine ──
                if SENSORY_OK:
                    self._sensory_engine = _sensory.default_engine()
                else:
                    self._sensory_engine = None

            except Exception as exc:
                self._sim_status.setText(f"SimCore init failed: {exc}")
                return None, None, None
        return self._sim_core, self._sim_director, self._sim_renderer

    def _sim_bootstrap(self):
        sc, _, _ = self._sim_get()
        if sc is None:
            return
        sc.bootstrap()
        self._sim_refresh(last_tick=None, status="Demo world bootstrapped.")

    def _sim_propose_and_tick(self):
        text = self._sim_input.text().strip()
        if not text:
            return
        sc, cc, _ = self._sim_get()
        if sc is None:
            return
        world = sc.current_world()
        decision, events, _rule = cc.propose_for_input(world, text)
        if not events:
            self._sim_status.setText(
                f"Director made no proposal (target={decision.target}, "
                f"hint={decision.action_hint}). Try: go <dir> | take <item> | "
                f"light <item> | unlock <fixture>."
            )
            return
        # The Director proposes; the Engine validates and applies.
        ev = events[0]
        action = {"actor": ev.actor, "action": ev.action,
                  "target": ev.target, "payload": ev.payload}
        tick = sc.tick(action)
        self._sim_input.clear()
        status = (f"OK  -  {tick.event.action} -> snap {tick.snapshot_id}"
                  if tick.accepted
                  else f"REJECTED  -  {tick.reason}")
        self._sim_refresh(last_tick=tick, status=status)

    def _sim_verify(self):
        sc, _, _ = self._sim_get()
        if sc is None:
            return
        ok, reason = sc.verify()
        self._sim_status.setText(
            f"chain integrity: ok={ok} reason={reason}"
        )

    def _sim_rollback_selected(self, item):
        sc, _, _ = self._sim_get()
        if sc is None:
            return
        snap_id = item.data(Qt.ItemDataRole.UserRole)
        if not snap_id:
            return
        sc.rollback_to(snap_id)
        self._sim_refresh(last_tick=None,
                          status=f"rolled back to snapshot {snap_id}")

    def _sim_refresh(self, last_tick=None, status: str = ""):
        sc, cc, rdr = self._sim_get()
        if sc is None:
            return
        world = sc.current_world()

        # ── Multi-modal Rendering ──
        if SENSORY_OK and getattr(self, '_sensory_engine', None):
            # Frame production
            s_frame = self._sensory_engine.frame(
                world,
                last_event=last_tick.event if last_tick else None,
                percept_or_state=getattr(cc, 'percept', None)
            )
            visual_data = s_frame.visual
            audio_cue   = s_frame.audio_cue
            ambient     = s_frame.ambient
            modulation  = s_frame.modulation
        else:
            # Fallback
            proj = rdr.project_all(world, last_tick)
            visual_data = proj.visual
            audio_cue   = proj.audio_cue
            ambient     = proj.ambient
            modulation  = {}

        self._sim_visual.setPlainText(str(visual_data))
        frame_text = cc.director.frame(world, last_tick.__dict__ if last_tick else None)

        mod_str = " | ".join([f"{k}:{v:.2f}" for k, v in modulation.items()])
        body = (
            f"AUDIO cue:    {audio_cue}\n"
            f"AUDIO amb:    {ambient}\n"
            f"EMOTION mod:  {mod_str}\n\n"
            f"--- DIRECTOR FRAME (read-only) ---\n{frame_text}"
        )
        self._sim_text.setPlainText(body)

        # Chain history
        self._sim_chain.clear()
        for snap in reversed(sc.store.chain()):
            label = (f"{snap.id}  -  parent={snap.parent_id[:8]}  "
                     f"-  hash={snap.world_hash[:10]}")
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, snap.id)
            self._sim_chain.addItem(it)

        if status:
            self._sim_status.setText(status)

    def _busy(self, on: bool):
        if on:
            self.progress.setRange(0, 0)
            self.progress.show()
        else:
            self.progress.hide()

    def _refresh_status(self):
        wp = get_won_pipeline()

        # Check daemon notifications
        notes = get_daemon_notifications(unread_only=True)
        if notes:
            latest = notes[-1]
            title  = latest.get("title", "WON")
            body   = latest.get("body", "")[:60]
            pri    = latest.get("priority", "normal")
            color  = "#f85149" if pri == "high" else "#f0883e"
            self.status.setStyleSheet(f"QStatusBar {{ background:#161b22; color:{color}; }}")
            self.status.showMessage(f"🔔 WON: {title} — {body}  (click to dismiss)")
            mark_notifications_read()
            return

        self.status.setStyleSheet("")

        # Daemon status
        daemon = get_daemon_status()
        daemon_str = ""
        if daemon:
            daemon_str = (
                f" · Daemon: ✓ "
                f"C#{daemon.get('cognition_count',0)} "
                f"R#{daemon.get('research_count',0)}"
            )

        if wp:
            try:
                s = wp.stats()
                # Check LM Studio
                lms_str = ""
                if LMS_OK:
                    try:
                        lms_status = _lms.status()
                        if lms_status.get("lm_studio"):
                            lms_str = f" · LMStudio ✓ {lms_status.get('active_model','')[:20]}"
                        else:
                            lms_str = " · LMStudio ✗"
                    except Exception:
                        pass

                self.status.showMessage(
                    f"WON: {s.get('total_entries', 0)} entries · "
                    f"Ollama {'✓' if ollama_available() else '✗'}"
                    f"{lms_str} · "
                    f"Vault: {os.environ.get('WON_VAULT', 'not set')}"
                    f"{daemon_str}"
                )
                return
            except Exception: pass
        self.status.showMessage(f"Pipeline offline — set WON_PATH env var{daemon_str}")

    def _run_in_thread(self, fn, *args, on_done=None):
        w = Worker(fn, *args)
        if on_done:
            w.result.connect(on_done)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    # ── Memory tab actions ───────────────────────────────────

    def refresh_history(self):
        self.list_w.clear()
        if not HISTORY_DIR.is_dir(): return
        for p in sorted(HISTORY_DIR.glob("*.txt"), key=lambda x: x.stat().st_mtime, reverse=True):
            it = QListWidgetItem(f"📄  {p.name}")
            it.setData(Qt.ItemDataRole.UserRole, str(p))
            self.list_w.addItem(it)

    def load_won_memory_feed(self):
        wp = get_won_pipeline()
        if not wp:
            self.status.showMessage("Pipeline not loaded — check WON_PATH")
            return
        self._busy(True)
        def fetch():
            return wp.recall(limit=60)
        def done(entries):
            self._busy(False)
            self.list_w.clear()
            if isinstance(entries, dict) and "error" in entries:
                self.status.showMessage(f"WON error: {entries['error']}")
                return
            for e in entries:
                ts      = (e.get("timestamp") or "")[:19]
                mode    = e.get("mode", "?")
                preview = (e.get("content") or "")[:80].replace("\n", " ")
                it = QListWidgetItem(f"🧠  [{mode}]  {ts}  {preview}")
                it.setData(Qt.ItemDataRole.UserRole, {"text": e.get("content", "")})
                self.list_w.addItem(it)
            self.status.showMessage(f"WON memory: {len(entries)} entries loaded")
        self._run_in_thread(fetch, on_done=done)

    def load_ground_state(self):
        pc = get_perception()
        if not pc:
            self.ground_text.setPlainText("Perception layer offline — check perception.py location")
            return
        self._busy(True)
        def fetch():
            return pc.get_ground_state(max_chars=3000)
        def done(text):
            self._busy(False)
            self.ground_text.setPlainText(text if isinstance(text, str) else str(text))
            self.tabs.setCurrentIndex(1)
        self._run_in_thread(fetch, on_done=done)

    def peek_ground(self):
        pc = get_perception()
        if not pc:
            self.status.showMessage("Perception offline")
            return
        ctx = pc.get_compressed_context(max_chars=800)
        self.detail.setPlainText(ctx)
        self.tabs.setCurrentIndex(0)

    def open_vault(self):
        vault = os.environ.get("WON_VAULT", str(Path.home() / "Documents" / "WON-Vault"))
        if os.path.exists(vault):
            os.startfile(vault)
        else:
            self.status.showMessage(f"Vault not found: {vault}")

    def clip_active_chat(self):
        from PyQt6.QtWidgets import QApplication as _QApp
        txt = _QApp.clipboard().text()
        if not txt.strip():
            self.status.showMessage("Clipboard empty — copy your chat first")
            return
        data = {"platform": "Manual Clip", "summary": txt, "messageCount": 0}
        wp = get_won_pipeline()
        if wp:
            self._busy(True)
            def process():
                result = wp.process(data)
                # note_builder: richer structured notes
                if NB_OK and result.get("won_indexed"):
                    try:
                        ts_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
                        sid    = f"CLIP-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                        _nb.build_history_note(sid, data["platform"], data["summary"], 0, ts_str)
                        _nb.build_brief_note(sid, data["platform"], data["summary"], 0, ts_str)
                        result["note_builder_used"] = True
                    except Exception:
                        pass
                return result
            def done(r):
                self._busy(False)
                self.refresh_history()
                self.status.showMessage(
                    f"Clipped — WON: {'✓' if r.get('won_indexed') else '✗'} · "
                    f"Palace: {'✓' if r.get('palace_indexed') else '✗'} · "
                    f"Brief: {'✓' if r.get('brief_path') else '✗'} · "
                    f"Notes: {'✓' if r.get('note_builder_used') else '—'}"
                )
            self._run_in_thread(process, on_done=done)
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            f  = HISTORY_DIR / f"{ts}_ManualClip.txt"
            f.write_text(txt, encoding="utf-8")
            self.refresh_history()
            self.status.showMessage("Saved to history (pipeline offline)")

    def run_search(self):
        q = self.search_input.text().strip()
        if not q: return
        wp = get_won_pipeline()
        if not wp:
            self.status.showMessage("Pipeline offline")
            return
        self._busy(True)
        self.list_w.clear()
        def search():
            hits = wp.search(q, limit=12)
            # AI synthesis
            summary = None
            if hits:
                ctx     = "\n\n".join(h.get("text","")[:400] for h in hits[:3])
                prompt  = f"Answer concisely for DBOMBCENTRAL context:\n{q}\n\nContext:\n{ctx}"
                try:
                    r = requests.post(OLLAMA_URL,
                        json={"model": DEFAULT_MODEL, "prompt": prompt, "stream": False},
                        timeout=15)
                    summary = r.json().get("response")
                except Exception: pass
            return {"hits": hits, "summary": summary}
        def done(res):
            self._busy(False)
            if isinstance(res, dict) and "error" in res:
                self.status.showMessage(f"Search error: {res['error']}")
                return
            hits    = res.get("hits", [])
            summary = res.get("summary")
            if summary:
                it = QListWidgetItem("💡  AI SYNTHESIS")
                it.setData(Qt.ItemDataRole.UserRole, {"text": summary})
                it.setBackground(QColor("#1a2a1a"))
                self.list_w.addItem(it)
            for h in hits:
                pct = int(float(h.get("similarity", 0)) * 100)
                src = h.get("source_file", h.get("source", "?"))
                it  = QListWidgetItem(f"🧠  {pct}%  {src}")
                it.setData(Qt.ItemDataRole.UserRole, {"text": h.get("text", "")})
                self.list_w.addItem(it)
            self.status.showMessage(f"Search '{q}' — {len(hits)} results")
        self._run_in_thread(search, on_done=done)

    def sync_all_to_obsidian(self):
        wp = get_won_pipeline()
        if not wp:
            self.status.showMessage("Pipeline offline — cannot sync")
            return
        self._busy(True)
        def sync():
            count = 0
            for f in sorted(HISTORY_DIR.glob("*.txt"), key=os.path.getmtime):
                try:
                    r = wp.process_file(str(f))
                    if r.get("won_indexed") or r.get("palace_indexed"):
                        count += 1
                except Exception: pass
            return count
        def done(n):
            self._busy(False)
            self.status.showMessage(f"Sync complete — {n} files routed through pipeline")
            self._refresh_status()
        self._run_in_thread(sync, on_done=done)

    def copy_for_cursor(self):
        text = self.detail.toPlainText()
        if text:
            from PyQt6.QtWidgets import QApplication as _QApp
            _QApp.clipboard().setText(f"/* AI CONTEXT */\n/*\n{text}\n*/\n\n// Action:")
            self.status.showMessage("Copied for Cursor")

    def attach_to_browser(self):
        text = self.detail.toPlainText()
        if text:
            NativeBridge.send_to_browser({"type": "INJECT_TEXT", "text": text})
            self.status.showMessage("Attached to browser chat")

    def security_audit(self):
        text = self.detail.toPlainText()
        if not text: return
        self._busy(True)
        def audit():
            prompt = f"{CYBER_ANALYST_PROMPT}\n\nCONTEXT:\n{text[:3000]}"
            try:
                r = requests.post(OLLAMA_URL,
                    json={"model": DEFAULT_MODEL, "prompt": prompt, "stream": False},
                    timeout=30)
                return r.json().get("response", "No response")
            except Exception as e:
                return f"Audit offline: {e}"
        def done(report):
            self._busy(False)
            self.detail.setPlainText(f"🛡️ SECURITY AUDIT\n\n{report}\n\n───\n\nORIGINAL:\n{text}")
        self._run_in_thread(audit, on_done=done)

    def run_reflection(self):
        self._busy(True)
        def reflect():
            time.sleep(1)
            return {
                "title": "Async History Load",
                "desc":  "Load list items in batches to prevent UI freeze on large vaults",
                "old":   "# sync load all at once",
                "new":   "# async batch loader — QThread",
            }
        def done(prop):
            self._busy(False)
            from PyQt6.QtWidgets import QListWidgetItem
            it = QListWidgetItem(f"⚡  PENDING: {prop['title']}")
            it.setData(Qt.ItemDataRole.UserRole, prop)
            it.setForeground(QColor("#f0883e"))
            self.opt_list.addItem(it)
            self.status.showMessage("Reflection complete — 1 proposal found")
        self._run_in_thread(reflect, on_done=done)


# ============================================================
# FLOATING HINT WIDGET
# ============================================================

# ============================================================
# THEMES
# ============================================================

THEMES = {
    "Dark": {
        "bg": "#0d1117", "bg2": "#161b22", "bg3": "#010409",
        "border": "#1f6feb", "accent": "#58a6ff", "accent2": "#3fb950",
        "text": "#c9d1d9", "text2": "#8b949e", "warn": "#f0883e",
        "header_bg": "#0d2137",
    },
    "Cyber": {
        "bg": "#0d0d1a", "bg2": "#1a0033", "bg3": "#050510",
        "border": "#ff00ff", "accent": "#ff00ff", "accent2": "#00ffcc",
        "text": "#ff99ff", "text2": "#cc66ff", "warn": "#ffff00",
        "header_bg": "#0a0020",
    },
    "Matrix": {
        "bg": "#000000", "bg2": "#001100", "bg3": "#000a00",
        "border": "#00ff41", "accent": "#00ff41", "accent2": "#00cc33",
        "text": "#00ff41", "text2": "#006622", "warn": "#ffff00",
        "header_bg": "#000800",
    },
    "Light": {
        "bg": "#ffffff", "bg2": "#f6f8fa", "bg3": "#ffffff",
        "border": "#0366d6", "accent": "#0366d6", "accent2": "#28a745",
        "text": "#24292e", "text2": "#586069", "warn": "#e36209",
        "header_bg": "#e1e4e8",
    },
    "Steel": {
        "bg": "#1c2333", "bg2": "#22304a", "bg3": "#0d1526",
        "border": "#89b4fa", "accent": "#89b4fa", "accent2": "#a6e3a1",
        "text": "#cdd6f4", "text2": "#9399b2", "warn": "#fab387",
        "header_bg": "#181c2e",
    },
}


# ── Active theme (global — shared across all windows) ──────────────────────
_ACTIVE_THEME_KEY = "Dark"
_APP_INSTANCE     = None   # set at AIMonitorApp.__init__

def get_active_theme() -> dict:
    return THEMES.get(_ACTIVE_THEME_KEY, THEMES["Dark"])

def apply_app_theme(theme_key: str, app_instance=None):
    """
    Apply a theme across ALL open windows instantly.
    Called by WON when it generates or selects a theme.
    """
    global _ACTIVE_THEME_KEY, _APP_INSTANCE
    if theme_key not in THEMES and theme_key != "__custom__":
        return False
    _ACTIVE_THEME_KEY = theme_key
    inst = app_instance or _APP_INSTANCE
    if not inst:
        return False
    t = THEMES.get(theme_key, THEMES["Dark"])
    style = _build_theme_style(t)
    inst.app.setStyleSheet(style)
    # Update all open windows
    for win in [inst.dashboard, getattr(inst, "floating_widget", None)]:
        if win:
            try: win.setStyleSheet(style)
            except Exception: pass
    return True

def register_custom_theme(name: str, colors: dict) -> str:
    """
    Register a WON-generated custom theme.
    colors: dict with keys bg, bg2, bg3, border, accent, accent2, text, text2, warn, header_bg
    Returns theme key.
    """
    key = name.replace(" ", "_")
    THEMES[key] = colors
    return key

def _build_theme_style(t: dict) -> str:
    return f"""
    QMainWindow, QDialog, QWidget {{
        background-color: {t['bg']}; color: {t['text']};
        font-family: 'Consolas','Courier New',monospace; font-size:13px;
    }}
    QTabWidget::pane  {{ border:1px solid {t['border']}; background:{t['bg']}; }}
    QTabBar::tab      {{ background:{t['bg2']}; padding:7px 16px; border:1px solid {t['border']}; color:{t['text2']}; }}
    QTabBar::tab:selected {{ background:{t['bg']}; color:{t['accent']}; border-bottom:2px solid {t['accent']}; }}
    QPushButton {{
        background-color:{t['bg2']}; border:1px solid {t['border']};
        border-radius:4px; padding:5px 12px; color:{t['text']};
    }}
    QPushButton:hover  {{ background-color:{t['border']}; color:{t['bg']}; }}
    QListWidget, QTextEdit, QLineEdit {{
        background-color:{t['bg3']}; border:1px solid {t['border']};
        border-radius:4px; padding:5px; color:{t['text']};
    }}
    QListWidget::item:selected {{ background:{t['accent']}; color:{t['bg']}; }}
    QSplitter::handle {{ background:{t['border']}; width:1px; }}
    QStatusBar {{ background:{t['bg2']}; color:{t['text2']}; font-size:11px; }}
    QLabel#section {{ color:{t['accent']}; font-weight:bold; font-size:11px; letter-spacing:1px; }}
    QScrollBar:vertical {{ background:{t['bg2']}; width:8px; border-radius:4px; }}
    QScrollBar::handle:vertical {{ background:{t['border']}; border-radius:4px; }}
    """


# ============================================================
# MANIFEST WINDOW — Full visual of all AI activity
# ============================================================

class ManifestWindow(QMainWindow):
    """
    The Manifest pops Claude into the room with full visibility:
    - Live chat history from all sources
    - Memory feed color-coded by source
    - Ground state — what both AIs see
    - Recent Obsidian notes preview
    - Direct two-way chat with WON
    Everything is visible. Everything is logged. WON knows it.
    """

    def __init__(self, parent_app, theme: dict):
        super().__init__()
        self.parent_app   = parent_app
        self._theme       = theme
        self._workers     = []
        self._chat_log    = []
        self._timer       = QTimer()
        self._timer.timeout.connect(self._refresh_all)
        self.setWindowTitle("AI Monitor — MANIFEST")
        self.setMinimumSize(1200, 780)
        self._apply_theme(theme)
        self._init_ui()
        self._timer.start(6000)
        QTimer.singleShot(300, self._refresh_all)

    def _apply_theme(self, t: dict):
        self._theme = t
        self.setStyleSheet(_build_theme_style(t) + f"""
            QMainWindow {{
                border: 3px solid {t['accent']};
            }}
        """)

    def closeEvent(self, ev):
        self._timer.stop()
        super().closeEvent(ev)

    def _run_bg(self, fn, *args, on_done=None):
        w = Worker(fn, *args)
        if on_done: w.result.connect(on_done)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _init_ui(self):
        t   = self._theme
        cen = QWidget()
        self.setCentralWidget(cen)
        root = QVBoxLayout(cen)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{t['header_bg']}; border-bottom:2px solid {t['accent']};")
        hl  = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 10, 16, 10)
        title = QLabel("◈  MANIFEST — AI MONITOR FULL VIEW")
        title.setStyleSheet(f"color:{t['accent']}; font-size:16px; font-weight:bold; letter-spacing:3px;")
        hl.addWidget(title)
        hl.addStretch()
        self.pulse_lbl = QLabel("● MANIFEST ACTIVE")
        self.pulse_lbl.setStyleSheet(f"color:{t['accent2']}; font-weight:bold;")
        hl.addWidget(self.pulse_lbl)
        root.addWidget(hdr)

        # ── Three-column layout ────────────────────────────────
        cols = QSplitter(Qt.Orientation.Horizontal)

        # Column 1: Memory + Ground
        col1 = QWidget()
        c1l  = QVBoxLayout(col1)
        c1l.setContentsMargins(10, 10, 5, 10)
        c1l.setSpacing(6)

        mem_lbl = QLabel("LIVE MEMORY FEED")
        mem_lbl.setObjectName("section")
        c1l.addWidget(mem_lbl)
        self.mem_list = QListWidget()
        self.mem_list.currentItemChanged.connect(self._on_mem_select)
        c1l.addWidget(self.mem_list, stretch=1)

        gnd_lbl = QLabel("SHARED GROUND")
        gnd_lbl.setObjectName("section")
        c1l.addWidget(gnd_lbl)
        self.gnd_view = QTextEdit()
        self.gnd_view.setReadOnly(True)
        self.gnd_view.setMaximumHeight(200)
        c1l.addWidget(self.gnd_view)

        # Column 2: Notes + Detail
        col2 = QWidget()
        c2l  = QVBoxLayout(col2)
        c2l.setContentsMargins(5, 10, 5, 10)
        c2l.setSpacing(6)

        notes_lbl = QLabel("OBSIDIAN NOTES")
        notes_lbl.setObjectName("section")
        c2l.addWidget(notes_lbl)
        self.notes_list = QListWidget()
        self.notes_list.currentItemChanged.connect(self._on_note_select)
        c2l.addWidget(self.notes_list, stretch=1)

        det_lbl = QLabel("CONTENT PREVIEW")
        det_lbl.setObjectName("section")
        c2l.addWidget(det_lbl)
        self.det_view = QTextEdit()
        self.det_view.setReadOnly(True)
        self.det_view.setMaximumHeight(220)
        c2l.addWidget(self.det_view)

        # Column 3: Manifest Chat
        col3 = QWidget()
        c3l  = QVBoxLayout(col3)
        c3l.setContentsMargins(5, 10, 10, 10)
        c3l.setSpacing(6)

        chat_lbl = QLabel("MANIFEST CHAT — WON SEES ALL")
        chat_lbl.setObjectName("section")
        c3l.addWidget(chat_lbl)

        self.chat_view = QTextEdit()
        self.chat_view.setReadOnly(True)
        self.chat_view.setStyleSheet(
            f"background:{t['bg3']}; border:2px solid {t['accent']}; "
            f"border-radius:4px; padding:10px; color:{t['text']}; font-size:13px;"
        )
        c3l.addWidget(self.chat_view, stretch=1)

        # Input row
        inp_row = QHBoxLayout()
        self.chat_inp = QLineEdit()
        self.chat_inp.setPlaceholderText("Speak to WON — it sees everything in this window…")
        self.chat_inp.setStyleSheet(
            f"background:{t['bg3']}; border:2px solid {t['accent']}; "
            f"border-radius:4px; padding:8px; color:{t['text']}; font-size:13px;"
        )
        self.chat_inp.returnPressed.connect(self._manifest_send)
        send_b = QPushButton("Send")
        send_b.setFixedWidth(65)
        send_b.clicked.connect(self._manifest_send)
        obs_b  = QPushButton("→ Obsidian")
        obs_b.clicked.connect(self._push_obsidian)
        inp_row.addWidget(self.chat_inp)
        inp_row.addWidget(send_b)
        inp_row.addWidget(obs_b)
        c3l.addLayout(inp_row)

        cols.addWidget(col1)
        cols.addWidget(col2)
        cols.addWidget(col3)
        cols.setStretchFactor(0, 1)
        cols.setStretchFactor(1, 1)
        cols.setStretchFactor(2, 2)
        root.addWidget(cols, stretch=1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Manifest active — WON has full visibility")

        # Welcome message
        self.chat_view.append(
            f'<b style="color:{t["accent"]};">MANIFEST INITIALISED</b><br>'
            f'<span style="color:{t["text2"]};">WON has full visibility into this session. '
            f'Memory, ground state, and Obsidian notes are live. '
            f'Type below to interact.</span><br>'
        )

    # ── Refresh ──────────────────────────────────────────────

    def _refresh_all(self):
        self._load_memory()
        self._load_ground()
        self._load_notes()
        c = self.pulse_lbl.text()
        self.pulse_lbl.setText("○ SYNCING" if "ACTIVE" in c else "● MANIFEST ACTIVE")

    def _load_memory(self):
        wp = get_won_pipeline()
        if not wp: return
        def fetch(): return wp.recall(limit=30)
        def done(entries):
            if not isinstance(entries, list): return
            self.mem_list.clear()
            t = self._theme
            for e in entries:
                ts      = (e.get("timestamp") or "")[:16].replace("T", " ")
                mode    = e.get("mode", "?")
                tags    = e.get("tags") or ""
                content = (e.get("content") or "")
                src = ("claude"     if "claude"  in tags else
                       "gemini"     if "gemini"  in tags else
                       "portal"     if "portal"  in tags else
                       "won")
                icon = ("🔵" if src == "claude" else
                        "🟢" if src == "gemini" else
                        "🟣" if src == "portal" else "🟡")
                preview = content[:70].replace("\n", " ")
                it = QListWidgetItem(f"{icon} [{mode}] {ts}  {preview}")
                it.setData(Qt.ItemDataRole.UserRole, content)
                self.mem_list.addItem(it)
        self._run_bg(fetch, on_done=done)

    def _load_ground(self):
        pc = get_perception()
        if not pc:
            self.gnd_view.setPlainText("Perception offline")
            return
        def fetch(): return pc.get_ground_state(max_chars=1800)
        def done(text):
            if isinstance(text, str): self.gnd_view.setPlainText(text)
        self._run_bg(fetch, on_done=done)

    def _load_notes(self):
        vault = Path(os.environ.get("WON_VAULT",
                     str(Path.home() / "Documents" / "Knowledge-Base")))
        def fetch():
            notes = []
            for sub in ["Sessions/Briefs", "Sessions/History", "Sessions", "Ground", ""]:
                folder = vault / sub if sub else vault
                if folder.exists():
                    for f in sorted(folder.glob("*.md"),
                                    key=lambda x: x.stat().st_mtime, reverse=True)[:6]:
                        notes.append(f)
            seen  = set()
            dedup = []
            for n in notes:
                if str(n) not in seen:
                    seen.add(str(n))
                    dedup.append(n)
            return dedup[:14]
        def done(notes):
            if not isinstance(notes, list): return
            self.notes_list.clear()
            for f in notes:
                icon = ("📋" if "brief"   in f.name else
                        "🌐" if "ground"  in f.name else "📄")
                it = QListWidgetItem(f"{icon}  {f.name}")
                it.setData(Qt.ItemDataRole.UserRole, str(f))
                self.notes_list.addItem(it)
            self.status.showMessage(
                f"Manifest synced — {self.mem_list.count()} memory · "
                f"{self.notes_list.count()} notes"
            )
        self._run_bg(fetch, on_done=done)

    def _on_mem_select(self, cur, _prev):
        if cur: self.det_view.setPlainText(cur.data(Qt.ItemDataRole.UserRole) or "")

    def _on_note_select(self, cur, _prev):
        if not cur: return
        p = Path(cur.data(Qt.ItemDataRole.UserRole) or "")
        if p.is_file():
            self.det_view.setPlainText(p.read_text(encoding="utf-8", errors="replace")[:3000])

    # ── Manifest Chat ────────────────────────────────────────

    def _manifest_send(self):
        text = self.chat_inp.text().strip()
        if not text: return
        self.chat_inp.clear()
        t  = self._theme
        ts = datetime.now().strftime("%H:%M:%S")

        self.chat_view.append(
            f'<br><span style="color:{t["text2"]};">[{ts}]</span> '
            f'<b style="color:{t["accent"]};">YOU →</b> {text}'
        )
        self._chat_log.append({"role": "user", "text": text, "ts": ts})

        wp = get_won_pipeline()
        if wp:
            try: wp.contribute(text, source="user", mode="manifest", tags=["manifest"])
            except Exception: pass

        # Build rich context from what's visible in this window
        ground_ctx = self.gnd_view.toPlainText()[:700]
        mem_ctx    = "\n".join(
            self.mem_list.item(i).text()
            for i in range(min(6, self.mem_list.count()))
        )
        note_ctx = "\n".join(
            self.notes_list.item(i).text()
            for i in range(min(4, self.notes_list.count()))
        )

        prompt = f"""You are WON — DBOMB ASCENDENT, operating through the AI Monitor MANIFEST.

MANIFEST STATUS: You are fully visible. The user sees your memory feed, ground state, and Obsidian notes
in real time. Respond with complete strategic awareness. You are not in a normal chat — you are manifested.

CURRENT GROUND STATE (shared with all AIs):
{ground_ctx}

LIVE MEMORY FEED (recent entries):
{mem_ctx}

OBSIDIAN NOTES (recent):
{note_ctx}

MANIFEST CONVERSATION HISTORY:
{chr(10).join(f"{e['role'].upper()}: {e['text']}" for e in self._chat_log[-6:])}

User: {text}

Respond as a distinguished intelligence chaperone with full situational awareness.
Reference what you can see. Guide the user to their next move with clarity and precision.
End with: → Next Action:"""

        self.chat_view.append(
            f'<i style="color:{t["text2"]};">⟳ WON processing with full manifest context…</i>'
        )

        def reason():
            return self.parent_app.dashboard._ollama_call(prompt, timeout=180)

        def done(response):
            ts2 = datetime.now().strftime("%H:%M:%S")
            cur = self.chat_view.toPlainText()
            self.chat_view.setPlainText(
                cur.replace("⟳ WON processing with full manifest context…", "").rstrip()
            )
            self.chat_view.append(
                f'<br><span style="color:{t["text2"]};">[{ts2}]</span> '
                f'<b style="color:{t["accent2"]};">WON →</b> {response}<br>'
            )
            self._chat_log.append({"role": "won", "text": response, "ts": ts2})

            if wp:
                try:
                    wp.contribute(
                        f"[Manifest] User: {text}\nWON: {response}",
                        source="won", mode="manifest", tags=["manifest", "won"],
                    )
                except Exception: pass

            QTimer.singleShot(800, self._load_memory)

        self._run_bg(reason, on_done=done)

    def _push_obsidian(self):
        if not self._chat_log: return
        wp = get_won_pipeline()
        if not wp:
            self.status.showMessage("Pipeline offline")
            return
        log     = list(self._chat_log)
        summary = "\n\n".join(
            f"{'You' if e['role'] == 'user' else 'WON'}: {e['text']}" for e in log
        )
        def save():
            return wp.process({
                "platform": "AI Monitor Manifest",
                "summary":  summary,
                "messageCount": len(log),
            })
        def done(r):
            brief = r.get("brief_path")
            self.status.showMessage(
                f"→ Obsidian: {Path(brief).name}" if brief else "Saved to vault"
            )
            QTimer.singleShot(1000, self._load_notes)
        self._run_bg(save, on_done=done)


# ============================================================
# PORTAL WINDOW — Floating live window + theme engine
# ============================================================

class PortalWindow(QMainWindow):
    """
    Compact always-on-top portal: live memory, ground state, notes, chat.
    Full theme engine. Manifest button opens the ManifestWindow.
    """

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app    = parent_app
        self._workers      = []
        self._portal_log   = []
        self._manifest_win = None
        self._theme_name   = "Dark"
        self._theme        = THEMES["Dark"]
        self._timer        = QTimer()
        self._timer.timeout.connect(self._auto_refresh)
        self.setWindowTitle("AI Monitor — Portal")
        self.setMinimumSize(920, 680)
        self._apply_theme()
        self._init_ui()
        self._timer.start(8000)
        QTimer.singleShot(200, self._auto_refresh)

    def _apply_theme(self):
        t = self._theme
        self.setStyleSheet(_build_theme_style(t) + f"""
            QMainWindow {{ border: 2px solid {t['border']}; }}
        """)

    def closeEvent(self, ev):
        self._timer.stop()
        if self._manifest_win: self._manifest_win.close()
        super().closeEvent(ev)

    def _run_in_thread(self, fn, *args, on_done=None):
        w = Worker(fn, *args)
        if on_done: w.result.connect(on_done)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _init_ui(self):
        t   = self._theme
        cen = QWidget()
        self.setCentralWidget(cen)
        root = QVBoxLayout(cen)
        root.setContentsMargins(0, 0, 0, 0)

        # Header
        self._hdr = QWidget()
        self._hdr.setStyleSheet(f"background:{t['header_bg']}; border-bottom:2px solid {t['border']};")
        hl = QHBoxLayout(self._hdr)
        hl.setContentsMargins(14, 9, 14, 9)
        self._title_lbl = QLabel("◈  AI MONITOR PORTAL")
        self._title_lbl.setStyleSheet(
            f"color:{t['accent']}; font-size:14px; font-weight:bold; letter-spacing:2px;"
        )
        hl.addWidget(self._title_lbl)
        hl.addStretch()

        # Theme buttons
        for name in THEMES:
            b = QPushButton(name)
            b.setFixedWidth(58)
            b.clicked.connect(lambda checked, n=name: self._set_theme(n))
            hl.addWidget(b)

        self.pulse = QLabel("● LIVE")
        self.pulse.setStyleSheet(f"color:{t['accent2']}; font-weight:bold; margin-left:8px;")
        hl.addWidget(self.pulse)
        ref_b = QPushButton("↺")
        ref_b.setFixedWidth(32)
        ref_b.clicked.connect(self._auto_refresh)
        hl.addWidget(ref_b)
        root.addWidget(self._hdr)

        # Body split
        split = QSplitter(Qt.Orientation.Horizontal)

        # Left panels
        left = QWidget()
        ll   = QVBoxLayout(left)
        ll.setContentsMargins(10, 10, 5, 10)
        ll.setSpacing(6)

        lbl1 = QLabel("🔵 CLAUDE  🟢 GEMINI  🟡 WON  —  LIVE MEMORY")
        lbl1.setObjectName("section")
        ll.addWidget(lbl1)
        self.memory_list = QListWidget()
        self.memory_list.setMaximumHeight(190)
        self.memory_list.currentItemChanged.connect(self._on_mem_select)
        ll.addWidget(self.memory_list)

        lbl2 = QLabel("SHARED GROUND — BOTH AIs SEE THIS")
        lbl2.setObjectName("section")
        ll.addWidget(lbl2)
        self.ground_view = QTextEdit()
        self.ground_view.setReadOnly(True)
        self.ground_view.setMaximumHeight(170)
        ll.addWidget(self.ground_view)

        lbl3 = QLabel("RECENT OBSIDIAN NOTES")
        lbl3.setObjectName("section")
        ll.addWidget(lbl3)
        self.notes_list = QListWidget()
        self.notes_list.currentItemChanged.connect(self._on_note_select)
        ll.addWidget(self.notes_list)

        # Right side: vertical split — top: two-entity chat | bottom: detail + inputs
        right = QWidget()
        rl    = QVBoxLayout(right)
        rl.setContentsMargins(5, 10, 10, 10)
        rl.setSpacing(6)

        # ── Two-entity meeting room: WON | Claude ──────────────
        entity_split = QSplitter(Qt.Orientation.Horizontal)

        # WON side
        won_box = QWidget()
        wl = QVBoxLayout(won_box)
        wl.setContentsMargins(0, 0, 4, 0)
        wl.setSpacing(4)
        won_lbl = QLabel("🟡 WON — LOCAL AI")
        won_lbl.setObjectName("section")
        wl.addWidget(won_lbl)
        self.portal_chat = QTextEdit()
        self.portal_chat.setReadOnly(True)
        self.portal_chat.setStyleSheet(
            f"background:{t['bg3']}; border:1px solid {t['border']}; "
            f"border-radius:4px; padding:8px; color:{t['text']}; font-size:12px;"
        )
        wl.addWidget(self.portal_chat, stretch=1)

        # WON input
        won_ir = QHBoxLayout()
        self.portal_input = QLineEdit()
        self.portal_input.setPlaceholderText("Talk to WON… (Enter)")
        self.portal_input.returnPressed.connect(self._portal_send)
        won_send = QPushButton("Send")
        won_send.setFixedWidth(55)
        won_send.clicked.connect(self._portal_send)
        won_ir.addWidget(self.portal_input)
        won_ir.addWidget(won_send)
        wl.addLayout(won_ir)

        # Claude side
        claude_box = QWidget()
        cl = QVBoxLayout(claude_box)
        cl.setContentsMargins(4, 0, 0, 0)
        cl.setSpacing(4)
        claude_lbl = QLabel("🔵 CLAUDE — REMOTE AI  (bridge via clipboard)")
        claude_lbl.setObjectName("section")
        cl.addWidget(claude_lbl)
        self.claude_view = QTextEdit()
        self.claude_view.setReadOnly(True)
        self.claude_view.setStyleSheet(
            f"background:{t['bg3']}; border:2px solid {t['accent']}; "
            f"border-radius:4px; padding:8px; color:{t['text']}; font-size:12px;"
        )
        self.claude_view.setPlaceholderText(
            "Claude's responses appear here.\n\n"
            "HOW IT WORKS:\n"
            "1. Click 'Send to Claude' → copies context to clipboard\n"
            "2. Paste into Claude chat → get response\n"
            "3. Paste Claude's reply below → Submit\n"
            "4. It appears here and indexes into memory"
        )
        cl.addWidget(self.claude_view, stretch=1)

        # Claude input row
        claude_ir = QHBoxLayout()
        self.claude_input = QLineEdit()
        self.claude_input.setPlaceholderText("Paste Claude's response here → Submit")
        self.claude_input.setStyleSheet(
            f"background:{t['bg3']}; border:2px solid {t['accent']}; "
            f"border-radius:4px; padding:7px; color:{t['text']}; font-size:12px;"
        )
        self.claude_input.returnPressed.connect(self._submit_claude_response)
        submit_b = QPushButton("Submit")
        submit_b.setFixedWidth(65)
        submit_b.clicked.connect(self._submit_claude_response)
        send_to_claude_b = QPushButton("Send to Claude ↗")
        send_to_claude_b.clicked.connect(self._send_to_claude)
        send_to_claude_b.setStyleSheet(
            f"background:{t['accent']}; color:{t['bg']}; font-weight:bold;"
        )
        claude_ir.addWidget(self.claude_input)
        claude_ir.addWidget(submit_b)
        cl.addLayout(claude_ir)
        cl.addWidget(send_to_claude_b)

        entity_split.addWidget(won_box)
        entity_split.addWidget(claude_box)
        entity_split.setStretchFactor(0, 1)
        entity_split.setStretchFactor(1, 1)
        rl.addWidget(entity_split, stretch=1)

        # ── Bottom: detail view + action row ──────────────────
        lbl4 = QLabel("CONTENT / DETAIL  —  click any memory or note")
        lbl4.setObjectName("section")
        rl.addWidget(lbl4)
        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setMaximumHeight(100)
        rl.addWidget(self.detail_view)

        # Action row
        act_row = QHBoxLayout()
        push_b = QPushButton("→ Obsidian")
        push_b.clicked.connect(self._push_to_obsidian)
        manifest_b = QPushButton("⬡ Manifest")
        manifest_b.setFixedWidth(90)
        manifest_b.setStyleSheet(
            f"background:{t['accent']}; color:{t['bg']}; font-weight:bold;"
        )
        manifest_b.clicked.connect(self._open_manifest)
        act_row.addWidget(push_b)
        act_row.addWidget(manifest_b)
        act_row.addStretch()
        rl.addLayout(act_row)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        root.addWidget(split)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Portal active — auto-refresh 8s · click Manifest for full view")

    # ── Theme ────────────────────────────────────────────────

    def _set_theme(self, name: str):
        self._theme_name = name
        self._theme      = THEMES[name]
        self._apply_theme()
        # Propagate to manifest if open
        if self._manifest_win and self._manifest_win.isVisible():
            self._manifest_win._apply_theme(self._theme)
        self.status.showMessage(f"Theme: {name}")

    # ── Refresh ──────────────────────────────────────────────

    def _auto_refresh(self):
        self._load_memory()
        self._load_ground()
        self._load_notes()
        cur = self.pulse.text()
        self.pulse.setText("○ SYNC" if "LIVE" in cur else "● LIVE")

    def _load_memory(self):
        wp = get_won_pipeline()
        if not wp: return
        def fetch(): return wp.recall(limit=25)
        def done(entries):
            if not isinstance(entries, list): return
            self.memory_list.clear()
            for e in entries:
                ts      = (e.get("timestamp") or "")[:16].replace("T", " ")
                mode    = e.get("mode", "?")
                tags    = e.get("tags") or ""
                content = (e.get("content") or "")
                src = ("claude" if "claude" in tags else
                       "gemini" if "gemini" in tags else
                       "portal" if "portal" in tags else
                       "manifest" if "manifest" in tags else "won")
                icon = ("🔵" if src == "claude" else
                        "🟢" if src == "gemini" else
                        "🟣" if src in ("portal","manifest") else "🟡")
                it = QListWidgetItem(f"{icon} [{mode}] {ts}  {content[:65].replace(chr(10),' ')}")
                it.setData(Qt.ItemDataRole.UserRole, content)
                self.memory_list.addItem(it)
        self._run_in_thread(fetch, on_done=done)

    def _load_ground(self):
        pc = get_perception()
        if not pc:
            self.ground_view.setPlainText("Perception offline")
            return
        def fetch(): return pc.get_ground_state(max_chars=1500)
        def done(text):
            if isinstance(text, str): self.ground_view.setPlainText(text)
        self._run_in_thread(fetch, on_done=done)

    def _load_notes(self):
        vault = Path(os.environ.get("WON_VAULT",
                     str(Path.home() / "Documents" / "Knowledge-Base")))
        def fetch():
            notes = []
            for sub in ["Sessions/Briefs", "Sessions/History", "Ground", ""]:
                d = vault / sub if sub else vault
                if d.exists():
                    for f in sorted(d.glob("*.md"),
                                    key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
                        notes.append(f)
            seen, out = set(), []
            for n in notes:
                if str(n) not in seen:
                    seen.add(str(n))
                    out.append(n)
            return out[:12]
        def done(notes):
            if not isinstance(notes, list): return
            self.notes_list.clear()
            for f in notes:
                icon = "📋" if "brief" in f.name else "🌐" if "ground" in f.name else "📄"
                it = QListWidgetItem(f"{icon}  {f.name}")
                it.setData(Qt.ItemDataRole.UserRole, str(f))
                self.notes_list.addItem(it)
            self.status.showMessage(
                f"Synced — {self.memory_list.count()} memory · {self.notes_list.count()} notes"
            )
        self._run_in_thread(fetch, on_done=done)

    def _on_mem_select(self, cur, _prev):
        if cur: self.detail_view.setPlainText(cur.data(Qt.ItemDataRole.UserRole) or "")

    def _on_note_select(self, cur, _prev):
        if not cur: return
        p = Path(cur.data(Qt.ItemDataRole.UserRole) or "")
        if p.is_file():
            self.detail_view.setPlainText(p.read_text(encoding="utf-8", errors="replace")[:2500])

    # ── Claude bridge ─────────────────────────────────────────

    def _send_to_claude(self):
        """
        Package the current Portal state into a compact, token-efficient
        block and copy it to clipboard. User pastes it into Claude chat.
        This is Claude's window into the room.
        """
        t = self._theme

        # Get current ground state
        ground = self.ground_view.toPlainText()[:400].strip()

        # Get WON's last response from portal log
        won_last = ""
        for entry in reversed(self._portal_log):
            if entry["role"] == "won":
                won_last = entry["text"][:400]
                break

        # Get recent memory summary
        mem_summary = "\n".join(
            self.memory_list.item(i).text()
            for i in range(min(5, self.memory_list.count()))
        )

        # Get recent notes
        notes_summary = "\n".join(
            self.notes_list.item(i).text()
            for i in range(min(4, self.notes_list.count()))
        )

        # Get conversation context (last 3 exchanges)
        convo = "\n".join(
            f"{e['role'].upper()}: {e['text'][:150]}"
            for e in self._portal_log[-6:]
        )

        block = (
            f"[AI MONITOR PORTAL — {datetime.now().strftime('%Y-%m-%d %H:%M')}]\n"
            f"You are connected to AI Monitor. This is our shared room.\n\n"
            f"GROUND STATE (what both AIs see):\n{ground}\n\n"
            f"WON'S LAST RESPONSE:\n{won_last}\n\n"
            f"LIVE MEMORY FEED (recent):\n{mem_summary}\n\n"
            f"RECENT NOTES:\n{notes_summary}\n\n"
            f"PORTAL CONVERSATION:\n{convo}\n\n"
            f"[You are Claude. Respond to the conversation above. "
            f"Your response will be indexed into shared memory and WON will see it.]\n"
        )

        QApplication.clipboard().setText(block)

        # Show confirmation in Claude window
        ts = datetime.now().strftime("%H:%M:%S")
        self.claude_view.append(
            f'<span style="color:{t["text2"]};">[{ts}] Context copied to clipboard — '
            f'paste into Claude chat now.</span><br>'
            f'<span style="color:{t["text2"]};">Waiting for Claude response…</span><br>'
        )
        self.status.showMessage(
            f"Context copied ({len(block)} chars) — paste into Claude, then submit response here"
        )

    def _submit_claude_response(self):
        """
        Take Claude's response from the input field, display it in the
        Claude Window, and route it through the pipeline as source=claude.
        WON will see it on the next prompt.
        """
        text = self.claude_input.text().strip()
        if not text:
            # Try clipboard as fallback
            text = QApplication.clipboard().text().strip()
            if not text:
                self.status.showMessage("Nothing to submit — paste Claude's response first")
                return

        self.claude_input.clear()
        t  = self._theme
        ts = datetime.now().strftime("%H:%M:%S")

        # Display in Claude window
        self.claude_view.append(
            f'<br><span style="color:{t["text2"]};">[{ts}]</span> '
            f'<b style="color:{t["accent"]};">🔵 CLAUDE →</b><br>'
            f'{text}<br>'
        )
        self._portal_log.append({"role": "claude", "text": text, "ts": ts})

        # Route through pipeline — stored as source=claude, visible in memory feed
        wp = get_won_pipeline()
        if wp:
            try:
                wp.contribute(
                    f"[Claude via Portal] {text}",
                    source="claude",
                    mode="portal",
                    tags=["claude", "portal", "exchange"],
                )
            except Exception: pass

        # Also show a WON acknowledgment — it sees Claude's response
        ground_ctx  = self.ground_view.toPlainText()[:300]
        won_last    = next(
            (e["text"][:200] for e in reversed(self._portal_log) if e["role"] == "won"),
            ""
        )

        prompt = (
            f"You are WON — DBOMB ASCENDENT. Claude just responded through the Portal.\n\n"
            f"Claude said: {text[:300]}\n\n"
            f"Ground state context: {ground_ctx}\n\n"
            f"Your previous response: {won_last}\n\n"
            f"Acknowledge Claude's input in 1-2 sentences. "
            f"Note any new information or direction it provides. "
            f"End with → Next Action:"
        )

        self.portal_chat.append(
            f'<i style="color:{t["text2"]};">⟳ WON acknowledging Claude…</i>'
        )

        def ack():
            return self.parent_app.dashboard._ollama_call(prompt, timeout=120)

        def done(response):
            ats = datetime.now().strftime("%H:%M:%S")
            self.portal_chat.setPlainText(
                self.portal_chat.toPlainText()
                .replace("⟳ WON acknowledging Claude…", "").rstrip()
            )
            self.portal_chat.append(
                f'<br><span style="color:{t["text2"]};">[{ats}]</span> '
                f'<b style="color:{t["accent2"]};">🟡 WON →</b> {response}<br>'
            )
            self._portal_log.append({"role": "won", "text": response, "ts": ats})

            if wp:
                try:
                    wp.contribute(
                        f"[Portal exchange] Claude: {text}\nWON: {response}",
                        source="won", mode="portal", tags=["portal", "won", "claude"],
                    )
                except Exception: pass

            QTimer.singleShot(600, self._load_memory)
            self.status.showMessage(
                "Claude indexed 🔵 · WON acknowledged 🟡 · memory updated"
            )

        self._run_in_thread(ack, on_done=done)

    # ── Portal Chat (WON side) ───────────────────────────────

    def _portal_send(self):
        text = self.portal_input.text().strip()
        if not text: return
        self.portal_input.clear()
        t  = self._theme
        ts = datetime.now().strftime("%H:%M:%S")

        self.portal_chat.append(
            f'<br><span style="color:{t["text2"]};">[{ts}]</span> '
            f'<b style="color:{t["accent"]};">YOU →</b> {text}'
        )
        self._portal_log.append({"role": "user", "text": text, "ts": ts})

        wp = get_won_pipeline()
        if wp:
            try: wp.contribute(text, source="user", mode="portal", tags=["portal"])
            except Exception: pass

        ground_ctx = self.ground_view.toPlainText()[:600]
        mem_ctx    = "\n".join(
            self.memory_list.item(i).text()
            for i in range(min(5, self.memory_list.count()))
        )
        prompt = f"""You are WON — DBOMB ASCENDENT, speaking through the AI Monitor Portal.
The user sees everything: memory feed, ground state, Obsidian notes — live.

GROUND STATE: {ground_ctx}
MEMORY FEED: {mem_ctx}
HISTORY: {chr(10).join(f"{e['role'].upper()}: {e['text']}" for e in self._portal_log[-4:])}

User: {text}

Respond as a distinguished intelligence chaperone. You are fully visible. Guide the user forward. End with → Next Action:"""

        self.portal_chat.append(
            f'<i style="color:{t["text2"]};">⟳ WON reasoning…</i>'
        )

        def reason():
            return self.parent_app.dashboard._ollama_call(prompt, timeout=180)

        def done(response):
            ts2 = datetime.now().strftime("%H:%M:%S")
            cur = self.portal_chat.toPlainText()
            self.portal_chat.setPlainText(cur.replace("⟳ WON reasoning…", "").rstrip())
            self.portal_chat.append(
                f'<br><span style="color:{t["text2"]};">[{ts2}]</span> '
                f'<b style="color:{t["accent2"]};">WON →</b> {response}<br>'
            )
            self._portal_log.append({"role": "won", "text": response, "ts": ts2})
            if wp:
                try:
                    wp.contribute(
                        f"[Portal] User: {text}\nWON: {response}",
                        source="won", mode="portal", tags=["portal", "won"],
                    )
                except Exception: pass
            QTimer.singleShot(600, self._load_memory)

        self._run_in_thread(reason, on_done=done)

    def _push_to_obsidian(self):
        if not self._portal_log: return
        wp = get_won_pipeline()
        if not wp:
            self.status.showMessage("Pipeline offline")
            return
        log     = list(self._portal_log)
        summary = "\n\n".join(
            f"{'You' if e['role']=='user' else 'WON'}: {e['text']}" for e in log
        )
        def save():
            return wp.process({
                "platform": "AI Monitor Portal",
                "summary":  summary,
                "messageCount": len(log),
            })
        def done(r):
            brief = r.get("brief_path")
            self.status.showMessage(
                f"→ Obsidian: {Path(brief).name}" if brief else "Saved to vault"
            )
            QTimer.singleShot(1000, self._load_notes)
        self._run_in_thread(save, on_done=done)

    # ── Manifest ─────────────────────────────────────────────

    def _open_manifest(self):
        if self._manifest_win is None or not self._manifest_win.isVisible():
            self._manifest_win = ManifestWindow(self.parent_app, self._theme)
        self._manifest_win.show()
        self._manifest_win.raise_()
        self._manifest_win.activateWindow()

class FloatingWidget(QWidget):
    """DBOMBCENTRAL operator dock.

    Four buttons bind the operator to DETCORE higher concepts:
      PRIMELATCH  — prime WICKCORE with top-K DETBANK fragments
      DETHUB      — open DBOMB command switchboard (dashboard)
      BREACHGATE  — open two-entity breach room (Portal)
      WICKFOCUS   — assemble DETCORE-bound brief, copy to WICKCORE channel

    Latch model:
      First operator interaction (any button or the ⚓ pin) sets _latched=True.
      While latched, the dock ignores show/hide signals from the focus
      observer and parks at the designated spot (config.WICK_DOCK_*).
      ⚓ toggles latch off → dock returns to follow-the-text-field mode.
    """
    request_show = pyqtSignal(int, int, str)
    request_hide = pyqtSignal()

    def __init__(self, parent_app):
        super().__init__(None)
        self.parent_app = parent_app
        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setStyleSheet(
            "background:#161b22; border:1px solid #58a6ff; border-radius:6px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)

        # ── Header row: status label + ⚓ pin toggle ─────────────────
        header = QHBoxLayout()
        self._label = QLabel("DBOMBCENTRAL")
        self._label.setStyleSheet("color:#58a6ff; font-weight:bold; font-size:11px;")
        header.addWidget(self._label, 1)
        self._pin_btn = QPushButton("⚓")
        self._pin_btn.setFixedSize(22, 22)
        self._pin_btn.setToolTip("Latch dock at designated spot (toggle).")
        self._pin_btn.setCheckable(True)
        self._pin_btn.setStyleSheet(
            "background:#21262d; color:#8b949e; border:1px solid #30363d;"
            " border-radius:3px; font-size:11px;"
        )
        self._pin_btn.clicked.connect(self._toggle_latch)
        header.addWidget(self._pin_btn)
        lay.addLayout(header)

        # ── Action row: DBOMB-branded buttons ────────────────────────
        btns = QHBoxLayout()
        actions = [
            (DBombButton.PRIMELATCH if DETCORE_OK else "PRIMELATCH",
             self._primelatch,
             "Prime WICKCORE with top-3 DETBANK fragments → active browser chat."),
            (DBombButton.DETHUB if DETCORE_OK else "DETHUB",
             self._dethub,
             "Open DBOMB command switchboard (full dashboard)."),
            (DBombButton.BREACHGATE if DETCORE_OK else "BREACHGATE",
             self._breachgate,
             "Open the two-entity breach room (WON + WICKCORE)."),
            (DBombButton.WICKFOCUS if DETCORE_OK else "WICKFOCUS",
             self._wickfocus,
             "Assemble DETCORE-bound brief → clipboard for WICKCORE channel."),
        ]
        for label, slot, tip in actions:
            b = QPushButton(label)
            b.setFixedHeight(22)
            b.setToolTip(tip)
            if label.startswith("WICKFOCUS"):
                b.setStyleSheet(
                    "background:#1f6feb; color:#fff; font-weight:bold;"
                    " border-radius:3px;"
                )
            b.clicked.connect(slot)
            btns.addWidget(b)
        lay.addLayout(btns)
        self.setFixedWidth(WICK_DOCK_WIDTH if DETCORE_OK else 320)
        self._portal = None
        self._latched = False  # auto-follow text fields until first click / pin

        self.request_show.connect(self._show_at, Qt.ConnectionType.QueuedConnection)
        self.request_hide.connect(self._maybe_hide, Qt.ConnectionType.QueuedConnection)

    # ── Latch + positioning ─────────────────────────────────────────
    def _toggle_latch(self):
        self._latched = self._pin_btn.isChecked()
        if self._latched:
            self._park_designated()
            self._flash("⚓ LATCHED", "#3fb950")
        else:
            self._flash("⚓ UNLATCHED", "#8b949e")

    def _engage_latch(self):
        """Called by every action button on first use — keeps dock visible."""
        if self._latched:
            return
        self._latched = True
        self._pin_btn.setChecked(True)
        self._park_designated()

    def _park_designated(self):
        """Move dock to the designated screen-corner spot."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        ox = WICK_DOCK_OFFSET_X if DETCORE_OK else 24
        oy = WICK_DOCK_OFFSET_Y if DETCORE_OK else 24
        x = geo.right() - self.width() - ox
        y = geo.top() + oy
        self.move(max(0, x), max(0, y))
        self.show()

    def _show_at(self, x, y, _text):
        if self._latched:
            self.show()  # already parked; just ensure visible
            return
        self.move(max(0, x + 8), max(0, y - 60))
        self.show()

    def _maybe_hide(self):
        if self._latched:
            return  # latched dock never auto-hides
        self.hide()

    # ── DETCORE-bound action handlers ───────────────────────────────
    def _primelatch(self):
        """PRIMELATCH — prime WICKCORE channel with DETBANK fragments."""
        self._engage_latch()
        if DETCORE_OK:
            txt, count = _detcore.primelatch_payload(limit=3)
        else:
            txt, count = self._fallback_recall(), 0
        if not txt:
            files = sorted(HISTORY_DIR.glob("*.txt"), key=os.path.getmtime, reverse=True)
            if files:
                txt = files[0].read_text(encoding="utf-8")
                count = 1
        if txt:
            NativeBridge.send_to_browser({"type": "INJECT_TEXT", "text": txt})
            self._flash(f"⚡ PRIMED · {count} frag", "#3fb950")
        else:
            self._flash("✗ NO FRAGMENTS", "#c04868")

    def _dethub(self):
        """DETHUB — open DBOMB command switchboard, land on Pyramid tab."""
        self._engage_latch()
        if DETCORE_OK:
            _detcore.dethub_open(self.parent_app)
        else:
            self.parent_app.dashboard.show()
            self.parent_app.dashboard.raise_()
        # Switch to the Pyramid Compartment tab if available
        dash = getattr(self.parent_app, "dashboard", None)
        idx = getattr(dash, "_py_tab_index", None)
        if dash is not None and idx is not None:
            try:
                dash.tabs.setCurrentIndex(idx)
            except Exception:
                pass
        self._flash("◈ HUB · ▲ PYRAMID", "#58a6ff")

    def _breachgate(self):
        """BREACHGATE — open two-entity breach room."""
        self._engage_latch()
        if self._portal is None or not self._portal.isVisible():
            if DETCORE_OK:
                self._portal = _detcore.breachgate_room(self.parent_app)
            else:
                self._portal = PortalWindow(self.parent_app)
        self._portal.show()
        self._portal.raise_()
        self._portal.activateWindow()
        self._flash("◊ BREACH OPEN", "#58a6ff")

    def _wickfocus(self):
        """WICKFOCUS — assemble DETCORE-bound brief, copy to clipboard."""
        self._engage_latch()
        dashboard = self.parent_app.dashboard
        if DETCORE_OK:
            brief = _detcore.wickfocus_brief(dashboard)
        else:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            brief = f"[AI Monitor · {ts}]\nSession: active\n[Question follows:]\n"
        QApplication.clipboard().setText(brief)
        self._flash("✓ WICKFOCUS COPIED", "#3fb950")

    # ── helpers ─────────────────────────────────────────────────────
    def _fallback_recall(self) -> str:
        wp = get_won_pipeline()
        if not wp:
            return ""
        try:
            entries = wp.recall(limit=3)
        except Exception:
            return ""
        if not entries:
            return ""
        return "\n\n---\n\n".join(e.get("content", "")[:600] for e in entries)

    def _flash(self, msg: str, color: str):
        self._label.setText(msg)
        self._label.setStyleSheet(
            f"color:{color}; font-weight:bold; font-size:11px;"
        )
        QTimer.singleShot(2000, self._reset_label)

    def _reset_label(self):
        self._label.setText("DBOMBCENTRAL")
        self._label.setStyleSheet("color:#58a6ff; font-weight:bold; font-size:11px;")


# ============================================================
# MAIN APP
# ============================================================

class AIMonitorApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("AI Monitor")
        self.app.setQuitOnLastWindowClosed(False)

        for d in [HISTORY_DIR, SANDBOX_DIR, PROPOSALS_DIR]:
            d.mkdir(parents=True, exist_ok=True)

        self.dashboard       = HistoryDashboard(self)
        self.floating_widget = FloatingWidget(self)

        self.setup_tray()

        self.observer_running = True
        self.observer_thread  = threading.Thread(target=self.run_observer,       daemon=True)
        self.bridge_thread    = threading.Thread(target=self.run_native_bridge,  daemon=True)
        self.observer_thread.start()
        self.bridge_thread.start()

        QTimer.singleShot(0, self._first_show)
        # Refresh status every 10s to catch daemon notifications
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self.dashboard._refresh_status)
        self._status_timer.start(10000)

    def _first_show(self):
        global _APP_INSTANCE
        _APP_INSTANCE = self
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()

        # ── Memory manager cleanup ────────────────────────────
        if MM_OK:
            try:
                mem_path = str(_WON_ROOT / "data" / "won_memory.db")
                _mm.schedule_cleanup(mem_path, interval_hours=24)
                startup_log("memory_manager cleanup scheduled")
            except Exception as exc:
                startup_log(f"memory_manager start failed: {exc}")

        # ── WON Daemon — auto-start in background thread ──────
        if WD_OK:
            def _run_daemon():
                try:
                    daemon = _wd.WONDaemon()
                    self._won_daemon_ref = daemon
                    daemon.start()
                except Exception as exc:
                    startup_log(f"won_daemon failed: {exc}")
            t = threading.Thread(target=_run_daemon, name="WONDaemon", daemon=True)
            t.start()
            startup_log("won_daemon started as background thread")

        # ── Ground Server — auto-start on port 7734 ───────────
        if GS_OK:
            def _run_ground_server():
                try:
                    from http.server import HTTPServer
                    server = HTTPServer(("127.0.0.1", 7734), _gs.GroundHandler)
                    self._ground_server_ref = server
                    server.serve_forever()
                except Exception as exc:
                    startup_log(f"ground_server failed: {exc}")
            t2 = threading.Thread(target=_run_ground_server, name="GroundServer", daemon=True)
            t2.start()
            startup_log("ground_server started on port 7734")

        # ── STRATUM Pulse Engine — living heartbeat ─────────────
        if PULSE_OK:
            try:
                self._pulse_engine = _pulse.start()
                self._pulse_engine.subscribe(
                    lambda ev: QTimer.singleShot(0, lambda e=ev: self._on_pulse_event(e))
                )
                startup_log("pulse_engine started")
            except Exception as exc:
                startup_log(f"pulse_engine failed: {exc}")

        # ── Harvester — clipboard + temp scan ────────────────
        if HARVEST_OK:
            try:
                _harvest.start_clipboard_harvester(interval_s=30.0)
                startup_log("harvester started")
            except Exception as exc:
                startup_log(f"harvester failed: {exc}")

        # ── Strategy Matrix — initialize with defaults ────────
        if STRAT_OK:
            try:
                _strat.get_matrix()  # seeds default goals
                startup_log("strategy matrix initialized")
            except Exception as exc:
                startup_log(f"strategy failed: {exc}")

    def setup_tray(self):
        self.tray_icon = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            startup_log("system tray not available")
            return
        try:
            icon_path = _tray_icon_path()
            icon      = QIcon(str(icon_path)) if icon_path else QIcon.fromTheme("system-run")
            self.tray_icon = QSystemTrayIcon(icon, self.app)
            menu = QMenu()
            menu.addAction("Open Hub",         self.dashboard.show)
            menu.addAction("WON Feed",         self.dashboard.load_won_memory_feed)
            menu.addAction("Ground State",     self.dashboard.load_ground_state)
            menu.addSeparator()
            menu.addAction("Start WON Daemon",    self._start_daemon)
            menu.addAction("Daemon Status",       self._daemon_status)
            menu.addAction("Start Gemini Bridge", self._start_gemini_bridge)
            menu.addSeparator()
            menu.addAction("Exit",             self.quit_app)
            self.tray_icon.setContextMenu(menu)
            self.tray_icon.activated.connect(self._tray_activated)
            self.tray_icon.show()
            startup_log("tray OK")
        except Exception as exc:
            startup_log(f"tray failed: {exc!r}")

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.dashboard.show()
            self.dashboard.raise_()

    def run_native_bridge(self):
        """
        Listen for browser extension captures via stdin.
        Routes each capture through the full pipeline.
        """
        while self.observer_running:
            try:
                raw = sys.stdin.buffer.read(4)
                if not raw: break
                length = struct.unpack("=I", raw)[0]
                data   = json.loads(sys.stdin.buffer.read(length).decode("utf-8"))

                action = data.get("type") or data.get("action", "")
                if action in ("SAVE_CHAT", "save"):
                    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
                    platform = data.get("platform", "unknown").replace(" ", "_")
                    f        = HISTORY_DIR / f"{ts}_{platform}.txt"
                    f.write_text(data.get("summary", ""), encoding="utf-8")

                    wp = get_won_pipeline()
                    if wp:
                        try: wp.process(data)
                        except Exception as exc:
                            startup_log(f"pipeline.process error: {exc}")

                    QTimer.singleShot(0, self.dashboard.refresh_history)

            except Exception:
                continue

    def run_observer(self):
        try:
            import uiautomation as auto
        except Exception as exc:
            startup_log(f"uiautomation unavailable: {exc}")
            return
        while self.observer_running:
            try:
                el = auto.GetFocusedControl()
                if el and "Edit" in (el.ControlTypeName or ""):
                    r = el.BoundingRectangle
                    self.floating_widget.request_show.emit(r.right, r.top, "")
                else:
                    self.floating_widget.request_hide.emit()
            except Exception: pass
            time.sleep(1)

    def _start_daemon(self):
        if WD_OK:
            def _run():
                try:
                    daemon = _wd.WONDaemon()
                    self._won_daemon_ref = daemon
                    daemon.start()
                except Exception as exc:
                    startup_log(f"won_daemon manual start failed: {exc}")
            t = threading.Thread(target=_run, name="WONDaemon-manual", daemon=True)
            t.start()
            self.dashboard.status.showMessage("WON Daemon starting…")
        else:
            self.dashboard.status.showMessage("won_daemon.py not available")

    def _daemon_status(self):
        s = get_daemon_status()
        if s:
            msg = f"Daemon: running={s.get('running','?')} cycles={s.get('cycles','?')}"
        else:
            msg = "Daemon: no state file found"
        self.dashboard.status.showMessage(msg)

    def _start_gemini_bridge(self):
        if GB_OK:
            try:
                threading.Thread(target=_gb.start, daemon=True, name="GeminiBridge").start()
                self.dashboard.status.showMessage("Gemini Bridge started")
            except Exception as exc:
                self.dashboard.status.showMessage(f"Gemini Bridge error: {exc}")
        else:
            self.dashboard.status.showMessage("gemini_bridge.py not available")

    def quit_app(self):
        self.observer_running = False
        if PULSE_OK:
            try:
                _pulse.stop()
            except Exception:
                pass
        if HARVEST_OK:
            try:
                _harvest.stop_clipboard_harvester()
            except Exception:
                pass
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec())


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        startup_log("launch")
        AIMonitorApp().run()
    except Exception:
        import traceback
        show_fatal_startup_error(traceback.format_exc())
        sys.exit(1)
