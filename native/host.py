#!/usr/bin/env python3
# host.py — AI Monitor Native Messaging Host  (v3 — Full Pipeline)
# Chrome/Edge → this process → pipeline → WON + MemPalace + two Obsidian notes
# Canonical copy lives here; repo root host.py is a thin launcher for local testing.

import sys
import json
import struct
import os
from datetime import datetime
from pathlib import Path

# ── Path setup: parent of native/ is the monitor root (repo or Documents\AI_Monitor)
_NATIVE_DIR = Path(__file__).resolve().parent
_MONITOR_DIR = _NATIVE_DIR.parent
for p in (str(_MONITOR_DIR), str(_NATIVE_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# ── Raw backup paths ───────────────────────────────────────────────────────────
SAVE_DIR = Path.home() / "Documents" / "AI_Monitor"
HISTORY_DIR = SAVE_DIR / "history"
CONTEXT_FILE = SAVE_DIR / "context.txt"
SUMMARY_FILE = SAVE_DIR / "summary.txt"

# ── Pipeline ───────────────────────────────────────────────────────────────────
try:
    import pipeline as won_pipeline

    PIPELINE_OK = True
except Exception as exc:
    PIPELINE_OK = False
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SAVE_DIR / "pipeline_error.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} — import failed: {exc}\n")


def read_message():
    raw = sys.stdin.buffer.read(4)
    if not raw:
        return None
    length = struct.unpack("=I", raw)[0]
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def send_message(data: dict):
    enc = json.dumps(data).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(enc)))
    sys.stdout.buffer.write(enc)
    sys.stdout.buffer.flush()


def _save_raw(data: dict) -> Path:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    platform = data.get("platform", "unknown").replace(" ", "_")
    summary = data.get("summary", "")

    session_file = HISTORY_DIR / f"{ts}_{platform}.txt"
    session_file.write_text(summary, encoding="utf-8")

    with open(SUMMARY_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*50}\n")
        f.write(f"SESSION: {ts} | {platform}\n{'='*50}\n")
        f.write(summary[:2000] + "\n")

    _update_context_raw(data, ts)
    return session_file


def _update_context_raw(data: dict, ts: str):
    if PIPELINE_OK:
        return

    platform = data.get("platform", "unknown")
    msg_count = data.get("messageCount", 0)
    snippet = data.get("summary", "")[:500].strip()

    entry = (
        f"\n[LAST SESSION: {ts}]\n"
        f"Platform : {platform}\n"
        f"Messages : {msg_count}\n"
        f"Snapshot :\n{snippet}\n{'='*50}\n"
    )

    existing = CONTEXT_FILE.read_text(encoding="utf-8") if CONTEXT_FILE.exists() else ""
    sessions = existing.split("[LAST SESSION:")
    if len(sessions) > 5:
        sessions = sessions[-5:]
    existing = "[LAST SESSION:".join(sessions)

    CONTEXT_FILE.write_text(
        "=== AI MONITOR CONTEXT FILE ===\n"
        "Paste this at the start of any new AI chat to restore context.\n"
        f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{'='*50}\n" + existing + entry,
        encoding="utf-8",
    )


def main():
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    while True:
        msg = read_message()
        if msg is None:
            break

        action = msg.get("action") or msg.get("type", "")

        if action in ("save", "SAVE_CHAT"):
            raw_path = _save_raw(msg)
            result = {}
            if PIPELINE_OK:
                try:
                    result = won_pipeline.process(msg)
                except Exception as exc:
                    with open(SAVE_DIR / "pipeline_error.log", "a", encoding="utf-8") as f:
                        f.write(f"{datetime.now().isoformat()} — process() error: {exc}\n")

            send_message(
                {
                    "status": "ok",
                    "saved_to": str(raw_path),
                    "won_indexed": result.get("won_indexed", False),
                    "palace_indexed": result.get("palace_indexed", False),
                    "history_note": result.get("history_path"),
                    "brief_note": result.get("brief_path"),
                    "context_updated": result.get("context_updated", False),
                    "pipeline": "active" if PIPELINE_OK else "offline",
                }
            )

        elif action == "ping":
            send_message({"status": "pong", "pipeline": "active" if PIPELINE_OK else "offline"})

        elif action == "get_context":
            ctx = ""
            if PIPELINE_OK:
                try:
                    ctx = won_pipeline.get_context_snippet()
                except Exception:
                    pass
            send_message({"status": "ok", "context": ctx})

        else:
            send_message({"status": "unknown_action", "received": action})


if __name__ == "__main__":
    main()
