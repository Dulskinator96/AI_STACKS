"""engine/workers/audio_worker.py — BUILD-022 AudioWorker.

Validates:
  · file exists
  · waveform readable (wave module decode)
  · nonzero duration (frames > 0)
  · sample rate integrity (>= 8000 Hz)
  · clipping threshold (< 99% samples at peak)
"""
from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Optional

from engine.workers.base_worker import (
    BaseWorker, WorkerRequest, ValidationResult,
)

_log = logging.getLogger(__name__)


class AudioWorker(BaseWorker):
    REALM = "audio"
    NAME  = "AudioWorker"

    def _do_execute(self, request: WorkerRequest, workspace) -> list:
        from realms.audio_engine.pipeline import run as audio_run
        from engine.production_core import get_production_core
        core = get_production_core()
        psess = None
        with core._lock:
            for s in core._sessions.values():
                if s.output_dir == str(workspace):
                    psess = s
                    break
        if psess is None:
            class _S:
                output_dir = str(workspace)
                session_id = workspace.name
                intent_text = request.intent_text
                spec_snapshot = {}
                artifacts = []
            psess = _S()

        result = audio_run(
            request.kind or "soundtrack",
            {
                "intent_text": request.intent_text,
                "spec":        request.spec,
                "session":     psess,
                "track_index": int(request.params.get("track_index", 0)),
            },
        )
        self._cur_backend = result.get("backend", "")
        if result.get("outcome") == "OK":
            return list(result.get("artifacts", []))
        raise RuntimeError(
            result.get("error", "audio pipeline failed") + " · "
            + result.get("remediation", "")
        )

    def _validate(self, path: Path) -> ValidationResult:
        checks: dict = {}
        if not path.is_file():
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="file missing")
        suf = path.suffix.lower()
        if suf == ".wav":
            return self._validate_wav(path)
        # Non-wav (mp3 / m4a): just check size + magic bytes
        size = path.stat().st_size
        checks["size_bytes"] = size
        if size < 1024:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="file too small")
        with path.open("rb") as fh:
            head = fh.read(8)
        checks["magic_head_hex"] = head.hex()
        if head[:3] == b"ID3" or head[:2] == b"\xff\xfb":
            checks["format"] = "mp3"
            return ValidationResult(valid=True, score=0.7, checks=checks,
                                      error="non-wav: magic-bytes only")
        return ValidationResult(valid=False, score=0.0, checks=checks,
                                  error=f"unknown audio format {suf}")

    def _validate_wav(self, path: Path) -> ValidationResult:
        checks: dict = {"size_bytes": path.stat().st_size}
        try:
            with wave.open(str(path), "rb") as w:
                n_frames = w.getnframes()
                sr = w.getframerate()
                ch = w.getnchannels()
                sw = w.getsampwidth()
                duration_s = n_frames / sr if sr > 0 else 0.0
                checks["frames"]      = n_frames
                checks["sample_rate"] = sr
                checks["channels"]    = ch
                checks["sample_width"]= sw
                checks["duration_s"]  = round(duration_s, 3)

                if n_frames <= 0:
                    return ValidationResult(valid=False, score=0.0, checks=checks,
                                              error="zero frames")
                if sr < 8000:
                    return ValidationResult(valid=False, score=0.0, checks=checks,
                                              error=f"sample rate {sr} below 8000 Hz")
                if duration_s < 0.1:
                    return ValidationResult(valid=False, score=0.0, checks=checks,
                                              error=f"duration {duration_s:.3f}s too short")

                # Clipping check: read a sample of frames
                try:
                    import struct
                    sample_count = min(n_frames, sr * 2)   # up to 2 seconds
                    raw = w.readframes(sample_count)
                    if sw == 2:
                        fmt = "<" + "h" * (len(raw) // 2)
                        if fmt == "<":
                            checks["clip_check"] = "skipped (empty read)"
                            return ValidationResult(valid=True, score=0.85, checks=checks)
                        samples = struct.unpack(fmt, raw)
                        peak = 32767
                        clipped = sum(1 for s in samples if abs(s) >= peak - 1)
                        ratio = clipped / max(1, len(samples))
                        checks["clip_ratio"] = round(ratio, 4)
                        if ratio > 0.05:
                            return ValidationResult(valid=False,
                                                      score=max(0.0, 0.6 - ratio),
                                                      checks=checks,
                                                      error=f"heavy clipping ({ratio*100:.1f}% peaks)")
                        # Real peak as fraction of max
                        peak_abs = max(abs(s) for s in samples) if samples else 0
                        checks["peak_abs"] = peak_abs
                        # Strong score if real signal with mild peaks
                        score = 0.7 + 0.3 * (1.0 - ratio * 20)
                        score = max(0.4, min(1.0, score))
                        return ValidationResult(valid=True, score=round(score, 3),
                                                  checks=checks)
                    else:
                        checks["clip_check"] = f"skipped (sample_width={sw})"
                        return ValidationResult(valid=True, score=0.75, checks=checks)
                except Exception as e:
                    checks["clip_check"] = f"failed: {e}"
                    return ValidationResult(valid=True, score=0.7, checks=checks,
                                              error=f"clip check skipped: {e}")
        except wave.Error as e:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"wave decode failed: {e}")
        except Exception as e:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"validation raised: {e}")


_INSTANCE: Optional[AudioWorker] = None


def get_audio_worker() -> AudioWorker:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = AudioWorker()
    return _INSTANCE
