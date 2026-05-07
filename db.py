# db.py — Supabase remote memory gateway for WON/STRATUM
#
# ── Setup (one-time, in Supabase SQL editor) ──────────────────────────────────
#
#   CREATE TABLE entries (
#     id        bigserial PRIMARY KEY,
#     timestamp timestamptz DEFAULT now(),
#     session   text, mode text, content text,
#     score     real, tags text
#   );
#   CREATE TABLE sessions (
#     id text PRIMARY KEY,
#     opened timestamptz, closed timestamptz,
#     log text, brief text
#   );
#   CREATE TABLE snapshots (
#     id bigserial PRIMARY KEY,
#     timestamp timestamptz DEFAULT now(),
#     data text
#   );
#   CREATE TABLE content_hashes (
#     hash text PRIMARY KEY,
#     first_seen timestamptz DEFAULT now(),
#     source text, count integer DEFAULT 1
#   );
#   CREATE TABLE captures (
#     hash text PRIMARY KEY,
#     ts timestamptz DEFAULT now(),
#     source text, content_type text, content text,
#     char_count integer,
#     compressed boolean DEFAULT false,
#     indexed boolean DEFAULT false
#   );
#
#   -- RLS: block all anon/authenticated access; service_role bypasses RLS
#   ALTER TABLE entries        ENABLE ROW LEVEL SECURITY;
#   ALTER TABLE sessions       ENABLE ROW LEVEL SECURITY;
#   ALTER TABLE snapshots      ENABLE ROW LEVEL SECURITY;
#   ALTER TABLE content_hashes ENABLE ROW LEVEL SECURITY;
#   ALTER TABLE captures       ENABLE ROW LEVEL SECURITY;
#
# ── Env vars ──────────────────────────────────────────────────────────────────
#   SUPABASE_URL — https://<project-ref>.supabase.co
#   SUPABASE_KEY — service_role secret key (never the anon key)
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime
from typing import Optional

_client = None
_client_lock = threading.Lock()


def _db():
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
        if not url or not key:
            return None
        try:
            from supabase import create_client
            _client = create_client(url, key)
        except Exception:
            return None
    return _client


def _bg(fn, *args, **kwargs):
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


def available() -> bool:
    return _db() is not None


# ── entries ───────────────────────────────────────────────────────────────────

def store_entry(session: str, mode: str, content: str,
                score=None, tags: str = ""):
    c = _db()
    if not c:
        return
    c.table("entries").insert({
        "timestamp": datetime.utcnow().isoformat(),
        "session": session,
        "mode": mode,
        "content": content,
        "score": score,
        "tags": tags,
    }).execute()


def store_entry_bg(session: str, mode: str, content: str,
                   score=None, tags: str = ""):
    _bg(store_entry, session, mode, content, score, tags)


def recall_entries(limit: int = 10, mode: str = None) -> list[dict]:
    c = _db()
    if not c:
        return []
    q = c.table("entries").select("*").order("id", desc=True).limit(limit)
    if mode:
        q = q.eq("mode", mode)
    res = q.execute()
    return list(reversed(res.data or []))


def search_entries(query: str, limit: int = 8) -> list[dict]:
    c = _db()
    if not c:
        return []
    safe = query.replace("%", "").replace("_", "")
    res = (c.table("entries").select("*")
           .ilike("content", f"%{safe}%")
           .limit(limit)
           .execute())
    return res.data or []


def count_entries() -> int:
    c = _db()
    if not c:
        return 0
    res = c.table("entries").select("id", count="exact").execute()
    return res.count or 0


def entries_older_than(cutoff_iso: str) -> list[dict]:
    c = _db()
    if not c:
        return []
    res = (c.table("entries").select("id, content")
           .lt("timestamp", cutoff_iso)
           .execute())
    return res.data or []


def update_entry_content(entry_id: int, content: str):
    c = _db()
    if not c:
        return
    c.table("entries").update({"content": content}).eq("id", entry_id).execute()


# ── sessions ──────────────────────────────────────────────────────────────────

def open_session(sid: str):
    c = _db()
    if not c:
        return
    c.table("sessions").insert({
        "id": sid,
        "opened": datetime.utcnow().isoformat(),
    }).execute()


