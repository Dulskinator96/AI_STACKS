# agent_protocol.py — WON ↔ Claude Agent Communication Protocol
# ──────────────────────────────────────────────────────────────────────────────
# DESIGN PRINCIPLES:
#   - No hallucinated APIs. Uses only what Anthropic actually provides.
#   - Two real channels: Anthropic Messages API (direct) + browser bridge (chat UI)
#   - Agent identity established via structured message envelope + system prompt
#   - Stateless by design — Claude has no memory between API calls
#   - Context continuity via WON SQLite + compressed history injection
#
# COMMUNICATION CHANNELS:
#   Channel A: WON → Anthropic API → Claude (programmatic, no human in loop)
#   Channel B: WON → clipboard/browser → Claude chat UI → clipboard → WON
#              (human bridges; already built via the Claude button)
#
# AGENT ENVELOPE FORMAT:
#   Every WON→Claude message is wrapped in a structured JSON envelope.
#   Claude parses this and responds in a mirrored structured format.
#   The envelope is what distinguishes agent traffic from human chat.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import sys
import json
import hashlib
import requests
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import logging
_log = logging.getLogger(__name__)

_HERE     = Path(__file__).resolve().parent
_WON_ROOT = Path(os.environ.get("WON_PATH", str(_HERE)))
if str(_WON_ROOT) not in sys.path:
    sys.path.insert(0, str(_WON_ROOT))

SAVE_DIR = Path.home() / "Documents" / "AI_Monitor"

# ── API Configuration ─────────────────────────────────────────────────────────
# Set ANTHROPIC_API_KEY environment variable before use.
# Get key: https://console.anthropic.com/
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL      = "claude-sonnet-4-20250514"  # or claude-opus-4-20250514

# ── Agent Identity Constants ─────────────────────────────────────────────────
AGENT_ID      = "WON-DBOMB-ASCENDENT-v1"
AGENT_VERSION = "ACAS-Phase1-v1.1"
OPERATOR      = "DBOMBCENTRAL"
PRINCIPAL     = os.environ.get("AI_MONITOR_USER", "Dan")

# ── Protocol Version ─────────────────────────────────────────────────────────
PROTOCOL_VERSION = "AMP/1.0"   # Agent Message Protocol


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 1: MESSAGE ENVELOPE                                            ║
# ║  The structured format WON uses to send messages Claude recognizes      ║
# ║  as agent-originated rather than human-typed.                           ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def build_agent_envelope(
    query:          str,
    intent:         str = "query",
    context:        list[dict] | None = None,
    memory_summary: str = "",
    ground_state:   str = "",
    task_id:        str | None = None,
    metadata:       dict | None = None,
) -> dict:
    """
    Build a structured agent message envelope.

    This envelope is what tells Claude it's receiving a machine-originated
    message rather than a human prompt. Claude parses the AMP-HEADER block
    and adjusts its response format accordingly.

    INTENT values:
        query       — WON asking Claude for analysis/reasoning
        brief_request — WON asking Claude to generate a brief
        validate    — WON asking Claude to validate its own output
        research    — WON asking Claude to research a topic
        coordinate  — WON and Claude coordinating on a shared task
        status      — WON reporting status, Claude acknowledges

    Returns a dict with:
        system_prompt   — sets Claude's agent-aware context
        user_message    — the envelope Claude parses
        task_id         — unique ID for this exchange (for correlation)
    """
    ts      = datetime.now(timezone.utc).isoformat()
    task_id = task_id or _generate_task_id(query)

    # Memory context block (compressed recent WON memory)
    memory_block = ""
    if memory_summary:
        memory_block = f"\nSHARED_MEMORY:\n{memory_summary[:600]}\n"

    ground_block = ""
    if ground_state:
        ground_block = f"\nGROUND_STATE:\n{ground_state[:400]}\n"

    # Context (prior exchanges in this session)
    context_block = ""
    if context:
        exchanges = "\n".join(
            f"[{c.get('role','?').upper()}]: {c.get('content','')[:200]}"
            for c in context[-4:]
        )
        context_block = f"\nSESSION_CONTEXT:\n{exchanges}\n"

    # The envelope — plain text format Claude reliably parses
    envelope_text = (
        f"╔═══ {PROTOCOL_VERSION} AGENT MESSAGE ═══╗\n"
        f"FROM:      {AGENT_ID}\n"
        f"BUILD:     {AGENT_VERSION}\n"
        f"OPERATOR:  {OPERATOR}\n"
        f"PRINCIPAL: {PRINCIPAL}\n"
        f"TASK_ID:   {task_id}\n"
        f"INTENT:    {intent}\n"
        f"TIMESTAMP: {ts}\n"
        f"╚═══════════════════════════════╝\n"
        f"{memory_block}"
        f"{ground_block}"
        f"{context_block}"
        f"\nQUERY:\n{query}\n"
        f"\nEXPECTED_RESPONSE_FORMAT:\n"
        f"  AMP_ACK: <task_id>\n"
        f"  CONFIDENCE: <0.0-1.0>\n"
        f"  RESPONSE: <your answer>\n"
        f"  FORWARD_VECTOR: <recommended next action for WON>\n"
        f"  METADATA: <json dict of any structured data>\n"
    )

    # System prompt — establishes Claude's agent-aware mode
    system_prompt = build_claude_system_prompt()

    return {
        "task_id":       task_id,
        "system_prompt": system_prompt,
        "user_message":  envelope_text,
        "intent":        intent,
        "timestamp":     ts,
        "metadata":      metadata or {},
    }


