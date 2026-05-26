"""engine/preview_registry.py — BUILD-022 PreviewRegistry.

Auto-registers a preview for every completed artifact. Used by the
Production Console / Preview Wall to show:
  · image artifacts → thumbnail path (PIL-downscaled if available)
  · audio artifacts → waveform summary (peak envelope)
  · video artifacts → ffprobe-extracted poster frame (if ffmpeg present)
  · game artifacts  → text excerpt (first 600 chars of design doc / scene)
  · simulation maps → same as image
  · code            → first 80 lines + symbol summary

Persisted state in-memory + JSONL at telemetry/preview_registry.jsonl.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


_PREVIEW_LOG = Path(__file__).resolve().parent.parent / "telemetry" / "preview_registry.jsonl"
_PREVIEW_DIR = Path(__file__).resolve().parent.parent / "telemetry" / "previews"


@dataclass
class PreviewEntry:
    preview_id:     str
    artifact_path:  str
    realm:          str
    backend:        str
    session_id:     str
    preview_kind:   str           # thumbnail|waveform|poster_frame|text_excerpt|symbol_summary
    preview_path:   Optional[str] # path to generated preview file (if any)
    summary:        dict = field(default_factory=dict)
    created_at:     float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class PreviewRegistry:
    """Auto-preview generator + registry."""

    def __init__(self):
        self._lock = threading.RLock()
        self._entries: dict[str, PreviewEntry] = {}
        self._cap = 500
        try:
            _PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.preview_registry", self)
        except Exception:
            pass

    def register_preview(self, *, artifact_path: str, realm: str,
                          backend: str, session_id: str) -> Optional[PreviewEntry]:
        """Generate a preview for the artifact and register it. Returns
        the PreviewEntry or None on failure."""
        p = Path(artifact_path)
        if not p.is_file():
            return None
        kind, preview_path, summary = self._generate(p, realm)
        if kind is None:
            return None
        entry = PreviewEntry(
            preview_id=f"prev-{uuid.uuid4().hex[:10]}",
            artifact_path=str(p),
            realm=realm,
            backend=backend,
            session_id=session_id,
            preview_kind=kind,
            preview_path=preview_path,
            summary=summary,
            created_at=time.time(),
        )
        with self._lock:
            self._entries[entry.preview_id] = entry
            if len(self._entries) > self._cap:
                # Evict oldest by created_at
                victim = min(self._entries.values(), key=lambda e: e.created_at)
                self._entries.pop(victim.preview_id, None)
        self._persist(entry)
        self._emit_receipt(entry)
        return entry

    def recent(self, n: int = 20, realm: Optional[str] = None) -> list:
        with self._lock:
            entries = sorted(self._entries.values(),
                              key=lambda e: -e.created_at)
        if realm:
            entries = [e for e in entries if e.realm == realm]
        return entries[:n]

    def for_session(self, session_id: str) -> list:
        with self._lock:
            return [e for e in self._entries.values()
                    if e.session_id == session_id]

    def stats(self) -> dict:
        with self._lock:
            return {
                "count":       len(self._entries),
                "per_realm":   self._per_realm(),
                "cap":         self._cap,
                "preview_dir": str(_PREVIEW_DIR),
            }

    def _per_realm(self) -> dict:
        d: dict[str, int] = {}
        for e in self._entries.values():
            d[e.realm] = d.get(e.realm, 0) + 1
        return d

    # ── Per-realm preview generators ─────────────────────────────────
    def _generate(self, p: Path, realm: str):
        suf = p.suffix.lower()
        if realm == "image" or suf in (".png", ".jpg", ".jpeg", ".webp"):
            return self._image_preview(p)
        if realm == "audio" or suf in (".wav", ".mp3", ".m4a", ".aac", ".flac"):
            return self._audio_preview(p)
        if realm == "video" or suf in (".mp4", ".mov", ".mkv", ".webm"):
            return self._video_preview(p)
        if suf in (".py", ".gd"):
            return self._code_preview(p)
        if suf in (".md", ".markdown", ".tscn", ".godot"):
            return self._text_preview(p)
        if suf == ".json":
            return self._json_preview(p)
        return self._generic_preview(p)

    def _image_preview(self, p: Path):
        try:
            from PIL import Image    # type: ignore
            with Image.open(str(p)) as img:
                w, h = img.size
                # Downscale to 256-px-wide thumbnail
                thumb = img.copy()
                thumb.thumbnail((256, 256))
                thumb_path = _PREVIEW_DIR / f"thumb_{p.stem}_{int(time.time()*1000)}.png"
                thumb.save(str(thumb_path))
                return ("thumbnail", str(thumb_path), {
                    "original_width":  w, "original_height": h,
                    "thumb_size":      thumb.size,
                })
        except ImportError:
            return ("thumbnail", str(p), {"note": "PIL absent — using original"})
        except Exception as e:
            return ("thumbnail", str(p), {"error": str(e)})

    def _audio_preview(self, p: Path):
        suf = p.suffix.lower()
        if suf != ".wav":
            return ("waveform", str(p), {"format": suf, "note": "non-wav preview"})
        try:
            import wave
            import struct
            with wave.open(str(p), "rb") as w:
                sr = w.getframerate()
                ch = w.getnchannels()
                sw = w.getsampwidth()
                n_frames = w.getnframes()
                duration_s = n_frames / sr if sr > 0 else 0.0
                # Peak envelope: 64 buckets
                if sw == 2 and n_frames > 0:
                    bucket_count = 64
                    bucket_size = max(1, n_frames // bucket_count)
                    peaks: list[float] = []
                    for _ in range(bucket_count):
                        raw = w.readframes(bucket_size)
                        if not raw:
                            break
                        fmt = "<" + "h" * (len(raw) // 2)
                        if fmt == "<":
                            peaks.append(0.0)
                            continue
                        samples = struct.unpack(fmt, raw)
                        peaks.append(round(max(abs(s) for s in samples) / 32768.0, 3))
                    return ("waveform", None, {
                        "sample_rate":  sr, "channels": ch,
                        "duration_s":   round(duration_s, 3),
                        "peak_envelope": peaks,
                    })
                return ("waveform", None, {
                    "sample_rate": sr, "channels": ch,
                    "duration_s":  round(duration_s, 3),
                    "note":        f"sample_width={sw} (envelope skipped)",
                })
        except Exception as e:
            return ("waveform", None, {"error": str(e)})

    def _video_preview(self, p: Path):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return ("poster_frame", None,
                    {"note": "ffmpeg absent — no poster extraction"})
        try:
            poster_path = _PREVIEW_DIR / f"poster_{p.stem}_{int(time.time()*1000)}.png"
            proc = subprocess.run(
                [ffmpeg, "-y", "-ss", "0.5", "-i", str(p),
                 "-frames:v", "1", "-vf", "scale=480:-1",
                 str(poster_path)],
                capture_output=True, timeout=20,
            )
            if proc.returncode == 0 and poster_path.is_file():
                return ("poster_frame", str(poster_path), {
                    "extracted_at": 0.5,
                })
            return ("poster_frame", None,
                    {"error": proc.stderr.decode(errors="ignore")[:200]})
        except Exception as e:
            return ("poster_frame", None, {"error": str(e)})

    def _code_preview(self, p: Path):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            lines = text.splitlines()
            head = "\n".join(lines[:80])
            symbols: list[str] = []
            if p.suffix == ".py":
                import ast
                try:
                    tree = ast.parse(text)
                    for n in ast.walk(tree):
                        if isinstance(n, ast.FunctionDef):
                            symbols.append(f"def {n.name}")
                        elif isinstance(n, ast.ClassDef):
                            symbols.append(f"class {n.name}")
                except Exception:
                    pass
            elif p.suffix == ".gd":
                for ln in lines:
                    s = ln.strip()
                    if s.startswith("func "):
                        symbols.append(s.split("(")[0])
                    elif s.startswith(("class ", "class_name ", "extends ")):
                        symbols.append(s)
            return ("symbol_summary", None, {
                "line_count": len(lines),
                "head":       head,
                "symbols":    symbols[:32],
            })
        except Exception as e:
            return ("symbol_summary", None, {"error": str(e)})

    def _text_preview(self, p: Path):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            return ("text_excerpt", None, {
                "char_count": len(text),
                "excerpt":    text[:600],
            })
        except Exception as e:
            return ("text_excerpt", None, {"error": str(e)})

    def _json_preview(self, p: Path):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            data = json.loads(text)
            keys = list(data.keys()) if isinstance(data, dict) else ["(list)"]
            return ("text_excerpt", None, {
                "json_keys": keys[:24],
                "excerpt":   text[:600],
            })
        except Exception as e:
            return ("text_excerpt", None, {"error": str(e)})

    def _generic_preview(self, p: Path):
        return ("text_excerpt", None, {
            "size_bytes": p.stat().st_size,
            "extension":  p.suffix,
        })

    def _persist(self, entry: PreviewEntry) -> None:
        try:
            _PREVIEW_LOG.parent.mkdir(parents=True, exist_ok=True)
            with _PREVIEW_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry.to_dict()) + "\n")
        except Exception as e:
            _log.debug("preview persist failed: %s", e)

    def _emit_receipt(self, entry: PreviewEntry) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"preview:registered:{entry.realm}",
                executor="PreviewRegistry",
                duration_ms=0.0,
                verified=True,
                compute_sha256=False,
                evidence={
                    "preview_id":   entry.preview_id,
                    "realm":        entry.realm,
                    "preview_kind": entry.preview_kind,
                    "preview_path": entry.preview_path,
                    "session_id":   entry.session_id,
                    "backend":      entry.backend,
                },
            )
        except Exception:
            pass


_INSTANCE: Optional[PreviewRegistry] = None


def get_preview_registry() -> PreviewRegistry:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = PreviewRegistry()
    return _INSTANCE
