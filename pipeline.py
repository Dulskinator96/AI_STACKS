# pipeline.py — WON ↔ AI Monitor Bridge  (v3 — Full Scope)
# ──────────────────────────────────────────────────────────────────────────────
# Every Claude/Gemini/ChatGPT session captured by the browser extension routes
# through here and produces:
#
#   1. Raw .txt backup          — always written, original behaviour
#   2. WON SQLite (FTS5)        — keyword search, persists forever
#   3. MemPalace (ChromaDB)     — semantic vector search, 96.6% R@5
#   4. Obsidian Chat History    — structured, flagged, topic-grouped
#   5. Obsidian Session Brief   — WON BriefEngine summary, decisions, vectors
#   6. context.txt update       — compressed brief for next-session token savings
#
# Environment variables:
#   WON_PATH    — path to DBOMBCENTRAL folder (contains won.py + core/)
#   WON_VAULT   — Obsidian vault path
#   PALACE_PATH — MemPalace palace path (default: ~/.mempalace/palace)
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# ── Locate roots ───────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent

# Resolution order: env var → sibling DBOMBCENTRAL folder → script dir
_FALLBACKS = [
    os.environ.get("WON_PATH", ""),
    str(_HERE / "DBOMBCENTRAL_WON" / "DBOMBCENTRAL"),
    str(_HERE.parent / "DBOMBCENTRAL_WON" / "DBOMBCENTRAL"),
    str(_HERE),
]
_WON_ROOT = Path(next((p for p in _FALLBACKS if p and (Path(p) / "core").is_dir()), str(_HERE)))

