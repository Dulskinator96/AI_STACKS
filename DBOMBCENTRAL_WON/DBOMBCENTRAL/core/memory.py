# core/memory.py — WON persistent memory (Supabase backend)
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# Ensure ai-monitor root is in path so db.py is importable regardless of entry point
_AI_MONITOR = Path(__file__).resolve().parent.parent.parent.parent
if str(_AI_MONITOR) not in sys.path:
    sys.path.insert(0, str(_AI_MONITOR))

import db


class WONMemory:
    def __init__(self, path: str = "data/won_memory.db"):
        self._session_id = ""

    # ── Session ────────────────────────────────────────────────────────────────

    def open_session(self) -> str:
        sid = datetime.utcnow().strftime("S-%Y%m%d-%H%M%S")
        self._session_id = sid
        db.open_session(sid)
        return sid

    def close_session(self, session_id: str, log: list = None, brief: str = ""):
        db.close_session(session_id, log or [], brief)

    # ── Write ──────────────────────────────────────────────────────────────────

    def store(self, content: str, mode: str,
              score: float = None, tags: list = None):
        db.store_entry_bg(
            self._session_id, mode, content, score,
            ",".join(tags) if tags else "",
        )

    # ── Read ───────────────────────────────────────────────────────────────────

    def recall(self, limit: int = 10, mode: str = None) -> list[dict]:
        return db.recall_entries(limit, mode)

    def recall_context(self, limit: int = 5) -> list[dict]:
        return db.recall_entries(limit)

    def search(self, query: str, limit: int = 8) -> list[dict]:
        return db.search_entries(query, limit)

    # ── Stats ──────────────────────────────────────────────────────────────────

    def count(self) -> int:
        return db.count_entries()

    def session_count(self) -> int:
        return db.count_sessions()

    def session_summary(self) -> dict:
        modes = db.top_modes(3)
        return {
            "total_entries": self.count(),
            "session_count":  self.session_count(),
            "top_modes":      ", ".join(f"{r['mode']}({r['c']})" for r in modes),
            "last_brief":     db.get_last_brief(),
        }

    def save_snapshot(self):
        db.save_snapshot(self.session_summary())
