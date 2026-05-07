"""
intent_engine.py — Intent classification and structured query parsing.

Classifies user input into a deterministic IntentClass and produces a
structured IntentResult that drives everything downstream. No LLM involved
at this stage — pure rule-based + pattern classification.

Pipeline position: INPUT → [IntentEngine] → code_correlator
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# ── Intent taxonomy ──────────────────────────────────────────────────────────

class IntentClass(str, Enum):
    CREATE   = "CREATE"    # build new file / class / function / feature
    MODIFY   = "MODIFY"    # change existing behaviour in known location
    DEBUG    = "DEBUG"     # diagnose error / unexpected behaviour
    EXPLAIN  = "EXPLAIN"   # describe what code does
    AUDIT    = "AUDIT"     # security / quality / performance review
    RESEARCH = "RESEARCH"  # gather information, no code change
    GENERATE = "GENERATE"  # produce artifact (test, doc, migration, schema)
    REFACTOR = "REFACTOR"  # restructure without changing behaviour
    UNKNOWN  = "UNKNOWN"   # fallback; ask user to clarify


# ── Constraint types ─────────────────────────────────────────────────────────

class ConstraintKind(str, Enum):
    SCOPE_FILE    = "scope_file"     # limit to specific file
    SCOPE_SYMBOL  = "scope_symbol"   # limit to class / function name
    PRESERVE      = "preserve"       # must not touch X
    LANGUAGE      = "language"       # target language override
    MAX_LINES     = "max_lines"      # response brevity hint
    STYLE         = "style"          # coding style instruction
    ROLLBACK      = "rollback"       # safe-mode: always snapshot first
    DRY_RUN       = "dry_run"        # propose but don't execute


@dataclass
class Constraint:
    kind:  ConstraintKind
    value: str


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class IntentTarget:
    """A file or symbol the intent is aimed at."""
    path:        Optional[str] = None   # relative or absolute
    symbol:      Optional[str] = None   # class/function name
    line_hint:   Optional[int] = None   # rough line number if mentioned
    confidence:  float         = 1.0


@dataclass
class IntentResult:
    intent_class: IntentClass
    raw_query:    str
    targets:      list[IntentTarget]       = field(default_factory=list)
    constraints:  list[Constraint]         = field(default_factory=list)
    keywords:     list[str]                = field(default_factory=list)
    confidence:   float                    = 1.0
    ambiguous:    bool                     = False
    clarification_needed: Optional[str]    = None
    timestamp:    float                    = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "intent_class": self.intent_class.value,
            "raw_query":    self.raw_query,
            "targets":      [
                {"path": t.path, "symbol": t.symbol, "line_hint": t.line_hint,
                 "confidence": t.confidence}
                for t in self.targets
            ],
            "constraints":  [{"kind": c.kind.value, "value": c.value}
                              for c in self.constraints],
            "keywords":     self.keywords,
            "confidence":   self.confidence,
            "ambiguous":    self.ambiguous,
            "timestamp":    self.timestamp,
        }


# ── Pattern tables ───────────────────────────────────────────────────────────

# Each entry: (regex_pattern, IntentClass, base_confidence)
# Ordered by specificity — first match wins unless overridden by score
_PATTERNS: list[tuple[re.Pattern, IntentClass, float]] = [
    # DEBUG
    (re.compile(r"\b(error|exception|traceback|crash|fails?|broken|bug|not working|wrong output)\b", re.I), IntentClass.DEBUG, 0.85),
    (re.compile(r"\b(debug|fix|repair|resolve|trace|step through|why (is|does|doesn't|isn't))\b", re.I), IntentClass.DEBUG, 0.80),

    # AUDIT
    (re.compile(r"\b(audit|security|vuln|owasp|injection|xss|csrf|exposure|risk|threat)\b", re.I), IntentClass.AUDIT, 0.90),
    (re.compile(r"\b(review|check for issues|inspect)\b", re.I), IntentClass.AUDIT, 0.65),

    # MODIFY
    (re.compile(r"\b(change|update|modify|edit|alter|tweak|adjust|replace|rename|move)\b", re.I), IntentClass.MODIFY, 0.80),
    (re.compile(r"\b(add (a |an )?(parameter|argument|field|property|method|attribute))\b", re.I), IntentClass.MODIFY, 0.85),

    # CREATE
    (re.compile(r"\b(create|build|write|implement|make|new|add (a |an )?(class|module|file|function|endpoint|route|component))\b", re.I), IntentClass.CREATE, 0.80),

    # GENERATE
    (re.compile(r"\b(generate|scaffold|produce|emit|output|template|boilerplate)\b", re.I), IntentClass.GENERATE, 0.80),
    (re.compile(r"\b(test(s|suite|case)?|migration|schema|doc(umentation)?|type stub)\b", re.I), IntentClass.GENERATE, 0.70),

    # REFACTOR
    (re.compile(r"\b(refactor|restructure|reorganize|clean ?up|decouple|extract|split|merge|consolidate)\b", re.I), IntentClass.REFACTOR, 0.85),

    # EXPLAIN
    (re.compile(r"\b(explain|describe|what (is|does|are)|how (does|do)|walk me through|tell me about)\b", re.I), IntentClass.EXPLAIN, 0.85),
    (re.compile(r"\b(understand|clarify|summarize|overview)\b", re.I), IntentClass.EXPLAIN, 0.70),

    # RESEARCH
    (re.compile(r"\b(research|find|look up|search|investigate|explore|compare|benchmark|pros and cons)\b", re.I), IntentClass.RESEARCH, 0.75),
]

# Constraint extraction patterns
_CONSTRAINT_PATTERNS: list[tuple[re.Pattern, ConstraintKind, str]] = [
    (re.compile(r"\bin (?:the )?file[:\s]+([^\s,]+)", re.I), ConstraintKind.SCOPE_FILE, r"\1"),
    (re.compile(r"\bin (?:the )?function[:\s]+(\w+)", re.I),  ConstraintKind.SCOPE_SYMBOL, r"\1"),
    (re.compile(r"\bin (?:the )?class[:\s]+(\w+)", re.I),     ConstraintKind.SCOPE_SYMBOL, r"\1"),
    (re.compile(r"don[''']t touch (\S+)", re.I),              ConstraintKind.PRESERVE, r"\1"),
    (re.compile(r"\bkeep (\S+) (unchanged|intact|as.is)", re.I), ConstraintKind.PRESERVE, r"\1"),
    (re.compile(r"\b(dry.?run|preview only|no changes)", re.I), ConstraintKind.DRY_RUN, "true"),
    (re.compile(r"\bsnapshot first\b", re.I),                  ConstraintKind.ROLLBACK, "true"),
]

# File/symbol mention extraction
_FILE_PATTERN  = re.compile(r"(?:^|[\s('])([a-zA-Z0-9_\-/\\]+\.py)(?=[\s),']|$)", re.M)
_SYMBOL_PATTERN = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:Engine|Manager|Agent|Service|Handler|Model|Class)?)\b|(?:def |class )(\w+)")


def _extract_keywords(query: str) -> list[str]:
    stopwords = {"the", "a", "an", "is", "it", "in", "to", "of", "and", "or",
                 "for", "with", "that", "this", "i", "me", "my", "we", "you"}
    tokens = re.findall(r"\b[a-zA-Z_]\w{2,}\b", query.lower())
    return [t for t in tokens if t not in stopwords][:20]


def _score_intent(query: str) -> tuple[IntentClass, float]:
    scores: dict[IntentClass, float] = {}
    for pattern, intent_class, conf in _PATTERNS:
        if pattern.search(query):
            scores[intent_class] = max(scores.get(intent_class, 0.0), conf)

    if not scores:
        return IntentClass.UNKNOWN, 0.0

    best = max(scores, key=lambda k: scores[k])
    return best, scores[best]


def _extract_targets(query: str) -> list[IntentTarget]:
    targets: list[IntentTarget] = []
    seen: set[str] = set()

    for m in _FILE_PATTERN.finditer(query):
        path = m.group(1)
        if path not in seen:
            seen.add(path)
            targets.append(IntentTarget(path=path, confidence=0.9))

    for m in _SYMBOL_PATTERN.finditer(query):
        sym = m.group(1) or m.group(2)
        if sym and sym not in seen and len(sym) > 2:
            seen.add(sym)
            targets.append(IntentTarget(symbol=sym, confidence=0.75))

    return targets


def _extract_constraints(query: str) -> list[Constraint]:
    constraints: list[Constraint] = []
    for pattern, kind, value_group in _CONSTRAINT_PATTERNS:
        m = pattern.search(query)
        if m:
            try:
                val = m.expand(value_group)
            except Exception:
                val = "true"
            constraints.append(Constraint(kind=kind, value=val))
    return constraints


# ── Public API ────────────────────────────────────────────────────────────────

class IntentEngine:
    """
    Stateless intent classifier.  Thread-safe — share one instance globally.
    """

    def parse(self, query: str) -> IntentResult:
        query = query.strip()
        intent_class, confidence = _score_intent(query)
        targets     = _extract_targets(query)
        constraints = _extract_constraints(query)
        keywords    = _extract_keywords(query)

        ambiguous = confidence < 0.65
        clarification = None
        if intent_class == IntentClass.UNKNOWN:
            clarification = (
                "Could not determine intent. "
                "Try starting with: create / modify / debug / explain / audit / refactor / generate / research"
            )

        return IntentResult(
            intent_class          = intent_class,
            raw_query             = query,
            targets               = targets,
            constraints           = constraints,
            keywords              = keywords,
            confidence            = confidence,
            ambiguous             = ambiguous,
            clarification_needed  = clarification,
        )


# Module-level singleton
_engine: Optional[IntentEngine] = None

def get_engine() -> IntentEngine:
    global _engine
    if _engine is None:
        _engine = IntentEngine()
    return _engine


def parse_intent(query: str) -> IntentResult:
    return get_engine().parse(query)
