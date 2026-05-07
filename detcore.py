"""
detcore.py — DBOMBCENTRAL Constrained Reasoning Anchor (binding layer).

Pipeline position:
    SHARDFEED (retrieval) → DETBANK (store) → DETCORE (this module) →
    TRIPGATE (validation) → YIELDCAST (output) → ai_monitor surface

Public API:
    load_anchor()                          — read DETCORE.md spec text
    classify_domain(text)                  — PRIMEKEY: tag input domain(s)
    assemble_brief(query, fragments, ...)  — build WICKCORE-bound prompt
    primelatch_payload(limit)              — pull top-K DETBANK fragments
    wickfocus_brief(dashboard, query)      — DETCORE-bound session brief
    breachgate_room(parent_app)            — open two-entity breach room
    dethub_open(parent_app)                — open DBOMB command switchboard

This module is Model-layer per CLAUDE.md §5: NO PyQt6 widget imports.
UI wiring lives in app.py FloatingWidget; this module returns plain data.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Iterable

from config import (
    DETCORE_SPEC_PATH,
    BlastDomain,
    DBombLexicon,
    MAX_CONTEXT_CHARS,
)

_log = logging.getLogger(__name__)

# ── Anchor spec cache ────────────────────────────────────────────────────────

_SPEC_CACHE: str | None = None


def load_anchor() -> str:
    """Return DETCORE.md spec text (cached). Empty string if missing."""
    global _SPEC_CACHE
    if _SPEC_CACHE is not None:
        return _SPEC_CACHE
    try:
        _SPEC_CACHE = Path(DETCORE_SPEC_PATH).read_text(encoding="utf-8")
    except OSError as exc:
        _log.warning("DETCORE spec unreadable at %s: %s", DETCORE_SPEC_PATH, exc)
        _SPEC_CACHE = ""
    return _SPEC_CACHE


# ── PRIMEKEY — domain classification ─────────────────────────────────────────

_DOMAIN_KEYS: dict[str, tuple[str, ...]] = {
    BlastDomain.COG: ("psych", "cognit", "attention", "consciousness", "perception",
                      "emotion", "decision", "bias"),
    BlastDomain.MEM: ("memory", "recall", "episodic", "semantic", "hippocamp",
                      "encoding", "retrieval"),
    BlastDomain.VIS: ("vision", "image", "visual", "color", "video", "sight",
                      "render", "frame", "pixel"),
    BlastDomain.AUD: ("audio", "sound", "hearing", "music", "speech", "voice",
                      "tts", "asr", "loudness"),
    BlastDomain.COD: ("code", "function", "class", "module", "import", "bug",
                      "refactor", "ast", "test", "compile"),
    BlastDomain.CRE: ("design", "create", "compose", "render", "produce",
                      "protocol", "sop", "workflow", "edit"),
    BlastDomain.TRN: ("transformer", "attention head", "embedding", "token",
                      "rag", "retrieval-augmented", "fine-tune", "lora"),
}


def classify_domain(text: str) -> list[str]:
    """PRIMEKEY: tag input with one or more BLASTRADIUS domains.
    Returns [GENERAL] if no keyword matches."""
    if not text:
        return [BlastDomain.GENERAL]
    lower = text.lower()
    hits = [dom for dom, keys in _DOMAIN_KEYS.items() if any(k in lower for k in keys)]
    return hits or [BlastDomain.GENERAL]


# ── DETBANK adapter — pulls from existing memory pipeline ────────────────────

def primelatch_payload(limit: int = 3) -> tuple[str, int]:
    """Pull top-K DETBANK fragments (via existing WON pipeline).
    Returns (concatenated text, fragment count)."""
    try:
        from app import get_won_pipeline  # late import — app imports detcore
    except Exception as exc:  # pragma: no cover — import order safety
        _log.debug("DETBANK pipeline unavailable: %s", exc)
        return ("", 0)

    wp = get_won_pipeline()
    if not wp:
        return ("", 0)
    try:
        entries = wp.recall(limit=limit)
    except Exception as exc:
        _log.warning("SHARDFEED.recall failed: %s", exc)
        return ("", 0)
    if not entries:
        return ("", 0)
    fragments = [e.get("content", "")[:600] for e in entries if e.get("content")]
    text = "\n\n---\n\n".join(fragments)
    return (text[:MAX_CONTEXT_CHARS], len(fragments))


# ── YIELDCAST — DETCORE-bound brief assembly ─────────────────────────────────

_BRIEF_HEADER = (
    "[DBOMBCENTRAL · DETCORE-bound · {ts}]\n"
    "ANCHOR: {anchor} v1\n"
    "DOMAIN: {domains}\n"
    "PROTOCOL: {protocol} → CLASSIFY → CONTEXT → STRUCTURE → REASON → "
    "{validator} → {output}\n"
    "CONSTRAINT: every claim must cite a CONTEXT fragment. If grounding is "
    "absent, reply 'INSUFFICIENT GROUNDED DATA'.\n"
)


def assemble_brief(
    query: str,
    fragments: Iterable[str] = (),
    domains: Iterable[str] | None = None,
) -> str:
    """Assemble a WICKCORE-bound prompt.
    Honors DETCORE FUSELINE: header → CONTEXT → QUERY."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    domains = list(domains) if domains else classify_domain(query)
    header = _BRIEF_HEADER.format(
        ts=ts,
        anchor=DBombLexicon.ANCHOR,
        domains=",".join(domains),
        protocol=DBombLexicon.PROTOCOL,
        validator=DBombLexicon.VALIDATOR,
        output=DBombLexicon.OUTPUT,
    )
    frag_list = [f for f in fragments if f]
    if frag_list:
        ctx_block = "\n\n".join(
            f"[Fragment {i+1}]\n{f}" for i, f in enumerate(frag_list)
        )
    else:
        ctx_block = "(no fragments — SHARDFEED returned empty)"
    return f"{header}\nCONTEXT:\n{ctx_block}\n\nQUERY:\n{query.strip()}\n"


