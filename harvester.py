# harvester.py — STRATUM Zero-Leak Data Harvester (Supabase backend)
#
# Capture surfaces:
#   1. Clipboard — AI-looking text captured and indexed
#   2. Context overflow — text too long for context windows, compressed + stored
#   3. Temp file scanner — abandoned session data recovered
#   4. Process stdout — pipes from Gemini CLI / other AI tools
#   5. Token-optimized compression — long content compressed before storage
#
# All captured data → Supabase captures table (no local .db or overflow files)

from __future__ import annotations

import os
import re
import sys
import json
import time
import hashlib
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import db
import logging
_log = logging.getLogger(__name__)

OLLAMA_URL    = "http://localhost:11434/api/generate"
DEFAULT_MODEL = os.environ.get("WON_MODEL", "mistral:latest")


# ── Content Analysis ──────────────────────────────────────────────────────────

AI_MARKERS = [
    "Claude", "ChatGPT", "Gemini", "GPT-4", "GPT-3", "Anthropic",
    "assistant:", "Assistant:", "User:", "Human:", "WON:", "STRATUM",
    "→", "```", "ANALYSIS:", "INSIGHT:", "DECISION:", "FINDING:",
    "I understand", "Let me", "Certainly", "Of course", "I'll help",
    "Here's", "Here is", "Based on", "In conclusion",
]

CODE_MARKERS = ["def ", "class ", "import ", "function ", "const ", "var ", "let "]


def classify_content(text: str) -> str:
    text_lower = text.lower()
    if any(m.lower() in text_lower for m in AI_MARKERS):
        return "ai_conversation"
    if any(m in text for m in CODE_MARKERS):
        return "code_fragment"
    if len(text) > 500 and text.count('\n') > 5:
        return "document_fragment"
    return "raw_text"


def compute_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()[:16]


def is_ai_content(text: str) -> bool:
    return any(m in text for m in AI_MARKERS) or classify_content(text) == "code_fragment"


# ── Index proxy (thin wrapper over db.*) ──────────────────────────────────────

class _IndexProxy:
    def is_duplicate(self, content_hash: str) -> bool:
        return db.is_duplicate_capture(content_hash)

    def register(self, content_hash: str, source: str, content_type: str,
                 content: str, char_count: int, compressed: bool = False):
        db.register_capture_bg(content_hash, source, content_type, content,
                               char_count, compressed)

    def mark_indexed(self, content_hash: str):
        db.mark_capture_indexed(content_hash)

    def stats(self) -> dict:
        return db.capture_stats()


_index_proxy = _IndexProxy()


def get_index() -> _IndexProxy:
    return _index_proxy


# ── Semantic Compression ──────────────────────────────────────────────────────

