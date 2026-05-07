# perception.py — Shared Ground Perception Layer
# ──────────────────────────────────────────────────────────────────────────────
# AI Monitor's shared memory ground. Both Gemini CLI and Claude can:
#   - peek at the current knowledge state  (get_ground_state)
#   - contribute new knowledge             (contribute)
#   - search across all memory             (search)
#
# This file is the single interface both AIs use to read/write the ground.
# Drop it next to pipeline.py in the ai-monitor folder.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import sys
import re
import json
from datetime import datetime
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_HERE     = Path(__file__).resolve().parent
_WON_ROOT = Path(os.environ.get("WON_PATH", str(_HERE)))
for p in [str(_HERE), str(_WON_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Ground state file — fast read without loading full SQLite
_GROUND_FILE  = Path.home() / "Documents" / "AI_Monitor" / "ground.json"
_CONTEXT_FILE = Path.home() / "Documents" / "AI_Monitor" / "context.txt"
_VAULT_PATH   = Path(os.environ.get("WON_VAULT", str(Path.home() / "Documents" / "WON-Vault")))

# Sources that can write to the ground
SOURCES = {
    "claude":     "Claude (Browser)",
    "gemini_cli": "Gemini CLI",
    "won":        "WON Agent",
    "user":       "User",
    "pipeline":   "AI Monitor Pipeline",
}


# ── Ground state management ────────────────────────────────────────────────────

def _load_ground() -> dict:
    """Load the ground state JSON — lightweight, no DB needed."""
    if not _GROUND_FILE.exists():
        return {"contributions": [], "last_updated": None, "sources": {}}
    try:
        return json.loads(_GROUND_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"contributions": [], "last_updated": None, "sources": {}}


def _save_ground(state: dict):
    _GROUND_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = datetime.utcnow().isoformat()
    _GROUND_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Public API ─────────────────────────────────────────────────────────────────

def contribute(
    content:  str,
    source:   str = "pipeline",
    mode:     str = "exchange",
    tags:     list[str] | None = None,
) -> bool:
    """
    Write a new piece of knowledge to the shared ground.

    source  — who is contributing ("claude", "gemini_cli", "won", "user")
    mode    — type of content ("exchange", "brief", "decision", "research")
    tags    — optional tag list for filtering

    Writes to:
      1. ground.json         — fast shared state file
      2. WON SQLite          — FTS5 keyword index
      3. MemPalace           — semantic vector index (if available)
      4. Obsidian Ground/    — cross-AI knowledge note
    """
    if not content or not content.strip():
        return False

    content = content.strip()
    ts      = datetime.utcnow().isoformat()
    entry   = {
        "ts":      ts,
        "source":  source,
        "mode":    mode,
        "tags":    tags or [],
        "preview": content[:200],
    }

    # 1. ground.json
    try:
        state = _load_ground()
        state["contributions"].append(entry)
        # Keep last 200 in ground.json (previews only — full content in DB)
        state["contributions"] = state["contributions"][-200:]
        state["sources"][source] = state["sources"].get(source, 0) + 1
        _save_ground(state)
    except Exception as exc:
        print(f"[Perception] ground.json write — {exc}", file=sys.stderr)

    # 2. WON SQLite
    try:
        import pipeline as p
        p._load_won()
        if p._memory:
            p._memory.store(
                content=f"[{source}] {content}",
                mode=mode,
                tags=(tags or []) + [source],
            )
    except Exception as exc:
        print(f"[Perception] WON store — {exc}", file=sys.stderr)

    # 3. MemPalace
    try:
        import pipeline as p
        if p._load_palace():
            import tempfile, os as _os
            from mempalace.miner import mine_project
            md = f"# Ground Contribution — {source}\n*{ts}*\n\n{content}\n"
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", prefix="ground_",
                delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(md)
                tmp_path = tmp.name
            try:
                mine_project(path=tmp_path, palace_path=str(p._PALACE_PATH), wing="dbombcentral")
            finally:
                _os.unlink(tmp_path)
    except Exception as exc:
        print(f"[Perception] MemPalace contribute — {exc}", file=sys.stderr)

    # 4. Obsidian Ground note
    try:
        _write_ground_note(source, mode, content, ts)
    except Exception as exc:
        print(f"[Perception] Obsidian ground — {exc}", file=sys.stderr)

    return True


def get_ground_state(max_chars: int = 1200) -> str:
    """
    Return the current shared ground state as a compact string.
    Both AIs call this at session start to get perception of what the other has built.
    Stays under max_chars to minimize token cost.
    """
    parts = []

    # Recent contributions from ground.json (source-attributed)
    try:
        state = _load_ground()
        contribs = state.get("contributions", [])[-15:]
        if contribs:
            parts.append("=== SHARED GROUND — RECENT CONTRIBUTIONS ===")
            for c in reversed(contribs):
                ts_short = c["ts"][:16].replace("T", " ")
                src      = SOURCES.get(c["source"], c["source"])
                preview  = c["preview"][:120].replace("\n", " ")
                parts.append(f"[{ts_short}] {src} ({c['mode']}): {preview}")
    except Exception:
        pass

    # Compressed context from last sessions
    if _CONTEXT_FILE.exists():
        try:
            ctx = _CONTEXT_FILE.read_text(encoding="utf-8")
            # Extract just the session blocks
            blocks = re.findall(r"\[SESSION[^\]]+\].*?={60}", ctx, re.DOTALL)
            if blocks:
                parts.append("\n=== LAST SESSION CONTEXT ===")
                parts.append(blocks[-1][:600])
        except Exception:
            pass

    # Source activity summary
    try:
        state  = _load_ground()
        srcs   = state.get("sources", {})
        if srcs:
            summary = "  |  ".join(
                f"{SOURCES.get(k, k)}: {v} entries"
                for k, v in sorted(srcs.items(), key=lambda x: -x[1])
            )
            parts.append(f"\n=== GROUND ACTIVITY: {summary} ===")
    except Exception:
        pass

    result = "\n".join(parts)
    return result[:max_chars]


def search(query: str, limit: int = 8) -> list[dict]:
    """
    Search across all ground memory.
    Returns unified results from MemPalace + WON FTS5.
    """
    try:
        import pipeline as p
        return p.search(query, limit=limit)
    except Exception as exc:
        print(f"[Perception] search — {exc}", file=sys.stderr)
        return []


def get_compressed_context(max_chars: int = 800) -> str:
    """
    Minimal-token context string for injection at session start.
    Strips markdown, caps at max_chars.
    """
    raw = get_ground_state(max_chars=max_chars * 2)
    # Strip markdown
    clean = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", raw)
    clean = re.sub(r"`{1,3}[^`]*`{1,3}", "", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean[:max_chars]


def format_for_injection(source_name: str = "AI Monitor") -> str:
    """
    Format the ground state as a system-level injection block.
    Paste this at the start of a new chat or inject via the extension.
    """
    ctx = get_compressed_context()
    if not ctx:
        return ""
    return (
        f"[{source_name} GROUND STATE — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}]\n"
        f"{ctx}\n"
        f"[END GROUND STATE]\n"
    )


# ── Obsidian ground notes ──────────────────────────────────────────────────────

def _write_ground_note(source: str, mode: str, content: str, ts: str):
    """
    Write/append to a daily cross-AI knowledge note in Obsidian Ground/.
    Each day gets one note; contributions from all sources are appended.
    """
    date_str  = ts[:10]
    src_label = SOURCES.get(source, source)
    note_path = _VAULT_PATH / "Ground" / f"{date_str}_ground.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)

    # Create with frontmatter if new
    if not note_path.exists():
        note_path.write_text(
            f"---\ncreated: {date_str}\ntype: ground\nsources: []\n---\n\n"
            f"# Ground — {date_str}\n"
            f"*Shared knowledge contributed by all connected AIs and agents.*\n\n",
            encoding="utf-8",
        )

    # Append contribution
    with open(note_path, "a", encoding="utf-8") as f:
        f.write(
            f"\n---\n"
            f"**{src_label}** · `{mode}` · {ts[:16].replace('T', ' ')} UTC\n\n"
            f"{content[:1500]}\n"
        )