for _p in [str(_WON_ROOT), str(_HERE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Paths ──────────────────────────────────────────────────────────────────────
_VAULT_PATH  = Path(os.environ.get("WON_VAULT",   str(Path.home() / "Documents" / "WON-Vault")))
_MEMORY_PATH = _WON_ROOT / "data" / "won_memory.db"
_PALACE_PATH = Path(os.environ.get("PALACE_PATH", str(Path.home() / ".mempalace" / "palace")))
_PALACE_WING = "dbombcentral"

# Build file directories pipeline will scan for context
_BUILD_DIRS = [
    _WON_ROOT,
    _WON_ROOT / "core",
    _HERE,
]
_BUILD_EXTS = {".py", ".yaml", ".yml", ".json", ".md", ".txt"}
_BUILD_SKIP = {"won_memory.db", "projects.json", "__pycache__", ".git"}

# ── Lazy singletons ────────────────────────────────────────────────────────────
_won_ready    = False
_palace_ready = False
_memory       = None
_obsidian     = None
_brain        = None
_tracker      = None


def _load_won() -> bool:
    global _won_ready, _memory, _obsidian, _brain, _tracker
    if _won_ready:
        return True
    try:
        from core.memory import WONMemory
        from core.obsidian import ObsidianWriter
        from core.brain import Brain
        from core.project_tracker import ProjectTracker
        os.makedirs(_MEMORY_PATH.parent, exist_ok=True)
        _memory   = WONMemory(path=str(_MEMORY_PATH))
        _obsidian = ObsidianWriter(vault_path=str(_VAULT_PATH))
        _brain    = Brain()
        _tracker  = ProjectTracker(path=str(_WON_ROOT / "data" / "projects.json"))
        _won_ready = True
        return True
    except Exception as exc:
        print(f"[Pipeline] WON core unavailable — {exc}", file=sys.stderr)
        return False


_palace_attempted = False   # only try once — no stderr spam

def _load_palace() -> bool:
    global _palace_ready, _palace_attempted
    if _palace_ready:
        return True
    if _palace_attempted:
        return False
    _palace_attempted = True
    try:
        import warnings, logging
        logging.getLogger("opentelemetry").setLevel(logging.CRITICAL)
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        from mempalace.miner import mine_project        # noqa: F401
        from mempalace.searcher import search_memories  # noqa: F401
        _palace_ready = True
        return True
    except Exception:
        return False  # silent — WON SQLite handles search


# ── Build file reader ──────────────────────────────────────────────────────────

def _read_build_files(max_files: int = 8) -> dict[str, str]:
    """
    Scan DBOMBCENTRAL and ai-monitor for relevant source files.
    Returns {filename: first_500_chars} for use as brief context.
    """
    files = {}
    for d in _BUILD_DIRS:
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if len(files) >= max_files:
                break
            if (f.is_file()
                    and f.suffix in _BUILD_EXTS
                    and f.name not in _BUILD_SKIP
                    and not f.name.startswith(".")):
                try:
                    files[f.name] = f.read_text(encoding="utf-8", errors="ignore")[:500]
                except Exception:
                    pass
    return files


# ── Public API ─────────────────────────────────────────────────────────────────

def process(data: dict) -> dict:
    """
    Full pipeline for a browser-extension capture.

    Input keys:
        platform     (str)  — "Claude", "Gemini", "ChatGPT", ...
        summary      (str)  — full raw chat text
        messageCount (int)  — number of turns

    Returns:
        {
            won_indexed:      bool,
            palace_indexed:   bool,
            history_path:     str | None,   ← Obsidian Chat History note
            brief_path:       str | None,   ← Obsidian Session Brief note
            context_updated:  bool,         ← context.txt compressed brief updated
        }
    """
    platform  = data.get("platform", "unknown")
    summary   = (data.get("summary") or "").strip()
    msg_count = int(data.get("messageCount") or 0)

    if not summary:
        return _empty_result()

    ts         = datetime.utcnow()
    platform_slug = platform.replace(" ", "_").replace("/", "-")[:20]
    session_id = f"{platform_slug}_{ts.strftime('%Y-%m-%d_%H%M')}"
    ts_str     = ts.strftime("%Y-%m-%d %H:%M UTC")

    won_ok    = _route_won(platform, summary)
    palace_ok = _route_palace(platform, summary, session_id, ts_str, msg_count)
    history_p, brief_p, ctx_ok = _route_obsidian(platform, summary, msg_count, session_id, ts_str)

    return {
        "won_indexed":     won_ok,
        "palace_indexed":  palace_ok,
        "history_path":    history_p,
        "brief_path":      brief_p,
        "context_updated": ctx_ok,
    }


def process_file(txt_path: str) -> dict:
    """Retroactively process a .txt history file through the full pipeline."""
    p = Path(txt_path)
    if not p.exists():
        return _empty_result()
    parts    = p.stem.split("_", 2)
    platform = parts[2].replace("_", " ") if len(parts) >= 3 else "unknown"
    try:
        summary = p.read_text(encoding="utf-8").strip()
    except Exception:
        return _empty_result()
    return process({"platform": platform, "summary": summary, "messageCount": 0})


def search(query: str, limit: int = 10) -> list[dict]:
    """
    Unified search: MemPalace semantic (primary) + WON FTS5 (augment).
    """
    results = []

    if _load_palace():
        try:
            from mempalace.searcher import search_memories
            mp = search_memories(query, str(_PALACE_PATH), wing=_PALACE_WING)
            for h in mp.get("results", [])[:limit]:
                results.append({
                    "text":        h.get("text", ""),
                    "similarity":  float(h.get("similarity") or 0.0),
                    "source_file": h.get("source_file", "palace"),
                    "source":      "mempalace",
                })
        except Exception as exc:
            print(f"[Pipeline] MemPalace search — {exc}", file=sys.stderr)

    if _load_won():
        try:
            seen = {r["text"][:80] for r in results}
            for h in _memory.search(query, limit=limit):
                content = h.get("content", "")
                if content[:80] not in seen:
                    results.append({
                        "text":        content,
                        "similarity":  float(h.get("score") or 0.5),
                        "source_file": f"WON:{h.get('mode','?')}:{(h.get('timestamp') or '')[:10]}",
                        "source":      "won",
                    })
        except Exception as exc:
            print(f"[Pipeline] WON search — {exc}", file=sys.stderr)

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:limit]


def recall(limit: int = 10) -> list[dict]:
    if not _load_won():
        return []
    return _memory.recall(limit=limit)


def stats() -> dict:
    base = {"total_entries": 0, "session_count": 0, "top_modes": "", "last_brief": None}
    if _load_won():
        try:
            base = _memory.session_summary()
        except Exception:
            pass
    base["palace_available"] = _load_palace()
    base["palace_path"]      = str(_PALACE_PATH)
    return base


def vault_path() -> str:
    return str(_VAULT_PATH)


def get_context_snippet(max_chars: int = 1200) -> str:
    """
    Return the current context.txt content — used to prepend minimal
    context to new sessions instead of pasting full history.
    Caps at max_chars to keep token usage low.
    """
    ctx_file = Path.home() / "Documents" / "AI_Monitor" / "context.txt"
    if not ctx_file.exists():
        return ""
    try:
        return ctx_file.read_text(encoding="utf-8")[:max_chars]
    except Exception:
        return ""


# ── Internal routing ───────────────────────────────────────────────────────────

def _route_won(platform: str, summary: str) -> bool:
    if not _load_won():
        return False
    try:
        _memory.store(
            content=f"[{platform}] {summary}",
            mode="capture",
            tags=["capture", platform.lower().replace(" ", "-")],
        )
        return True
    except Exception as exc:
        print(f"[Pipeline] WON store — {exc}", file=sys.stderr)
        return False


def _route_palace(platform, summary, session_id, ts_str, msg_count) -> bool:
    if not _load_palace():
        return False
    try:
        from mempalace.miner import mine_project
        transcript = (
            f"# {platform} Capture — {session_id}\n"
            f"*{ts_str} · {msg_count} messages*\n\n"
            f"{summary}\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md",
            prefix=f"{session_id}_",
            delete=False, encoding="utf-8",
        ) as tmp:
            tmp.write(transcript)
            tmp_path = tmp.name
        try:
            mine_project(path=tmp_path, palace_path=str(_PALACE_PATH), wing=_PALACE_WING)
        finally:
            os.unlink(tmp_path)
        return True
    except Exception as exc:
        print(f"[Pipeline] MemPalace mine — {exc}", file=sys.stderr)
        return False


def _route_obsidian(
    platform: str,
    summary: str,
    msg_count: int,
    session_id: str,
    ts_str: str,
) -> tuple[str | None, str | None, bool]:
    """
    Write two notes to Obsidian and update context.txt.
    Returns (history_path, brief_path, context_updated).
    """
    if not _load_won():
        return None, None, False

    try:
        from note_builder import build_history_note, build_brief_note, _compress_for_context
        from note_builder import _detect_topics, _parse_exchanges
    except Exception as exc:
        print(f"[Pipeline] note_builder unavailable — {exc}", file=sys.stderr)
        return None, None, False

    safe_plat  = platform.replace(" ", "_")
    build_files = _read_build_files()

    # 1. Chat History note ─────────────────────────────────────────────────────
    history_md = build_history_note(session_id, platform, summary, msg_count, ts_str)
    history_rel = f"Sessions/History/{session_id}_chat.md"
    history_path = None
    try:
        _obsidian._write(history_rel, history_md)
        history_path = str(Path(_obsidian.vault_path) / history_rel)
    except Exception as exc:
        print(f"[Pipeline] Obsidian history write — {exc}", file=sys.stderr)

    # 2. Session Brief note ────────────────────────────────────────────────────
    brief_md = build_brief_note(
        session_id=session_id,
        platform=platform,
        summary=summary,
        msg_count=msg_count,
        ts_str=ts_str,
        brain=_brain,
        tracker=_tracker,
        memory=_memory,
        build_files=build_files,
    )
    brief_rel  = f"Sessions/Briefs/{session_id}_brief.md"
    brief_path = None
    try:
        _obsidian._write(brief_rel, brief_md)
        brief_path = str(Path(_obsidian.vault_path) / brief_rel)
        # Store brief in WON memory too
        _memory.store(
            content=f"[Brief:{platform}:{session_id}] {brief_md[:1000]}",
            mode="brief",
            tags=["brief", "capture", platform.lower().replace(" ", "-")],
        )
    except Exception as exc:
        print(f"[Pipeline] Obsidian brief write — {exc}", file=sys.stderr)

    # 3. Update context.txt with compressed brief ──────────────────────────────
    ctx_ok = False
    try:
        exchanges = _parse_exchanges(summary)
        topics    = sorted(set(t for e in exchanges for t in _detect_topics(e["text"])))
        compressed = _compress_for_context(session_id, platform, brief_md, topics)
        _update_context_file(compressed, session_id, platform)
        ctx_ok = True
    except Exception as exc:
        print(f"[Pipeline] context.txt update — {exc}", file=sys.stderr)

    return history_path, brief_path, ctx_ok


def _update_context_file(compressed: str, session_id: str, platform: str):
    """
    Append compressed brief to context.txt, keeping last 5 sessions.
    This is what gets pasted into new chats — minimal tokens, maximum context.
    """
    ctx_file = Path.home() / "Documents" / "AI_Monitor" / "context.txt"
    ctx_file.parent.mkdir(parents=True, exist_ok=True)

    entry = (
        f"\n[SESSION {session_id} | {platform} | {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}]\n"
        f"{compressed}\n"
        f"{'='*60}\n"
    )

    existing = ctx_file.read_text(encoding="utf-8") if ctx_file.exists() else ""
    sessions = existing.split("\n[SESSION ")
    if len(sessions) > 5:
        sessions = sessions[-5:]
    existing = "\n[SESSION ".join(sessions)

    ctx_file.write_text(
        "=== AI MONITOR — COMPRESSED CONTEXT ===\n"
        "Paste this at the start of a new chat to restore context with minimal tokens.\n"
        f"Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"{'='*60}\n"
        + existing + entry,
        encoding="utf-8",
    )


def _empty_result() -> dict:
    return {
        "won_indexed": False, "palace_indexed": False,
        "history_path": None, "brief_path": None, "context_updated": False,
    }


def contribute(content: str, source: str = "pipeline", mode: str = "exchange", tags: list = None) -> bool:
    """
    Direct write to shared ground — delegates to perception.contribute().
    Call this from any script, MCP tool, or agent to add knowledge.
    """
    try:
        import perception as _perc
        return _perc.contribute(content=content, source=source, mode=mode, tags=tags or [])
    except Exception as exc:
        # Fallback: write directly to WON SQLite if perception is unavailable
        if _load_won():
            try:
                _memory.store(
                    content=f"[{source}] {content}",
                    mode=mode,
                    tags=(tags or []) + [source],
                )
                return True
            except Exception:
                pass
        print(f"[Pipeline] contribute() — {exc}", file=sys.stderr)
        return False