def compress_semantic(content: str, max_output: int = 500) -> str:
    if len(content) <= max_output:
        return content

    prompt = (
        f"Compress this content to under {max_output} characters. "
        f"Preserve: key decisions, named entities, conclusions, action items. "
        f"Remove: filler, repetition, pleasantries. Output compressed text only.\n\n"
        f"CONTENT:\n{content[:3000]}"
    )
    try:
        import requests as _r
        r = _r.post(
            OLLAMA_URL,
            json={"model": DEFAULT_MODEL, "prompt": prompt, "stream": False,
                  "options": {"num_predict": max_output // 4, "temperature": 0.2}},
            timeout=30,
        )
        compressed = r.json().get("response", "").strip()
        if compressed and len(compressed) < len(content) * 0.7:
            return compressed
    except Exception as e:
        _log.warning(f'caught exception: {e}')

    sentences = re.split(r'(?<=[.!?])\s+', content)
    result, chars = [], 0
    for s in sentences:
        if chars + len(s) > max_output:
            break
        result.append(s)
        chars += len(s) + 1
    return " ".join(result) or content[:max_output]


# ── Capture ───────────────────────────────────────────────────────────────────

def capture(
    content: str,
    source: str = "unknown",
    auto_compress: bool = True,
    auto_index: bool = True,
) -> Optional[dict]:
    if not content or len(content.strip()) < 50:
        return None

    content_hash = compute_hash(content)
    idx = get_index()

    if idx.is_duplicate(content_hash):
        return None

    content_type  = classify_content(content)
    original_len  = len(content)
    stored_content = content
    compressed     = False

    if auto_compress and len(content) > 2000:
        stored_content = compress_semantic(content, max_output=1000)
        compressed = True

    idx.register(content_hash, source, content_type, stored_content,
                 original_len, compressed)

    record = {
        "hash":         content_hash,
        "source":       source,
        "content_type": content_type,
        "char_count":   original_len,
        "compressed":   compressed,
        "ts":           datetime.utcnow().isoformat(),
        "preview":      stored_content[:120],
    }

    if auto_index:
        _index_to_won(stored_content, source, content_type)
        idx.mark_indexed(content_hash)

    return record


def capture_overflow(content: str, source: str = "context_overflow") -> Optional[dict]:
    return capture(content, source=source, auto_compress=True)


def capture_file(path: Path, source: str = "file") -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if len(text) > 100 and is_ai_content(text):
            return capture(text, source=f"file:{path.name}")
    except Exception as e:
        _log.warning(f'caught exception: {e}')
    return None


# ── Clipboard Harvester ───────────────────────────────────────────────────────

class ClipboardHarvester:
    def __init__(self, interval_s: float = 30.0):
        self.interval = interval_s
        self._stop   = threading.Event()
        self._last   = ""
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                clip = self._read_clipboard()
                if clip and clip != self._last and len(clip) > 100:
                    if is_ai_content(clip):
                        capture(clip, source="clipboard")
                    self._last = clip
            except Exception as e:
                _log.warning(f'caught exception: {e}')

    def _read_clipboard(self) -> str:
        try:
            import subprocess
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=3,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            return result.stdout.strip()
        except Exception as e:
            _log.warning(f'caught exception: {e}')
        try:
            import pyperclip
            return pyperclip.paste()
        except Exception:
            return ""


# ── Temp File Scanner ─────────────────────────────────────────────────────────

def scan_temp_files(max_age_hours: float = 2.0) -> list[dict]:
    results = []
    cutoff  = time.time() - max_age_hours * 3600

    scan_dirs = [
        Path(os.environ.get("TEMP", "C:/Windows/Temp")),
        Path(os.environ.get("TMP",  "C:/Windows/Temp")),
        Path.home() / "AppData" / "Local" / "Temp",
    ]
    patterns = ["*.json", "*.txt", "*.md", "*.log"]

    for d in scan_dirs:
        if not d.exists():
            continue
        for pat in patterns:
            for f in list(d.glob(pat))[:20]:
                try:
                    if f.stat().st_mtime < cutoff:
                        continue
                    record = capture_file(f, source="temp_scan")
                    if record:
                        results.append(record)
                except Exception:
                    continue

    return results


# ── Context Overflow Management ───────────────────────────────────────────────

def compress_context(messages: list[dict], target_chars: int = 4000) -> list[dict]:
    total = sum(len(m.get("content", "")) for m in messages)
    if total <= target_chars:
        return messages

    recent = messages[-4:]
    older  = messages[:-4]

    if not older:
        return messages

    combined = "\n".join(
        f"{m.get('role','?')}: {m.get('content','')}" for m in older
    )
    summary = compress_semantic(combined, max_output=min(1000, target_chars // 2))
    capture_overflow(combined, source="context_compression")

    return [{"role": "system", "content": f"[Context summary]\n{summary}"}] + recent


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    return get_index().stats()


# ── Internal ──────────────────────────────────────────────────────────────────

def _index_to_won(content: str, source: str, content_type: str):
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import pipeline as _p
        _p.contribute(content, source=source,
                      mode=content_type, tags=["harvested", source])
    except Exception as e:
        _log.warning(f'caught exception: {e}')


# ── Singleton Clipboard Harvester ─────────────────────────────────────────────

_clipboard_harvester: Optional[ClipboardHarvester] = None


def start_clipboard_harvester(interval_s: float = 30.0) -> ClipboardHarvester:
    global _clipboard_harvester
    if _clipboard_harvester is None:
        _clipboard_harvester = ClipboardHarvester(interval_s)
    _clipboard_harvester.start()
    return _clipboard_harvester


def stop_clipboard_harvester():
    if _clipboard_harvester:
        _clipboard_harvester.stop()