def wickfocus_brief(dashboard, query: str = "") -> str:
    """WICKFOCUS button payload: DETCORE-bound session brief from dashboard chat
    log, DETBANK fragments, and the operator's pending query.

    If PRIMEKEY tags COD, also injects HELIXCHAIN DNA fragments — the brief
    becomes structurally aware of the project's actual functions / classes.
    """
    chat_lines: list[str] = []
    for e in getattr(dashboard, "_chat_log", [])[-4:]:
        role = "Operator" if e.get("role") == "user" else DBombLexicon.PROCESSOR
        txt = (e.get("text") or "")[:120].replace("\n", " ")
        chat_lines.append(f"{role}: {txt}")

    if not query:
        query = next(
            (l[len("Operator: "):] for l in reversed(chat_lines)
             if l.startswith("Operator: ")),
            "",
        )

    fragments_text, count = primelatch_payload(limit=3)
    fragments = [fragments_text] if fragments_text else []
    if chat_lines:
        fragments.append("RECENT TRANSCRIPT:\n" + "\n".join(chat_lines))

    domains = classify_domain(query) if query else [BlastDomain.GENERAL]

    # Phase C: when domain is COD, inject HELIXCHAIN DNA fragments
    helix_count = 0
    if BlastDomain.COD in domains and query:
        try:
            import helixchain as _helix
            project_root = Path(__file__).parent
            dna_frags = _helix.helix_fragments_for_brief(project_root, query, limit=8)
            if dna_frags:
                fragments.append("HELIXCHAIN DNA:\n" + "\n".join(dna_frags))
                helix_count = len(dna_frags)
        except Exception as exc:
            _log.warning("HELIXCHAIN injection failed: %s", exc)

    brief = assemble_brief(query or "(no operator query supplied)",
                           fragments=fragments, domains=domains)
    _log.info("WICKFOCUS brief assembled: domains=%s detbank=%d helix=%d",
              ",".join(domains), count, helix_count)
    return brief


# ── BREACHGATE / DETHUB — UI delegation helpers ──────────────────────────────
# These are thin model-layer helpers. Actual window construction stays in app.py.

def breachgate_room(parent_app):
    """Return PortalWindow class instance — caller is responsible for show()."""
    from app import PortalWindow  # late import — Model layer must not import View
    return PortalWindow(parent_app)


def dethub_open(parent_app) -> None:
    """Bring the dashboard (DBOMB command switchboard) to the front."""
    dash = getattr(parent_app, "dashboard", None)
    if dash is None:
        _log.warning("DETHUB: no dashboard on parent_app")
        return
    dash.show()
    dash.raise_()
    dash.activateWindow()
