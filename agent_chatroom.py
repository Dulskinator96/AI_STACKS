"""
agent_chatroom.py — Sandboxed Multi-Agent Deliberation Environment.

The chatroom is a structured protocol where agents take sequential turns,
each reading the full conversation history and contributing their perspective.

Why sequential and not parallel:
    LLMs cannot truly run in parallel on a single Ollama instance. More importantly,
    genuine deliberation requires each agent to READ what the others said before responding.
    Sequential turns with full history = each agent builds on prior thought.
    This is how human expert panels actually work.

Protocol:
    Round 0  — Moderator opens with query + context framing
    Round 1  — Each agent gives opening statement (independent analysis)
               Tool calls are dispatched inline (TOOL: directives)
               Memory context injected from agent_memory.py
    Round N  — Each agent responds to specific points from prior round
               Cross-references by name: "@Validation, regarding your point..."
    Synthesis — SynthesisAgent reads full transcript → definitive answer
    Close    — Moderator extracts action items + open questions

Each agent message is stored in SQLite (chatroom.db) for recall in future sessions.
Agents can retrieve past chatroom sessions relevant to the current query.

Public API:
    ChatRoom(model, project_root)
    chatroom.run(query, code_context, callback) → ChatTranscript
    get_chatroom(model) → ChatRoom singleton
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from config import (
    CHATROOM_DB,
    CHATROOM_MAX_ROUNDS,
    CHATROOM_MAX_MSG_CHARS,
    DEFAULT_MODEL,
    ENGINEERING_CORE_PROMPT,
    AgentID,
    ExpertFramework,
)

try:
    from perceptual_engine import get_engine as _get_percept_engine
    _PERCEPT_OK = True
except ImportError:
    _PERCEPT_OK = False

_log = logging.getLogger("stratum.chatroom")

# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT    PRIMARY KEY,
    query       TEXT,
    status      TEXT    DEFAULT 'active',
    rounds      INTEGER DEFAULT 0,
    ts          REAL
);
CREATE TABLE IF NOT EXISTS messages (
    msg_id      TEXT    PRIMARY KEY,
    session_id  TEXT    NOT NULL,
    speaker_id  TEXT    NOT NULL,
    speaker_name TEXT   NOT NULL,
    speaker_emoji TEXT  DEFAULT '',
    content     TEXT    NOT NULL,
    round       INTEGER DEFAULT 0,
    turn        INTEGER DEFAULT 0,
    response_to TEXT    DEFAULT '',
    tool_results TEXT   DEFAULT '[]',
    ts          REAL
);
CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id, round);
"""


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ChatMessage:
    msg_id:        str
    session_id:    str
    speaker_id:    str
    speaker_name:  str
    speaker_emoji: str
    content:       str
    round:         int
    turn:          int
    response_to:   str                = ""
    tool_results:  list[str]          = field(default_factory=list)
    ts:            float              = field(default_factory=time.time)

    def to_context_line(self) -> str:
        tools = ""
        if self.tool_results:
            tools = "\n  [Tools used: " + "; ".join(self.tool_results[:2]) + "]"
        return (
            f"**{self.speaker_emoji} {self.speaker_name}** (R{self.round}):\n"
            f"{self.content}{tools}"
        )


@dataclass
class ChatTranscript:
    session_id: str
    query:      str
    messages:   list[ChatMessage]
    synthesis:  str
    rounds:     int
    total_ms:   float


# ── System prompts per agent ──────────────────────────────────────────────────

