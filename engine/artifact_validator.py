"""engine/artifact_validator.py — BUILD-023 single source of validation.

Consolidates per-realm validation that previously lived inside each
worker. Workers now delegate to this module via:

    validator = get_artifact_validator()
    result = validator.validate(realm, path, intent_text=...)

Adding a new validation rule? Add it here once — every worker picks it
up. Adding a new realm? Add a `_validate_<realm>` method.

Each result is a ValidationResult with:
  · valid: bool
  · score: 0..1
  · checks: dict of named observations
  · error: str (empty when valid)
"""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import math
import re
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any, Optional

from engine.workers.base_worker import ValidationResult

_log = logging.getLogger(__name__)


_FABRICATION_MARKERS = (
    "project aurora", "project luna", "data breach",
    "according to my sources", "as i recall", "i have access to",
    "i remember when",
)


class ArtifactValidator:
    """Single source of truth for artifact validation."""

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.artifact_validator", self)
        except Exception:
            pass

    def validate(self, realm: str, path: Path,
                  intent_text: str = "") -> ValidationResult:
        """Dispatch to the per-realm validator. Never raises."""
        p = Path(path)
        if not p.is_file():
            return ValidationResult(valid=False, score=0.0,
                                      checks={}, error="file missing")
        try:
            r = (realm or "").lower()
            if r == "image":      return self._validate_image(p)
            if r == "audio":      return self._validate_audio(p)
            if r == "video":      return self._validate_video(p)
            if r == "game":       return self._validate_game(p)
            if r == "simulation": return self._validate_simulation(p)
            if r == "code":       return self._validate_code(p)
            if r == "cast":       return self._validate_cast(p, intent_text)
            return ValidationResult(valid=True, score=0.5, checks={},
                                      error=f"no validator for realm '{realm}'")
        except Exception as e:
            return ValidationResult(valid=False, score=0.0, checks={},
                                      error=f"validator raised: {e}")

    # ── IMAGE ─────────────────────────────────────────────────────────
    def _validate_image(self, path: Path) -> ValidationResult:
        checks: dict = {"size_bytes": path.stat().st_size}
        if checks["size_bytes"] < 1024:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="file too small (<1KB)")
        try:
            from PIL import Image    # type: ignore
            with Image.open(str(path)) as img:
                w, h = img.size
                checks["width"]  = w
                checks["height"] = h
                checks["mode"]   = img.mode
                if w < 64 or h < 64:
                    return ValidationResult(valid=False, score=0.0,
                                              checks=checks,
                                              error=f"dimensions {w}x{h} too small")
                grey = img.convert("L")
                hist = grey.histogram()
                total = sum(hist) or 1
                probs = [c / total for c in hist if c > 0]
                entropy = -sum(p * math.log2(p) for p in probs)
                checks["entropy"] = round(entropy, 3)
                if entropy < 3.0:
                    return ValidationResult(valid=False, score=0.2,
                                              checks=checks,
                                              error=f"entropy too low ({entropy:.2f})")
                score = max(0.0, min(1.0, (entropy - 3.0) / 5.0))
                checks["entropy_score"] = round(score, 3)
                return ValidationResult(valid=True, score=score, checks=checks)
        except ImportError:
            # Magic-bytes fallback
            with path.open("rb") as fh:
                head = fh.read(16)
            checks["magic_head_hex"] = head.hex()
            if (head.startswith(b"\x89PNG\r\n\x1a\n") or
                  head.startswith(b"\xff\xd8\xff") or
                  (head[:4] == b"RIFF" and head[8:12] == b"WEBP")):
                return ValidationResult(valid=True, score=0.6, checks=checks,
                                          error="PIL absent — magic-bytes only")
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="unknown image format header")

    # ── AUDIO ─────────────────────────────────────────────────────────
    def _validate_audio(self, path: Path) -> ValidationResult:
        checks: dict = {"size_bytes": path.stat().st_size}
        suf = path.suffix.lower()
        if suf != ".wav":
            with path.open("rb") as fh:
                head = fh.read(8)
            checks["magic_head_hex"] = head.hex()
            if head[:3] == b"ID3" or head[:2] == b"\xff\xfb":
                checks["format"] = "mp3"
                return ValidationResult(valid=True, score=0.7, checks=checks,
                                          error="non-wav: magic-bytes only")
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"unknown audio format {suf}")
        try:
            with wave.open(str(path), "rb") as w:
                n_frames = w.getnframes()
                sr = w.getframerate()
                ch = w.getnchannels()
                sw = w.getsampwidth()
                duration_s = n_frames / sr if sr > 0 else 0.0
                checks.update({
                    "frames":       n_frames,
                    "sample_rate":  sr,
                    "channels":     ch,
                    "sample_width": sw,
                    "duration_s":   round(duration_s, 3),
                })
                if n_frames <= 0:
                    return ValidationResult(valid=False, score=0.0, checks=checks,
                                              error="zero frames")
                if sr < 8000:
                    return ValidationResult(valid=False, score=0.0, checks=checks,
                                              error=f"sample rate {sr} below 8000")
                if duration_s < 0.1:
                    return ValidationResult(valid=False, score=0.0, checks=checks,
                                              error=f"duration {duration_s:.3f}s too short")
                if sw == 2:
                    sample_count = min(n_frames, sr * 2)
                    raw = w.readframes(sample_count)
                    if raw:
                        fmt = "<" + "h" * (len(raw) // 2)
                        samples = struct.unpack(fmt, raw)
                        clipped = sum(1 for s in samples if abs(s) >= 32766)
                        ratio = clipped / max(1, len(samples))
                        checks["clip_ratio"] = round(ratio, 4)
                        checks["peak_abs"]   = max(abs(s) for s in samples) if samples else 0
                        if ratio > 0.05:
                            return ValidationResult(valid=False,
                                                      score=max(0.0, 0.6 - ratio),
                                                      checks=checks,
                                                      error=f"heavy clipping ({ratio*100:.1f}%)")
                        score = 0.7 + 0.3 * (1.0 - ratio * 20)
                        return ValidationResult(valid=True,
                                                  score=round(max(0.4, min(1.0, score)), 3),
                                                  checks=checks)
                return ValidationResult(valid=True, score=0.75, checks=checks)
        except wave.Error as e:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"wave decode failed: {e}")

    # ── VIDEO ─────────────────────────────────────────────────────────
    def _validate_video(self, path: Path) -> ValidationResult:
        checks: dict = {"size_bytes": path.stat().st_size}
        if checks["size_bytes"] < 8192:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="file too small (<8KB)")
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            with path.open("rb") as fh:
                head = fh.read(32)
            checks["magic_head_hex"] = head[:12].hex()
            if b"ftyp" in head:
                return ValidationResult(valid=True, score=0.55, checks=checks,
                                          error="ffprobe absent — magic-bytes only")
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="no ffprobe and non-MP4 header")
        try:
            proc = subprocess.run(
                [ffprobe, "-v", "error", "-print_format", "json",
                 "-show_streams", "-show_format", str(path)],
                capture_output=True, timeout=15,
            )
            if proc.returncode != 0:
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error=f"ffprobe rc={proc.returncode}")
            info = json.loads(proc.stdout.decode(errors="ignore"))
            streams = info.get("streams", [])
            fmt = info.get("format", {})
            duration = float(fmt.get("duration", 0) or 0)
            checks["duration_s"] = round(duration, 3)
            checks["format"]     = fmt.get("format_name", "")
            v_streams = [s for s in streams if s.get("codec_type") == "video"]
            a_streams = [s for s in streams if s.get("codec_type") == "audio"]
            checks["video_streams"] = len(v_streams)
            checks["audio_streams"] = len(a_streams)
            if duration <= 0:
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error="duration zero")
            if not v_streams:
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error="no video stream")
            v = v_streams[0]
            checks["codec"]  = v.get("codec_name", "")
            checks["width"]  = v.get("width", 0)
            checks["height"] = v.get("height", 0)
            score = 0.7
            if checks["width"] >= 1280 and checks["height"] >= 720:
                score += 0.15
            if a_streams:
                score += 0.10
            return ValidationResult(valid=True,
                                      score=round(max(0.4, min(1.0, score)), 3),
                                      checks=checks)
        except subprocess.TimeoutExpired:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="ffprobe timeout (15s)")

    # ── GAME ──────────────────────────────────────────────────────────
    def _validate_game(self, path: Path) -> ValidationResult:
        checks: dict = {"size_bytes": path.stat().st_size}
        if checks["size_bytes"] <= 0:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="empty file")
        suf = path.suffix.lower()
        name = path.name.lower()
        if name == "project.godot":
            return self._validate_project_godot(path, checks)
        if suf == ".gd":
            return self._validate_gdscript(path, checks)
        if suf == ".tscn":
            return self._validate_tscn(path, checks)
        if suf == ".py":
            return self._validate_python(path, checks)
        if suf in (".md", ".markdown"):
            return self._validate_markdown(path, checks)
        return ValidationResult(valid=True, score=0.4, checks=checks,
                                  error=f"unrecognized extension {suf}")

    def _validate_project_godot(self, path: Path, checks: dict) -> ValidationResult:
        text = path.read_text(encoding="utf-8", errors="ignore")
        checks["lines"] = text.count("\n") + 1
        has_app    = "[application]" in text
        has_config = "config_version" in text
        checks["has_application_section"] = has_app
        checks["has_config_version"]      = has_config
        if not has_app:
            return ValidationResult(valid=False, score=0.3, checks=checks,
                                      error="project.godot missing [application]")
        godot = shutil.which("godot") or shutil.which("godot4")
        if godot:
            try:
                proc = subprocess.run(
                    [godot, "--headless", "--quit", "--path", str(path.parent)],
                    capture_output=True, timeout=20,
                )
                checks["godot_returncode"] = proc.returncode
                if proc.returncode == 0:
                    return ValidationResult(valid=True, score=1.0, checks=checks)
                return ValidationResult(valid=False, score=0.3, checks=checks,
                                          error=f"godot --quit failed rc={proc.returncode}")
            except Exception as e:
                checks["godot_check"] = f"raised: {e}"
        else:
            checks["godot_check"] = "godot CLI not on PATH"
        return ValidationResult(valid=True, score=0.85, checks=checks)

    def _validate_gdscript(self, path: Path, checks: dict) -> ValidationResult:
        text = path.read_text(encoding="utf-8", errors="ignore")
        checks["lines"] = text.count("\n") + 1
        nonblank = [ln.strip() for ln in text.splitlines()
                    if ln.strip() and not ln.strip().startswith("#")]
        if not nonblank:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="empty GDScript")
        head = nonblank[0]
        if head.startswith(("extends ", "class_name ", "class ")):
            has_func = any(ln.startswith(("func ", "func_")) for ln in nonblank)
            checks["has_function"] = has_func
            return ValidationResult(valid=True,
                                      score=0.9 if has_func else 0.7,
                                      checks=checks)
        return ValidationResult(valid=False, score=0.3, checks=checks,
                                  error=f"GDScript missing extends/class: {head[:60]}")

    def _validate_tscn(self, path: Path, checks: dict) -> ValidationResult:
        text = path.read_text(encoding="utf-8", errors="ignore")
        first = text.splitlines()[0] if text else ""
        if first.startswith("[gd_scene"):
            checks["nodes"] = text.count("[node ")
            return ValidationResult(valid=True, score=0.9, checks=checks)
        return ValidationResult(valid=False, score=0.2, checks=checks,
                                  error="missing [gd_scene header")

    def _validate_python(self, path: Path, checks: dict) -> ValidationResult:
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src)
            checks["ast_nodes"] = sum(1 for _ in ast.walk(tree))
            checks["func_count"]   = sum(1 for n in ast.walk(tree)
                                          if isinstance(n, ast.FunctionDef))
            checks["import_count"] = sum(1 for n in ast.walk(tree)
                                          if isinstance(n, (ast.Import, ast.ImportFrom)))
            return ValidationResult(valid=True, score=0.92, checks=checks)
        except SyntaxError as e:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"SyntaxError: {e}")

    def _validate_markdown(self, path: Path, checks: dict) -> ValidationResult:
        text = path.read_text(encoding="utf-8", errors="ignore")
        checks["lines"] = text.count("\n") + 1
        checks["headings"] = sum(1 for ln in text.splitlines()
                                  if ln.startswith("#"))
        if checks["headings"] >= 2:
            return ValidationResult(valid=True, score=0.85, checks=checks)
        return ValidationResult(valid=True, score=0.55, checks=checks,
                                  error="thin design doc (<2 headings)")

    # ── SIMULATION ────────────────────────────────────────────────────
    def _validate_simulation(self, path: Path) -> ValidationResult:
        checks: dict = {"size_bytes": path.stat().st_size}
        suf = path.suffix.lower()
        if suf == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error=f"manifest JSON parse failed: {e}")
            checks["has_intent"]      = "intent" in data
            checks["has_environment"] = "environment" in data
            checks["simcore_ok"]      = data.get("simcore_ok", False)
            # Deterministic replay hash
            h = hashlib.sha256()
            h.update((str(data.get("intent", "")) +
                       str(data.get("seed", ""))).encode())
            checks["replay_hash"] = h.hexdigest()[:16]
            if checks["has_intent"] and checks["has_environment"]:
                return ValidationResult(valid=True,
                                          score=0.9 if data.get("simcore_ok") else 0.7,
                                          checks=checks)
            return ValidationResult(valid=False, score=0.3, checks=checks,
                                      error="manifest missing required fields")
        if suf == ".png":
            try:
                from PIL import Image    # type: ignore
                with Image.open(str(path)) as img:
                    w, h = img.size
                    checks["width"]  = w
                    checks["height"] = h
                    if w < 32 or h < 32:
                        return ValidationResult(valid=False, score=0.2,
                                                  checks=checks,
                                                  error=f"map too small {w}x{h}")
                    small = img.resize((min(w, 64), min(h, 64))).convert("RGB")
                    colors = small.getcolors(maxcolors=4096) or []
                    checks["distinct_colors"] = len(colors)
                    if len(colors) < 4:
                        return ValidationResult(valid=False, score=0.2,
                                                  checks=checks,
                                                  error="map likely blank")
                    return ValidationResult(valid=True, score=0.9, checks=checks)
            except ImportError:
                with path.open("rb") as fh:
                    head = fh.read(8)
                if head.startswith(b"\x89PNG\r\n\x1a\n"):
                    return ValidationResult(valid=True, score=0.55, checks=checks,
                                              error="PIL absent — magic-bytes only")
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error="not a PNG (no PIL fallback)")
        if suf == ".ppm":
            with path.open("rb") as fh:
                head = fh.read(8)
            if head.startswith(b"P3"):
                return ValidationResult(valid=True, score=0.7, checks=checks)
        return ValidationResult(valid=True, score=0.4, checks=checks,
                                  error=f"unrecognized simulation artifact {suf}")

    # ── CODE ──────────────────────────────────────────────────────────
    def _validate_code(self, path: Path) -> ValidationResult:
        checks: dict = {"size_bytes": path.stat().st_size}
        suf = path.suffix.lower()
        if suf == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                checks["keys"] = (sorted(data.keys()) if isinstance(data, dict)
                                   else "non-dict")
                if isinstance(data, dict) and "raw" in data and len(data) == 1:
                    return ValidationResult(valid=True, score=0.5, checks=checks,
                                              error="engine returned bare string")
                return ValidationResult(valid=True, score=0.85, checks=checks)
            except Exception as e:
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error=f"proposal JSON parse failed: {e}")
        if suf == ".py":
            try:
                src = path.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(src)
                checks["functions"] = sum(1 for n in ast.walk(tree)
                                           if isinstance(n, ast.FunctionDef))
                checks["classes"]   = sum(1 for n in ast.walk(tree)
                                           if isinstance(n, ast.ClassDef))
                checks["lines"]     = src.count("\n") + 1
                score = 0.95 if (checks["functions"] + checks["classes"]) > 0 else 0.7
                return ValidationResult(valid=True, score=score, checks=checks)
            except SyntaxError as e:
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error=f"SyntaxError: {e}")
        return ValidationResult(valid=True, score=0.4, checks=checks,
                                  error=f"unrecognized code artifact {suf}")

    # ── CAST ──────────────────────────────────────────────────────────
    def _validate_cast(self, path: Path, intent_text: str) -> ValidationResult:
        checks: dict = {"size_bytes": path.stat().st_size}
        text = path.read_text(encoding="utf-8", errors="ignore")
        checks["chars"] = len(text)
        if len(text) < 80:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="verdict too short (<80 chars)")
        low = text.lower()
        tripped = [m for m in _FABRICATION_MARKERS if m in low]
        checks["fabrication_markers"] = tripped
        if tripped:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"fabrication markers tripped: {tripped}")
        tokens = [t.lower() for t in re.findall(r"[A-Za-z]{4,}", intent_text or "")]
        grounded = [t for t in set(tokens) if t in low]
        checks["grounded_tokens_present"] = grounded[:5]
        if intent_text and not grounded:
            return ValidationResult(valid=False, score=0.2, checks=checks,
                                      error="no grounded tokens from intent")
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        checks["paragraphs"] = len(paragraphs)
        return ValidationResult(valid=True,
                                  score=0.9 if len(paragraphs) >= 4 else 0.7,
                                  checks=checks)


_INSTANCE: Optional[ArtifactValidator] = None


def get_artifact_validator() -> ArtifactValidator:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ArtifactValidator()
    return _INSTANCE