def close_session(sid: str, log=None, brief: str = ""):
    c = _db()
    if not c:
        return
    c.table("sessions").update({
        "closed": datetime.utcnow().isoformat(),
        "log": json.dumps(log or []),
        "brief": brief,
    }).eq("id", sid).execute()


def count_sessions() -> int:
    c = _db()
    if not c:
        return 0
    res = c.table("sessions").select("id", count="exact").execute()
    return res.count or 0


def get_last_brief() -> Optional[str]:
    c = _db()
    if not c:
        return None
    res = (c.table("sessions").select("brief")
           .not_.is_("brief", "null")
           .neq("brief", "")
           .order("opened", desc=True)
           .limit(1)
           .execute())
    return res.data[0]["brief"] if res.data else None


def top_modes(n: int = 3) -> list[dict]:
    c = _db()
    if not c:
        return []
    res = c.table("entries").select("mode").limit(1000).execute()
    counts: dict[str, int] = {}
    for r in (res.data or []):
        m = r.get("mode") or "unknown"
        counts[m] = counts.get(m, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: -x[1])
    return [{"mode": k, "c": v} for k, v in ranked[:n]]


# ── snapshots ─────────────────────────────────────────────────────────────────

def save_snapshot(data: dict):
    c = _db()
    if not c:
        return
    c.table("snapshots").insert({
        "timestamp": datetime.utcnow().isoformat(),
        "data": json.dumps(data),
    }).execute()


# ── content_hashes (dedup) ────────────────────────────────────────────────────

def hash_content(content: str) -> str:
    normalized = " ".join(content.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def is_duplicate_hash(h: str) -> bool:
    c = _db()
    if not c:
        return False
    res = c.table("content_hashes").select("hash").eq("hash", h).execute()
    if res.data:
        _bg(_increment_hash, h)
        return True
    return False


def _increment_hash(h: str):
    c = _db()
    if not c:
        return
    try:
        res = c.table("content_hashes").select("count").eq("hash", h).execute()
        if res.data:
            c.table("content_hashes").update(
                {"count": res.data[0]["count"] + 1}
            ).eq("hash", h).execute()
    except Exception:
        pass


def register_hash(h: str, source: str = ""):
    c = _db()
    if not c:
        return
    c.table("content_hashes").upsert({
        "hash": h,
        "first_seen": datetime.utcnow().isoformat(),
        "source": source,
        "count": 1,
    }).execute()


def hash_stats() -> dict:
    c = _db()
    if not c:
        return {"total_unique": 0, "duplicates_prevented": 0}
    res = c.table("content_hashes").select("hash, count", count="exact").execute()
    total = res.count or 0
    dupes = sum(max(0, r.get("count", 1) - 1) for r in (res.data or []))
    return {"total_unique": total, "duplicates_prevented": dupes}


# ── captures (harvester) ──────────────────────────────────────────────────────

def is_duplicate_capture(h: str) -> bool:
    c = _db()
    if not c:
        return False
    res = c.table("captures").select("hash").eq("hash", h).execute()
    return bool(res.data)


def register_capture(h: str, source: str, content_type: str, content: str,
                     char_count: int, compressed: bool = False):
    c = _db()
    if not c:
        return
    c.table("captures").upsert({
        "hash": h,
        "ts": datetime.utcnow().isoformat(),
        "source": source,
        "content_type": content_type,
        "content": content,
        "char_count": char_count,
        "compressed": compressed,
        "indexed": False,
    }).execute()


def register_capture_bg(h: str, source: str, content_type: str, content: str,
                        char_count: int, compressed: bool = False):
    _bg(register_capture, h, source, content_type, content, char_count, compressed)


def mark_capture_indexed(h: str):
    c = _db()
    if not c:
        return
    c.table("captures").update({"indexed": True}).eq("hash", h).execute()


def capture_stats() -> dict:
    c = _db()
    if not c:
        return {"total_captures": 0, "total_chars": 0, "compressed": 0}
    res = c.table("captures").select("char_count, compressed", count="exact").execute()
    data = res.data or []
    return {
        "total_captures": res.count or 0,
        "total_chars": sum(r.get("char_count") or 0 for r in data),
        "compressed": sum(1 for r in data if r.get("compressed")),
    }