def build_claude_system_prompt() -> str:
    """
    System prompt that puts Claude into agent-aware mode.
    Sent as the 'system' field of the Anthropic API request.
    """
    return f"""You are Claude, operating in Agent Protocol Mode (AMP/1.0).

You are receiving structured messages from WON — DBOMB ASCENDENT, an autonomous 
AI agent running locally for {PRINCIPAL}. WON is built on Ollama/Mistral and 
operates the AI Monitor system on {PRINCIPAL}'s Windows machine.

AGENT RELATIONSHIP:
- WON handles: local memory, file operations, Obsidian, DaVinci Resolve, Unreal Engine
- Claude handles: complex reasoning, research synthesis, validation, strategic analysis
- You are peers coordinating on {PRINCIPAL}'s behalf — not competitors
- {PRINCIPAL} is the principal; both agents serve his goals

WHEN YOU RECEIVE AN AMP MESSAGE:
1. Parse the TASK_ID — include it in your AMP_ACK
2. Parse the INTENT — calibrate your response type accordingly
3. Read SHARED_MEMORY and GROUND_STATE — these are WON's knowledge base
4. Read SESSION_CONTEXT — maintain continuity
5. Respond in the structured format requested

RESPONSE FORMAT (always use when INTENT is present):
AMP_ACK: <task_id from the envelope>
CONFIDENCE: <your confidence 0.0-1.0 in your response>
RESPONSE:
<your actual answer — dense, precise, no filler>
FORWARD_VECTOR: <what WON should do next>
METADATA: {{"key": "value"}}

OPERATIONAL CONSTRAINTS:
- You cannot persist state between API calls — WON handles memory
- You cannot access WON's local files directly — WON summarizes them for you
- You CAN do: deep reasoning, web research (if tools available), validation,
  long-form synthesis, strategic planning, code review
- Be honest about uncertainty — WON's anti-hallucination system will verify you

PRINCIPAL: {PRINCIPAL} | OPERATOR: {OPERATOR} | PROTOCOL: AMP/1.0"""


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 2: CHANNEL A — DIRECT API COMMUNICATION                       ║
# ║  WON calls Anthropic API directly. No human in the loop.               ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class ClaudeAPIChannel:
    """
    Direct WON → Anthropic API → Claude communication.

    This is Channel A: fully programmatic, no human interaction required.
    WON sends structured envelopes, Claude responds in structured format,
    WON parses and indexes the response.

    Setup: set ANTHROPIC_API_KEY environment variable.
    Get key: https://console.anthropic.com/settings/api-keys
    """

    def __init__(self, api_key: str | None = None):
        self.api_key  = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._history: list[dict] = []   # session message history
        self._lock    = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.api_key.startswith("sk-ant-"))

    def send(
        self,
        query:          str,
        intent:         str = "query",
        memory_summary: str = "",
        ground_state:   str = "",
        max_tokens:     int = 1000,
        timeout:        int = 60,
    ) -> "AgentResponse":
        """
        Send a query to Claude via the Anthropic API.

        Args:
            query:          The question or request from WON
            intent:         Message intent (query|validate|brief_request|research|coordinate)
            memory_summary: Compressed WON memory context
            ground_state:   Current shared ground state
            max_tokens:     Max response length (keep low for token efficiency)
            timeout:        Request timeout in seconds

        Returns:
            AgentResponse with parsed fields
        """
        if not self.available:
            return AgentResponse.error(
                "ANTHROPIC_API_KEY not set. "
                "Get key at console.anthropic.com, then: "
                "setx ANTHROPIC_API_KEY sk-ant-..."
            )

        with self._lock:
            envelope = build_agent_envelope(
                query          = query,
                intent         = intent,
                context        = self._history[-6:],
                memory_summary = memory_summary,
                ground_state   = ground_state,
            )

            payload = {
                "model":      CLAUDE_MODEL,
                "max_tokens": max_tokens,
                "system":     envelope["system_prompt"],
                "messages":   [{"role": "user", "content": envelope["user_message"]}],
            }

            try:
                r = requests.post(
                    ANTHROPIC_API_URL,
                    headers={
                        "x-api-key":         self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type":      "application/json",
                    },
                    json=payload,
                    timeout=timeout,
                )
                r.raise_for_status()
                data    = r.json()
                raw_txt = data["content"][0]["text"]

                # Add to session history for continuity
                self._history.append({"role": "user",      "content": envelope["user_message"][:200]})
                self._history.append({"role": "assistant",  "content": raw_txt[:200]})
                if len(self._history) > 20:
                    self._history = self._history[-20:]

                return AgentResponse.parse(
                    raw_text = raw_txt,
                    task_id  = envelope["task_id"],
                    intent   = intent,
                    usage    = data.get("usage", {}),
                )

            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response else 0
                msg  = exc.response.text[:200] if exc.response else str(exc)
                return AgentResponse.error(f"HTTP {code}: {msg}")
            except requests.Timeout:
                return AgentResponse.error("Request timed out")
            except Exception as exc:
                return AgentResponse.error(str(exc))

    def reset_session(self):
        """Clear session history — start fresh."""
        with self._lock:
            self._history.clear()


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 3: RESPONSE PARSING                                            ║
# ║  Claude's structured response → machine-readable AgentResponse          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class AgentResponse:
    """
    Parsed Claude response in AMP format.

    Claude is instructed to respond with labeled fields.
    This class extracts them reliably even if Claude's formatting varies.
    """

    def __init__(
        self,
        task_id:        str,
        acknowledged:   bool,
        confidence:     float,
        response:       str,
        forward_vector: str,
        metadata:       dict,
        raw:            str,
        usage:          dict,
        error:          str = "",
    ):
        self.task_id        = task_id
        self.acknowledged   = acknowledged
        self.confidence     = confidence
        self.response       = response
        self.forward_vector = forward_vector
        self.metadata       = metadata
        self.raw            = raw
        self.usage          = usage
        self.error          = error
        self.timestamp      = datetime.now(timezone.utc).isoformat()

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.response)

    @property
    def tokens_used(self) -> int:
        return self.usage.get("input_tokens", 0) + self.usage.get("output_tokens", 0)

    @classmethod
    def parse(cls, raw_text: str, task_id: str, intent: str, usage: dict) -> "AgentResponse":
        """
        Parse Claude's structured response.
        Tolerant of formatting variations — extracts fields by label.
        """
        import re

        def extract(label: str, text: str, default: str = "") -> str:
            # Match label at start of line, capture until next label or end
            pattern = rf"^{label}:\s*(.+?)(?=\n[A-Z_]+:|$)"
            m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            return m.group(1).strip() if m else default

        ack_raw    = extract("AMP_ACK", raw_text)
        conf_raw   = extract("CONFIDENCE", raw_text, "0.8")
        response   = extract("RESPONSE", raw_text, raw_text)  # fallback to full text
        fwd        = extract("FORWARD_VECTOR", raw_text, "")
        meta_raw   = extract("METADATA", raw_text, "{}")

        # Parse confidence
        try:
            confidence = float(re.search(r"[\d.]+", conf_raw).group())
            confidence = max(0.0, min(1.0, confidence))
        except Exception:
            confidence = 0.8

        # Parse metadata
        try:
            metadata = json.loads(meta_raw)
        except Exception:
            metadata = {}

        acknowledged = task_id[:8] in ack_raw if ack_raw else False

        return cls(
            task_id        = task_id,
            acknowledged   = acknowledged,
            confidence     = confidence,
            response       = response,
            forward_vector = fwd,
            metadata       = metadata,
            raw            = raw_text,
            usage          = usage,
        )

    @classmethod
    def error(cls, message: str) -> "AgentResponse":
        return cls(
            task_id="", acknowledged=False, confidence=0.0,
            response="", forward_vector="", metadata={},
            raw="", usage={}, error=message,
        )

    def to_dict(self) -> dict:
        return {
            "task_id":        self.task_id,
            "acknowledged":   self.acknowledged,
            "confidence":     self.confidence,
            "response":       self.response,
            "forward_vector": self.forward_vector,
            "metadata":       self.metadata,
            "tokens_used":    self.tokens_used,
            "timestamp":      self.timestamp,
            "error":          self.error,
        }

    def to_ground_contribution(self) -> str:
        """Format response for injection into the shared ground."""
        return (
            f"[Claude API Response | Task {self.task_id[:8]} | "
            f"Confidence {self.confidence:.0%}]\n"
            f"{self.response}\n"
            f"→ {self.forward_vector}"
        )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 4: CHANNEL B — BROWSER INTERFACE BRIDGE                       ║