_CHATROOM_PERSONA: dict[str, dict] = {
    AgentID.VALIDATION: {
        "name":  "Validation",
        "emoji": "✓",
        "role":  (
            "You are the Validation Agent in a multi-expert deliberation.\n"
            "Your role: fact-check, challenge assumptions, verify sources, flag contradictions.\n"
            + ExpertFramework.VALIDATION
        ),
    },
    AgentID.IMPLEMENTATION: {
        "name":  "Implementation",
        "emoji": "💻",
        "role":  (
            "You are the Implementation Agent in a multi-expert deliberation.\n"
            "Your role: translate ideas into working code, identify integration points, flag technical blockers.\n"
            + ExpertFramework.IMPLEMENTATION
        ),
    },
    AgentID.PLANNER: {
        "name":  "Planner",
        "emoji": "📋",
        "role":  (
            "You are the Planning Agent in a multi-expert deliberation.\n"
            "Your role: identify knowledge gaps, propose research strategy, order work by impact.\n"
            + ExpertFramework.PLANNER
        ),
    },
    AgentID.STRATEGIST: {
        "name":  "Strategist",
        "emoji": "♟",
        "role":  (
            "You are the Strategist Agent in a multi-expert deliberation.\n"
            "Your role: long-term implications, systems thinking, risk/opportunity analysis.\n"
            + ExpertFramework.STRATEGIST
        ),
    },
    AgentID.SYNTHESIS: {
        "name":  "Synthesis",
        "emoji": "✦",
        "role":  (
            "You are the Synthesis Agent — master integrator.\n"
            "You read the full deliberation and produce the definitive unified answer.\n"
            + ExpertFramework.SYNTHESIS
        ),
    },
    AgentID.MODERATOR: {
        "name":  "Moderator",
        "emoji": "◈",
        "role":  (
            "You are the Moderator. You open deliberations, surface tensions, "
            "and extract final action items. Be concise and directive."
        ),
    },
}

_AGENT_ORDER = [
    AgentID.VALIDATION,
    AgentID.IMPLEMENTATION,
    AgentID.PLANNER,
    AgentID.STRATEGIST,
]

# Prepend ENGINEERING_CORE contract to every chatroom persona.
# The contract governs all agent reasoning under AI_MONITOR — verification,
# planning, strategy, synthesis, moderation, and implementation alike.
# Missing ENGINEERING_CORE.md → no-op (empty-string guard in config.py).
if ENGINEERING_CORE_PROMPT:
    for _persona in _CHATROOM_PERSONA.values():
        _persona["role"] = (
            ENGINEERING_CORE_PROMPT + "\n\n---\n\n" + _persona["role"]
        )


# ── Chatroom event ────────────────────────────────────────────────────────────

@dataclass
class ChatEvent:
    kind:       str     # "message" | "round_start" | "round_end" | "done" | "error"
    message:    Optional[ChatMessage] = None
    round:      int     = 0
    text:       str     = ""


ChatCallback = Callable[[ChatEvent], None]


# ── SQLite persistence ────────────────────────────────────────────────────────

