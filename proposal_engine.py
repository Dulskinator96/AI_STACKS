"""
proposal_engine.py — LLM-as-proposal-engine with strict JSON schema enforcement.

The LLM NEVER executes anything. It produces a structured JSON proposal.
The schema validator rejects malformed output before it reaches the executor.
One retry on schema failure; hard-fail after that.

Pipeline position: code_correlator → [ProposalEngine] → executor
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from code_correlator import CorrelationResult
from config import ENGINEERING_CORE_PROMPT
from intent_engine import IntentClass, IntentResult

# ── Ollama config ────────────────────────────────────────────────────────────

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"
REQUEST_TIMEOUT = 120  # seconds


# ── Proposal schema ──────────────────────────────────────────────────────────
#
# Every LLM output MUST conform to this schema or it is rejected.
# No free-form text reaches the executor.

OPERATIONS = {"insert", "replace", "delete", "create_file", "explain", "research_note"}

PROPOSAL_SCHEMA = {
    "type": "object",
    "required": ["intent", "summary", "changes"],
    "properties": {
        "intent":   {"type": "string"},
        "summary":  {"type": "string", "maxLength": 400},
        "changes":  {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["operation", "file"],
                "properties": {
                    "operation":     {"type": "string", "enum": list(OPERATIONS)},
                    "file":          {"type": "string"},
                    "target_symbol": {"type": "string"},
                    "line_start":    {"type": "integer", "minimum": 1},
                    "line_end":      {"type": "integer", "minimum": 1},
                    "content":       {"type": "string"},
                    "reason":        {"type": "string", "maxLength": 200},
                },
            },
        },
        "risks":        {"type": "array", "items": {"type": "string"}},
        "assumptions":  {"type": "array", "items": {"type": "string"}},
        "confidence":   {"type": "number", "minimum": 0, "maximum": 1},
    },
}


# ── Validation ────────────────────────────────────────────────────────────────

class SchemaError(Exception):
    pass


def _validate_proposal(data: dict) -> None:
    required = PROPOSAL_SCHEMA["required"]
    for key in required:
        if key not in data:
            raise SchemaError(f"Missing required field: '{key}'")

    if not isinstance(data.get("changes"), list):
        raise SchemaError("'changes' must be a list")

    for i, change in enumerate(data["changes"]):
        if not isinstance(change, dict):
            raise SchemaError(f"changes[{i}] must be an object")
        if "operation" not in change:
            raise SchemaError(f"changes[{i}] missing 'operation'")
        if change["operation"] not in OPERATIONS:
            raise SchemaError(
                f"changes[{i}] unknown operation '{change['operation']}'. "
                f"Must be one of: {sorted(OPERATIONS)}"
            )
        if "file" not in change:
            raise SchemaError(f"changes[{i}] missing 'file'")

        op = change["operation"]
        if op in {"insert", "replace", "create_file"} and "content" not in change:
            raise SchemaError(f"changes[{i}] operation '{op}' requires 'content'")

    if "confidence" in data:
        c = data["confidence"]
        if not isinstance(c, (int, float)) or not (0 <= c <= 1):
            raise SchemaError(f"'confidence' must be 0–1, got {c!r}")


def _extract_json_block(text: str) -> str:
    """Pull the first ```json ... ``` or bare {{ ... }} from LLM output."""
    # 1. Fenced block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        return m.group(1)
    # 2. Bare JSON object (greedy from first { to last })
    m = re.search(r"(\{.*\})", text, re.S)
    if m:
        return m.group(1)
    return text


# ── Prompt construction ───────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a code proposal engine. You NEVER execute code. You ONLY output structured JSON proposals.

Rules:
1. Output ONLY a single JSON object matching the schema below — no prose, no markdown outside the JSON.
2. Every "changes" item must have: operation, file, content (if mutating), reason.
3. Never invent file paths that were not in the provided context unless operation is "create_file".
4. Confidence: 0.0 = guessing, 1.0 = certain. Be honest.
5. If the intent is EXPLAIN or RESEARCH, use operation "explain" or "research_note" with content as the answer — no file mutations.

JSON Schema:
{
  "intent":      "<IntentClass string>",
  "summary":     "<one sentence what this proposal does>",
  "changes": [
    {
      "operation":     "insert | replace | delete | create_file | explain | research_note",
      "file":          "<relative path>",
      "target_symbol": "<function or class name — omit if line-based>",
      "line_start":    <integer — 1-indexed, omit if symbol-based>,
      "line_end":      <integer>,
      "content":       "<new content as string>",
      "reason":        "<why this change>"
    }
  ],
  "risks":       ["<potential side effect>"],
  "assumptions": ["<assumption made>"],
  "confidence":  <0.0-1.0>
}
"""

# Prepend ENGINEERING_CORE contract to the proposal-engine system prompt.
# Empty-string fallback means a missing ENGINEERING_CORE.md is a no-op.
if ENGINEERING_CORE_PROMPT:
    _SYSTEM_PROMPT = ENGINEERING_CORE_PROMPT + "\n\n---\n\n" + _SYSTEM_PROMPT


