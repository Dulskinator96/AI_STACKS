# note_builder.py — Intelligent Obsidian note builder for AI Monitor
# ──────────────────────────────────────────────────────────────────────────────
# Takes raw chat captures and produces two structured Obsidian notes:
#   1. Chat History note  — important exchanges flagged, organized by topic
#   2. Session Brief note — WON BriefEngine summary, decisions, vectors
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

_TS   = lambda: datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
_DATE = lambda: datetime.utcnow().strftime("%Y-%m-%d")

# ── Importance heuristics ──────────────────────────────────────────────────────
# Exchanges containing these signals get flagged as IMPORTANT in the history note

_IMPORTANCE_SIGNALS = [
    # Decisions & actions
    r"\b(decided|decision|confirmed|agreed|approved|rejected|finalized)\b",
    r"\b(action item|next step|todo|task|milestone|deadline)\b",
    r"\b(build|implement|deploy|install|create|delete|remove|update|refactor)\b",
    # Technical depth
    r"\b(architecture|schema|pipeline|database|api|endpoint|module|class|function)\b",
    r"\b(error|bug|fix|issue|problem|crash|fail)\b",
    # Strategic
    r"\b(phase|roadmap|plan|strategy|objective|goal|priority)\b",
    r"\b(CENTCOM|ACAS|WON|DBOMBCENTRAL|MemPalace|Obsidian)\b",
    # Code blocks
    r"```",
]

_IMPORTANCE_RE = re.compile("|".join(_IMPORTANCE_SIGNALS), re.IGNORECASE)

# ── Topic detection ────────────────────────────────────────────────────────────
_TOPIC_PATTERNS = {
    "Architecture & Design":   r"\b(architect|design|schema|structure|pattern|layer|module|class)\b",
    "Code & Implementation":   r"\b(code|function|method|script|implement|refactor|debug|test)\b",
    "Pipeline & Data Flow":    r"\b(pipeline|flow|stream|capture|route|index|sync|process)\b",
    "Memory & Storage":        r"\b(memory|database|sqlite|chromadb|mempalace|obsidian|vault|store)\b",
    "Agent & AI":              r"\b(agent|llm|ollama|gemini|claude|gpt|brain|WON|CENTCOM|ACAS)\b",
    "Planning & Roadmap":      r"\b(phase|plan|roadmap|milestone|timeline|priority|next step)\b",
    "Bug & Fix":               r"\b(error|bug|fix|issue|fail|crash|exception|problem|patch)\b",
    "Setup & Config":          r"\b(install|config|setup|env|path|setting|launch|bat|yaml)\b",
}
_TOPIC_RE = {t: re.compile(p, re.IGNORECASE) for t, p in _TOPIC_PATTERNS.items()}


def _detect_topics(text: str) -> list[str]:
    return [t for t, rx in _TOPIC_RE.items() if rx.search(text)]


def _score_importance(text: str) -> int:
    return len(_IMPORTANCE_RE.findall(text))


# ── Exchange parser ────────────────────────────────────────────────────────────

def _parse_exchanges(raw: str) -> list[dict]:
    """
    Split raw capture into (role, text) exchanges.
    Handles Claude.ai format: 'Human:' / 'Assistant:' prefixes,
    or falls back to paragraph splitting if no markers found.
    """
    exchanges = []

    # Try explicit role markers first
    pattern = re.compile(r"^(Human|User|Assistant|Claude|You|Gemini|AI)\s*[:\|]\s*", re.MULTILINE | re.IGNORECASE)
    parts   = pattern.split(raw.strip())

    if len(parts) > 2:
        # parts = [pre, role1, text1, role2, text2, ...]
        i = 1
        while i + 1 < len(parts):
            role = parts[i].strip().lower()
            text = parts[i + 1].strip()
            if text:
                exchanges.append({
                    "role":       "user"      if role in ("human", "user", "you") else "assistant",
                    "text":       text,
                    "importance": _score_importance(text),
                    "topics":     _detect_topics(text),
                })
            i += 2
    else:
        # Fallback: treat each paragraph as an exchange, alternating roles
        paras = [p.strip() for p in raw.split("\n\n") if p.strip()]
        for i, para in enumerate(paras):
            exchanges.append({
                "role":       "user" if i % 2 == 0 else "assistant",
                "text":       para,
                "importance": _score_importance(para),
                "topics":     _detect_topics(para),
            })

    return exchanges