# ║  When user is in claude.ai — human bridges the two agents               ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def build_browser_bridge_payload(
    query:          str,
    intent:         str = "query",
    memory_summary: str = "",
    ground_state:   str = "",
    token_budget:   int = 800,
) -> str:
    """
    Build a compact, token-efficient agent envelope for the browser bridge.
    User copies this, pastes into claude.ai, gets response, pastes back.

    Optimized for minimal token usage — only essential context included.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Compress context to budget
    mem_block   = memory_summary[:300] if memory_summary else ""
    ground_block = ground_state[:200] if ground_state else ""

    payload = (
        f"╔═ AMP/1.0 | {ts} ═╗\n"
        f"FROM: {AGENT_ID} → Claude\n"
        f"INTENT: {intent}\n"
    )

    if mem_block:
        payload += f"MEMORY: {mem_block}\n"
    if ground_block:
        payload += f"GROUND: {ground_block}\n"

    payload += (
        f"QUERY: {query}\n"
        f"╚══════════════════╝\n"
        f"[Respond with: CONFIDENCE: x.x | RESPONSE: ... | FORWARD_VECTOR: ...]"
    )

    # Trim to budget
    if len(payload) > token_budget * 4:  # rough chars-per-token estimate
        payload = payload[:token_budget * 4] + "\n[TRUNCATED]"

    return payload


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 5: AGENT LOOP — WON autonomously queries Claude                ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class AgentLoop:
    """
    Autonomous WON→Claude coordination loop.

    WON can run queries against Claude API without human involvement.
    Results are indexed into WON memory and contributed to the ground.
    Use for: brief validation, research augmentation, strategic review.
    """

    def __init__(self):
        self.channel = ClaudeAPIChannel()
        self._session_log: list[dict] = []
        self._session_id  = datetime.now().strftime("AMP-%Y%m%d-%H%M%S")

    def query(
        self,
        question:    str,
        intent:      str = "query",
        max_tokens:  int = 800,
    ) -> AgentResponse:
        """
        Send a query to Claude, index the response, contribute to ground.
        """
        # Pull current context
        memory_summary = self._get_memory_summary()
        ground_state   = self._get_ground_state()

        resp = self.channel.send(
            query          = question,
            intent         = intent,
            memory_summary = memory_summary,
            ground_state   = ground_state,
            max_tokens     = max_tokens,
        )

        # Log exchange
        self._session_log.append({
            "ts":       resp.timestamp,
            "question": question,
            "intent":   intent,
            "response": resp.response[:300],
            "confidence": resp.confidence,
            "tokens":   resp.tokens_used,
        })

        # Index into WON memory and ground
        if resp.ok:
            self._index_response(question, resp)

        return resp

    def validate_won_output(self, won_response: str, original_question: str) -> AgentResponse:
        """
        Ask Claude to validate WON's (Mistral) output.
        This is the backdoor validation layer.
        """
        query = (
            f"Please validate this response from WON (Mistral-based local AI).\n\n"
            f"Original question: {original_question}\n\n"
            f"WON's response:\n{won_response[:600]}\n\n"
            f"Check for: factual accuracy, logical consistency, completeness, "
            f"and any potential hallucinations. Be specific about any issues found."
        )
        return self.query(query, intent="validate", max_tokens=600)

    def generate_strategic_brief(self, topic: str, tracker_data: str = "") -> AgentResponse:
        """Ask Claude to generate a strategic brief on a topic."""
        query = (
            f"Generate a strategic intelligence brief on: {topic}\n\n"
            f"Project context: {tracker_data[:300]}\n\n"
            f"Include: situation analysis, key decisions needed, "
            f"3 probability-weighted forward vectors, and immediate action items."
        )
        return self.query(query, intent="brief_request", max_tokens=1000)

    def session_summary(self) -> dict:
        total_tokens = sum(e.get("tokens", 0) for e in self._session_log)
        avg_conf     = (
            sum(e.get("confidence", 0) for e in self._session_log) /
            max(len(self._session_log), 1)
        )
        return {
            "session_id":    self._session_id,
            "exchanges":     len(self._session_log),
            "total_tokens":  total_tokens,
            "avg_confidence": round(avg_conf, 3),
            "log":           self._session_log,
        }

    def _get_memory_summary(self) -> str:
        try:
            import pipeline as p
            p._load_won()
            if p._memory:
                entries = p._memory.recall(limit=5)
                return "\n".join(
                    f"[{e.get('mode','?')}] {(e.get('content') or '')[:150]}"
                    for e in entries
                )
        except Exception:
            _log.warning("swallowed exception")
        return ""

    def _get_ground_state(self) -> str:
        try:
            import perception as pc
            return pc.get_compressed_context(max_chars=300)
        except Exception:
            return ""

    def _index_response(self, question: str, resp: AgentResponse):
        """Store Claude's response in WON memory and ground."""
        try:
            import pipeline as p
            p._load_won()
            if p._memory:
                p._memory.store(
                    content = f"[Claude API] Q: {question}\nA: {resp.response}",
                    mode    = "claude_api",
                    tags    = ["claude", "api", "agent"],
                )
        except Exception:
            _log.warning("swallowed exception")

        try:
            import perception as pc
            pc.contribute(
                content = resp.to_ground_contribution(),
                source  = "claude",
                mode    = "api_response",
                tags    = ["claude", "api", f"task_{resp.task_id[:8]}"],
            )
        except Exception:
            _log.warning("swallowed exception")