def _build_user_prompt(
    intent:      IntentResult,
    correlation: CorrelationResult,
) -> str:
    context_block = correlation.to_context_block()
    constraints = "\n".join(
        f"  - {c.kind.value}: {c.value}" for c in intent.constraints
    ) or "  (none)"

    return f"""\
## Query
{intent.raw_query}

## Intent
Class: {intent.intent_class.value}
Keywords: {', '.join(intent.keywords[:10])}
Confidence: {intent.confidence:.2f}

## Constraints
{constraints}

## Codebase Context
{context_block}

## Task
Produce a JSON proposal satisfying the query under the given constraints.
Use ONLY the files/symbols shown above unless operation is create_file.
"""


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class ChangeItem:
    operation:     str
    file:          str
    target_symbol: Optional[str] = None
    line_start:    Optional[int] = None
    line_end:      Optional[int] = None
    content:       Optional[str] = None
    reason:        Optional[str] = None


@dataclass
class Proposal:
    intent:      str
    summary:     str
    changes:     list[ChangeItem]
    risks:       list[str]        = field(default_factory=list)
    assumptions: list[str]        = field(default_factory=list)
    confidence:  float            = 0.5
    raw_json:    dict             = field(default_factory=dict)
    timestamp:   float            = field(default_factory=time.time)
    retry_used:  bool             = False

    def is_read_only(self) -> bool:
        return all(c.operation in {"explain", "research_note"} for c in self.changes)

    def to_dict(self) -> dict:
        return {
            "intent":      self.intent,
            "summary":     self.summary,
            "changes":     [
                {k: v for k, v in {
                    "operation":     c.operation,
                    "file":          c.file,
                    "target_symbol": c.target_symbol,
                    "line_start":    c.line_start,
                    "line_end":      c.line_end,
                    "content":       c.content,
                    "reason":        c.reason,
                }.items() if v is not None}
                for c in self.changes
            ],
            "risks":       self.risks,
            "assumptions": self.assumptions,
            "confidence":  self.confidence,
            "retry_used":  self.retry_used,
        }


@dataclass
class ProposalResult:
    success:   bool
    proposal:  Optional[Proposal] = None
    error:     Optional[str]      = None
    raw_llm:   Optional[str]      = None
    duration:  float              = 0.0


# ── Engine ────────────────────────────────────────────────────────────────────

class ProposalEngine:
    def __init__(
        self,
        model:      str = OLLAMA_MODEL,
        ollama_url: str = OLLAMA_URL,
        timeout:    int = REQUEST_TIMEOUT,
    ):
        self.model      = model
        self.ollama_url = ollama_url
        self.timeout    = timeout

    def _call_llm(self, user_prompt: str, temperature: float = 0.25) -> str:
        payload = {
            "model":  self.model,
            "prompt": _SYSTEM_PROMPT + "\n\n" + user_prompt,
            "stream": False,
            "options": {
                "temperature":    temperature,
                "repeat_penalty": 1.1,
                "num_predict":    2048,
            },
        }
        resp = requests.post(self.ollama_url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("response", "")

    def _parse_and_validate(self, raw: str) -> dict:
        extracted = _extract_json_block(raw)
        try:
            data = json.loads(extracted)
        except json.JSONDecodeError as e:
            raise SchemaError(f"JSON parse failed: {e}") from e
        _validate_proposal(data)
        return data

    def _dict_to_proposal(self, data: dict, retry_used: bool = False) -> Proposal:
        changes = [
            ChangeItem(
                operation     = c["operation"],
                file          = c["file"],
                target_symbol = c.get("target_symbol"),
                line_start    = c.get("line_start"),
                line_end      = c.get("line_end"),
                content       = c.get("content"),
                reason        = c.get("reason"),
            )
            for c in data["changes"]
        ]
        return Proposal(
            intent      = data["intent"],
            summary     = data["summary"],
            changes     = changes,
            risks       = data.get("risks", []),
            assumptions = data.get("assumptions", []),
            confidence  = float(data.get("confidence", 0.5)),
            raw_json    = data,
            retry_used  = retry_used,
        )

    def generate(
        self,
        intent:      IntentResult,
        correlation: CorrelationResult,
        temperature: float = 0.25,
    ) -> ProposalResult:
        t0 = time.time()
        user_prompt = _build_user_prompt(intent, correlation)

        # Attempt 1
        try:
            raw = self._call_llm(user_prompt, temperature)
        except requests.RequestException as e:
            return ProposalResult(success=False, error=f"Ollama connection failed: {e}",
                                  duration=time.time() - t0)

        try:
            data = self._parse_and_validate(raw)
            proposal = self._dict_to_proposal(data, retry_used=False)
            return ProposalResult(success=True, proposal=proposal,
                                  raw_llm=raw, duration=time.time() - t0)
        except SchemaError as e1:
            pass  # fall through to retry

        # Retry with explicit correction nudge
        retry_prompt = (
            user_prompt
            + f"\n\nYour previous output was rejected by the schema validator.\n"
              f"Validation error: {e1}\n"
              f"Output ONLY a single valid JSON object — no prose."
        )
        try:
            raw2 = self._call_llm(retry_prompt, temperature=0.1)
            data2 = self._parse_and_validate(raw2)
            proposal2 = self._dict_to_proposal(data2, retry_used=True)
            return ProposalResult(success=True, proposal=proposal2,
                                  raw_llm=raw2, duration=time.time() - t0)
        except (SchemaError, requests.RequestException) as e2:
            return ProposalResult(
                success  = False,
                error    = f"Schema validation failed after retry. First: {e1} | Retry: {e2}",
                raw_llm  = raw,
                duration = time.time() - t0,
            )


_engine: Optional[ProposalEngine] = None

def get_engine(model: str = OLLAMA_MODEL) -> ProposalEngine:
    global _engine
    if _engine is None:
        _engine = ProposalEngine(model=model)
    return _engine