# ── Note builders ──────────────────────────────────────────────────────────────

def build_history_note(
    session_id:  str,
    platform:    str,
    summary:     str,
    msg_count:   int,
    ts_str:      str,
) -> str:
    """
    Structured Chat History note.
    Important exchanges are highlighted with a ⚡ marker.
    Content is grouped by detected topic.
    """
    exchanges = _parse_exchanges(summary)
    all_topics = sorted(set(t for e in exchanges for t in e["topics"]))
    important  = [e for e in exchanges if e["importance"] >= 2]
    date_str   = _DATE()

    # ── Frontmatter ────────────────────────────────────────────────────────────
    lines = [
        "---",
        f"created: {date_str}",
        f"session_id: {session_id}",
        f"platform: {platform}",
        f"messages: {msg_count}",
        f"important_exchanges: {len(important)}",
        f"topics: [{', '.join(all_topics)}]",
        "type: chat-history",
        "agent: AI Monitor → WON Pipeline",
        "---",
        "",
        f"# Chat History — {platform}",
        f"*{ts_str} · {msg_count} messages · `{session_id}`*",
        "",
    ]

    # ── Topic index ────────────────────────────────────────────────────────────
    if all_topics:
        lines += ["## Topics Covered", ""]
        for t in all_topics:
            lines.append(f"- {t}")
        lines.append("")

    # ── Important exchanges ────────────────────────────────────────────────────
    if important:
        lines += [
            "---",
            "## ⚡ Key Exchanges",
            "*Flagged by importance heuristics — decisions, code, architecture, strategy*",
            "",
        ]
        for i, e in enumerate(important, 1):
            role_label = "**You**" if e["role"] == "user" else f"**{platform}**"
            topic_tags = " · ".join(f"`{t}`" for t in e["topics"]) if e["topics"] else ""
            lines += [
                f"### ⚡ Exchange {i}  {topic_tags}",
                f"{role_label}:",
                f"> {e['text'][:800].replace(chr(10), chr(10) + '> ')}",
                "",
            ]

    # ── Full chronological transcript ──────────────────────────────────────────
    lines += [
        "---",
        "## Full Transcript",
        "",
    ]
    for e in exchanges:
        marker     = "⚡ " if e["importance"] >= 2 else ""
        role_label = "**You**" if e["role"] == "user" else f"**{platform}**"
        lines += [
            f"{marker}{role_label}:",
            f"{e['text'][:1500]}",
            "",
        ]

    lines += [
        "---",
        f"*Chat History by AI Monitor · Indexed by WON + MemPalace · {ts_str}*",
    ]
    return "\n".join(lines)