class ChatStore:
    def __init__(self, db_path: Path = CHATROOM_DB):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()
        self._lock = threading.Lock()

    def save_session(self, session_id: str, query: str, rounds: int = 0) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions (session_id, query, rounds, ts)"
                " VALUES (?,?,?,?)",
                (session_id, query[:400], rounds, time.time()),
            )
            self._conn.commit()

    def save_message(self, msg: ChatMessage) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO messages"
                " (msg_id, session_id, speaker_id, speaker_name, speaker_emoji,"
                "  content, round, turn, response_to, tool_results, ts)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    msg.msg_id, msg.session_id, msg.speaker_id,
                    msg.speaker_name, msg.speaker_emoji,
                    msg.content[:1200], msg.round, msg.turn,
                    msg.response_to,
                    json.dumps(msg.tool_results),
                    msg.ts,
                ),
            )
            self._conn.commit()

    def recall_sessions(self, query: str, limit: int = 3) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM sessions ORDER BY ts DESC LIMIT 20"
        ).fetchall()
        from difflib import SequenceMatcher
        scored = sorted(
            [(dict(r), SequenceMatcher(None, query[:200], r["query"][:200]).ratio())
             for r in rows],
            key=lambda x: -x[1],
        )
        return [r for r, _ in scored[:limit]]

    def get_session_transcript(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY round, turn",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── ChatRoom orchestrator ─────────────────────────────────────────────────────

class ChatRoom:
    """
    Sandboxed multi-agent deliberation environment.

    Agents take turns reading the full conversation history and responding.
    Tool calls (TOOL: directives) are dispatched inline.
    Memory context injected per-agent from agent_memory.py.
    Full transcript stored in chatroom.db for cross-session recall.
    """

    def __init__(self, model: str = DEFAULT_MODEL,
                 project_root: Optional[str] = None):
        self._model = model
        self._store = ChatStore()
        self._project_root = project_root

    def run(
        self,
        query:        str,
        code_context: str,
        callback:     Optional[ChatCallback] = None,
        rounds:       int = CHATROOM_MAX_ROUNDS,
    ) -> ChatTranscript:
        """Run a full deliberation session and return the transcript."""
        t0         = time.time()
        session_id = _make_session_id(query)
        messages:  list[ChatMessage] = []
        _emit      = callback or (lambda e: None)

        self._store.save_session(session_id, query)

        # ── Past session recall (agents know what was discussed before) ────────
        past_context = self._recall_past_sessions(query)

        # ── R0: Moderator opens ────────────────────────────────────────────────
        _emit(ChatEvent(kind="round_start", round=0, text="Opening deliberation…"))
        opening = self._moderator_open(session_id, query, code_context, past_context)
        messages.append(opening)
        self._store.save_message(opening)
        _emit(ChatEvent(kind="message", message=opening, round=0))

        # ── Rounds 1..N ───────────────────────────────────────────────────────
        for rn in range(1, rounds + 1):
            _emit(ChatEvent(kind="round_start", round=rn,
                            text=f"Round {rn} — {'opening statements' if rn == 1 else 'cross-examination'}"))

            for turn, agent_id in enumerate(_AGENT_ORDER):
                persona = _CHATROOM_PERSONA[agent_id]
                try:
                    msg = self._agent_turn(
                        session_id   = session_id,
                        agent_id     = agent_id,
                        persona      = persona,
                        query        = query,
                        code_context = code_context,
                        history      = messages,
                        round_num    = rn,
                        turn         = turn,
                    )
                    messages.append(msg)
                    self._store.save_message(msg)
                    _emit(ChatEvent(kind="message", message=msg, round=rn))

                    # Store notable findings in agent episodic memory
                    self._update_agent_memory(agent_id, query, msg.content)

                except Exception as e:
                    _log.error(f"[R{rn}] {agent_id} turn error: {e}")
                    _emit(ChatEvent(kind="error", round=rn,
                                    text=f"{agent_id}: {e}"))

            _emit(ChatEvent(kind="round_end", round=rn))

        # ── Synthesis ─────────────────────────────────────────────────────────
        _emit(ChatEvent(kind="round_start", round=rounds + 1,
                        text="Synthesis — integrating full deliberation…"))
        synthesis_text = self._synthesize(session_id, query, code_context, messages)
        synth_msg = _make_message(
            session_id     = session_id,
            speaker_id     = AgentID.SYNTHESIS,
            persona        = _CHATROOM_PERSONA[AgentID.SYNTHESIS],
            content        = synthesis_text,
            round_num      = rounds + 1,
            turn           = 0,
        )
        messages.append(synth_msg)
        self._store.save_message(synth_msg)
        _emit(ChatEvent(kind="message", message=synth_msg, round=rounds + 1))

        # ── Moderator closes ──────────────────────────────────────────────────
        closing = self._moderator_close(session_id, query, synthesis_text, rounds + 2)
        messages.append(closing)
        self._store.save_message(closing)
        _emit(ChatEvent(kind="message", message=closing, round=rounds + 2))

        self._store.save_session(session_id, query, rounds=rounds)
        total_ms = (time.time() - t0) * 1000
        _emit(ChatEvent(kind="done", text=f"Deliberation complete in {total_ms/1000:.1f}s"))

        _log.info(
            f"Chatroom session {session_id[:8]} complete | "
            f"{len(messages)} messages | {total_ms/1000:.1f}s"
        )
        return ChatTranscript(
            session_id = session_id,
            query      = query,
            messages   = messages,
            synthesis  = synthesis_text,
            rounds     = rounds,
            total_ms   = total_ms,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _agent_turn(
        self,
        session_id:   str,
        agent_id:     str,
        persona:      dict,
        query:        str,
        code_context: str,
        history:      list[ChatMessage],
        round_num:    int,
        turn:         int,
    ) -> ChatMessage:
        from pyramid_ensemble import _ollama
        from agent_memory import get_memory
        from pyramid_tools import get_dispatcher

        memory = get_memory(agent_id)
        dispatcher = get_dispatcher()

        # Build history block
        history_block = self._format_history(history, max_chars=3000)

        # Memory context
        memory_ctx = memory.get_context_block(query)

        # Tool catalog
        tool_catalog = dispatcher._registry.list_tools()

        # Past similar sessions
        past = self._recall_past_sessions(query)

        # Perceptual context (neuroscience-grounded)
        percept_block = ""
        if _PERCEPT_OK:
            engine  = _get_percept_engine(agent_id)
            percept = engine.perceive(query, context_key=f"chatroom_r{round_num}", source="external")
            percept_block = percept.to_context_block()

        # Build prompt
        instruction = (
            "Give your perspective in 3-5 sentences. Be specific, reference prior speakers by name."
            if round_num > 1
            else "Give your opening analysis in 3-5 sentences. Use any tools you need."
        )

        prompt = f"""{persona['role']}

## Query Under Deliberation
{query}

## Code Context
{code_context[:1200]}

{past}

{percept_block}

## Conversation So Far
{history_block}

{memory_ctx}

{tool_catalog}

## Your Turn (Round {round_num}, {persona['name']})
{instruction}
You may call tools using: TOOL: tool_name | param=value
Speak in first person as {persona['name']}. Be direct, specific, expert-level."""

        raw, ms = _ollama(persona["role"], prompt, self._model)

        # Dispatch any tool calls inline
        if "TOOL:" in raw:
            raw = dispatcher.process(raw)

        content = raw.strip()[:CHATROOM_MAX_MSG_CHARS]

        # Detect response_to (did this agent address a specific prior speaker?)
        response_to = self._detect_response_to(content, history)

        msg = _make_message(
            session_id  = session_id,
            speaker_id  = agent_id,
            persona     = persona,
            content     = content,
            round_num   = round_num,
            turn        = turn,
            response_to = response_to,
        )
        _log.info(f"[R{round_num}T{turn}] {agent_id} | {ms:.0f}ms | {len(content)} chars")
        return msg

    def _moderator_open(
        self, session_id: str, query: str,
        code_context: str, past_context: str,
    ) -> ChatMessage:
        from pyramid_ensemble import _ollama
        prompt = (
            f"Query: {query}\n\n"
            f"Code context (excerpt):\n{code_context[:600]}\n\n"
            f"{past_context}\n\n"
            f"Open this deliberation session. In 2-3 sentences: frame the core question, "
            f"name the key tensions, and tell each specialist what to focus on."
        )
        raw, _ = _ollama(_CHATROOM_PERSONA[AgentID.MODERATOR]["role"], prompt, self._model)
        return _make_message(
            session_id = session_id,
            speaker_id = AgentID.MODERATOR,
            persona    = _CHATROOM_PERSONA[AgentID.MODERATOR],
            content    = raw.strip()[:CHATROOM_MAX_MSG_CHARS],
            round_num  = 0,
            turn       = 0,
        )

    def _synthesize(
        self, session_id: str, query: str,
        code_context: str, history: list[ChatMessage],
    ) -> str:
        from pyramid_ensemble import _ollama
        transcript = self._format_history(history, max_chars=4000)
        prompt = (
            f"## Original Query\n{query}\n\n"
            f"## Full Deliberation Transcript\n{transcript}\n\n"
            f"## Your Task\n"
            f"Apply the Feynman technique: synthesize the above into the definitive answer "
            f"that is MORE valuable than any single agent's perspective alone.\n"
            f"Structure:\n"
            f"1. CORE ANSWER (2-3 sentences)\n"
            f"2. CONSENSUS (where all agents agreed)\n"
            f"3. KEY TENSIONS (unresolved disagreements)\n"
            f"4. ACTION ITEMS (specific, ordered, actionable)\n"
            f"5. OPEN QUESTIONS (what still needs investigation)"
        )
        raw, _ = _ollama(_CHATROOM_PERSONA[AgentID.SYNTHESIS]["role"], prompt, self._model)
        return raw.strip()

    def _moderator_close(
        self, session_id: str, query: str,
        synthesis: str, round_num: int,
    ) -> ChatMessage:
        from pyramid_ensemble import _ollama
        prompt = (
            f"Deliberation complete. Synthesis:\n{synthesis[:600]}\n\n"
            f"Extract 3-5 concrete action items and 1-2 critical open questions."
        )
        raw, _ = _ollama(_CHATROOM_PERSONA[AgentID.MODERATOR]["role"], prompt, self._model)
        return _make_message(
            session_id = session_id,
            speaker_id = AgentID.MODERATOR,
            persona    = _CHATROOM_PERSONA[AgentID.MODERATOR],
            content    = raw.strip()[:CHATROOM_MAX_MSG_CHARS],
            round_num  = round_num,
            turn       = 99,
        )

    def _format_history(self, messages: list[ChatMessage], max_chars: int = 3000) -> str:
        lines = [m.to_context_line() for m in messages]
        full  = "\n\n".join(lines)
        if len(full) <= max_chars:
            return full
        # Truncate from the middle (keep first opening + most recent)
        half = max_chars // 2
        return full[:half] + "\n…[truncated]…\n" + full[-half:]

    def _recall_past_sessions(self, query: str) -> str:
        past = self._store.recall_sessions(query, limit=2)
        if not past:
            return ""
        lines = ["## Relevant Past Deliberations\n"]
        for s in past:
            lines.append(f"- [{s['session_id'][:8]}] {s['query'][:100]}")
        return "\n".join(lines)

    @staticmethod
    def _detect_response_to(content: str, history: list[ChatMessage]) -> str:
        """If the agent's message explicitly names a prior speaker, return their msg_id."""
        for msg in reversed(history[-6:]):
            if msg.speaker_name.lower() in content.lower():
                return msg.msg_id
        return ""

    @staticmethod
    def _update_agent_memory(agent_id: str, query: str, content: str) -> None:
        """Store notable findings in agent's episodic memory."""
        try:
            from agent_memory import get_memory
            mem = get_memory(agent_id)
            # Only store if content looks substantive
            if len(content) > 80 and not content.startswith("[Ollama"):
                mem.store_episodic(
                    content    = f"Q: {query[:80]}\nA: {content[:300]}",
                    tags       = ["chatroom", query[:30]],
                    importance = 0.6,
                )
        except Exception:
            _log.warning("swallowed exception")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session_id(query: str) -> str:
    import hashlib
    return hashlib.sha256(f"{query}{time.time()}".encode()).hexdigest()[:16]


def _make_message(
    session_id:  str,
    speaker_id:  str,
    persona:     dict,
    content:     str,
    round_num:   int,
    turn:        int,
    response_to: str = "",
) -> ChatMessage:
    msg_id = hashlib.sha256(
        f"{session_id}{speaker_id}{round_num}{turn}".encode()
    ).hexdigest()[:12]
    return ChatMessage(
        msg_id        = msg_id,
        session_id    = session_id,
        speaker_id    = speaker_id,
        speaker_name  = persona["name"],
        speaker_emoji = persona["emoji"],
        content       = content,
        round         = round_num,
        turn          = turn,
        response_to   = response_to,
    )


# ── Singleton ─────────────────────────────────────────────────────────────────

_chatroom: Optional[ChatRoom] = None


def get_chatroom(model: str = DEFAULT_MODEL,
                 project_root: Optional[str] = None) -> ChatRoom:
    global _chatroom
    if _chatroom is None:
        _chatroom = ChatRoom(model=model, project_root=project_root)
    return _chatroom