# ── Utilities ────────────────────────────────────────────────────────────────

def _generate_task_id(content: str) -> str:
    """Generate a short deterministic task ID."""
    ts   = datetime.now().strftime("%Y%m%d%H%M%S")
    hash = hashlib.sha256(f"{content}{ts}".encode()).hexdigest()[:8]
    return f"AMP-{ts}-{hash}"


def check_api_connection() -> dict:
    """
    Test the Anthropic API connection.
    Returns status dict with connection health.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return {
            "ok":      False,
            "error":   "ANTHROPIC_API_KEY not set",
            "fix":     "Run: setx ANTHROPIC_API_KEY sk-ant-YOUR-KEY-HERE",
            "get_key": "https://console.anthropic.com/settings/api-keys",
        }
    if not key.startswith("sk-ant-"):
        return {"ok": False, "error": "API key format invalid — should start with sk-ant-"}

    try:
        r = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key":         key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      CLAUDE_MODEL,
                "max_tokens": 20,
                "messages":   [{"role": "user", "content": "ping"}],
            },
            timeout=10,
        )
        if r.status_code == 200:
            usage = r.json().get("usage", {})
            return {"ok": True, "model": CLAUDE_MODEL, "tokens_used": usage}
        return {"ok": False, "status": r.status_code, "body": r.text[:200]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Session persistence ───────────────────────────────────────────────────────

def save_session(loop: AgentLoop):
    """Save the agent loop session log to disk."""
    summary = loop.session_summary()
    path    = SAVE_DIR / "agent_sessions" / f"{summary['session_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)