def build_brief_note(
    session_id:  str,
    platform:    str,
    summary:     str,
    msg_count:   int,
    ts_str:      str,
    brain=None,
    tracker=None,
    memory=None,
    build_files: Optional[dict] = None,
) -> str:
    """
    Session Brief note.
    Uses WON Brain (Ollama) if available; falls back to heuristic extraction.
    build_files = {filename: content_snippet} — local build context for the brief.
    """
    date_str  = _DATE()
    exchanges = _parse_exchanges(summary)
    topics    = sorted(set(t for e in exchanges for t in e["topics"]))
    important = [e for e in exchanges if e["importance"] >= 2]

    # ── Build-file context block ───────────────────────────────────────────────
    build_context = ""
    if build_files:
        snippets = []
        for fname, content in list(build_files.items())[:5]:
            snippets.append(f"  [{fname}]\n  {content[:300]}")
        build_context = "Local build files referenced:\n" + "\n".join(snippets)

    # ── AI-generated brief (WON Brain via Ollama) ──────────────────────────────
    ai_brief = ""
    if brain is not None:
        try:
            key_text = "\n\n".join(
                f"[{e['role']}]: {e['text'][:400]}"
                for e in important[:8]
            ) or summary[:2000]

            prompt = (
                f"You are WON — DBOMB ASCENDENT. Produce a concise session brief.\n\n"
                f"Platform: {platform}\n"
                f"Messages: {msg_count}\n"
                f"Topics: {', '.join(topics)}\n"
                f"{build_context}\n\n"
                f"Key exchanges:\n{key_text}\n\n"
                f"Brief must include:\n"
                f"1. What Was Discussed (2-3 sentences)\n"
                f"2. Key Decisions Made (bullet points)\n"
                f"3. Action Items / Next Steps (bullet points)\n"
                f"4. Forward Vectors — 3 probability-weighted next moves\n"
                f"5. Token Efficiency Note — what to paste at next session start\n\n"
                f"Be dense. No filler. Operational intelligence only."
            )
            ctx = memory.recall_context(limit=3) if memory else None
            ai_brief = brain.reason(prompt=prompt, context=ctx)
        except Exception as exc:
            ai_brief = f"[Brain offline: {exc}]"

    # ── Heuristic fallback ─────────────────────────────────────────────────────
    if not ai_brief:
        ai_brief = _heuristic_brief(exchanges, important, topics)

    # ── Compressed context for context.txt (token-efficient) ──────────────────
    compressed = _compress_for_context(session_id, platform, ai_brief, topics)

    # ── Assemble note ──────────────────────────────────────────────────────────
    lines = [
        "---",
        f"created: {date_str}",
        f"session_id: {session_id}",
        f"platform: {platform}",
        f"messages: {msg_count}",
        f"topics: [{', '.join(topics)}]",
        "type: session-brief",
        "agent: WON — DBOMB ASCENDENT",
        "---",
        "",
        f"# Session Brief — {platform}",
        f"*{ts_str} · {msg_count} messages · `{session_id}`*",
        "",
        "---",
        "## Brief",
        "",
        ai_brief,
        "",
        "---",
        "## Compressed Context",
        "*Paste this block at the start of your next session to restore context instantly.*",
        "",
        "```",
        compressed,
        "```",
        "",
        "---",
        f"*Brief by WON — DBOMB ASCENDENT · {ts_str}*",
        f"*Linked: [[Chat History — {session_id}]]*",
    ]
    return "\n".join(lines)


def _heuristic_brief(exchanges, important, topics) -> str:
    """Fallback brief when Ollama is offline."""
    lines = ["**What Was Discussed**"]
    if topics:
        lines.append(f"Session covered: {', '.join(topics)}.")
    lines.append(f"Total exchanges: {len(exchanges)}. Key moments: {len(important)}.")
    lines += ["", "**Key Exchanges (flagged)**"]
    for e in important[:5]:
        preview = e["text"][:200].replace("\n", " ")
        lines.append(f"- [{e['role']}] {preview}")
    lines += ["", "**Action Items**", "- Review flagged exchanges above", "- Update project tracker"]
    return "\n".join(lines)


def _compress_for_context(session_id: str, platform: str, brief: str, topics: list[str]) -> str:
    """
    Minimal token footprint for context.txt injection.
    Strips markdown, caps at 800 chars.
    """
    # Strip markdown
    clean = re.sub(r"#{1,6}\s+", "", brief)
    clean = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", clean)
    clean = re.sub(r"`{1,3}[^`]*`{1,3}", "", clean)
    clean = re.sub(r"\n{2,}", "\n", clean).strip()
    clean = clean[:800]

    return (
        f"[SESSION {session_id} | {platform}]\n"
        f"Topics: {', '.join(topics) or 'general'}\n"
        f"{clean}"
    )
