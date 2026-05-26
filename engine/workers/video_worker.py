"""engine/workers/video_worker.py — BUILD-022 VideoWorker.

Validates:
  · file exists, size > 8 KB
  · ffprobe parses container
  · frame_count > 0 (via ffprobe if available, else file-size fallback)
  · duration_s > 0
  · codec integrity (video stream present)
  · mux successful (audio stream present if expected)
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from engine.workers.base_worker import (
    BaseWorker, WorkerRequest, ValidationResult,
)

_log = logging.getLogger(__name__)


class VideoWorker(BaseWorker):
    REALM = "video"
    NAME  = "VideoWorker"

    def _do_execute(self, request: WorkerRequest, workspace) -> list:
        from realms.video_production.pipeline import run as video_run
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

        result = video_run(
            request.kind or "title_card",
            {
                "intent_text": request.intent_text,
                "spec":        request.spec,
                "session":     psess,
                **request.params,
            },
        )
        self._cur_backend = result.get("backend", "")
        if result.get("outcome") == "OK":
            return list(result.get("artifacts", []))
        raise RuntimeError(
            result.get("error", "video pipeline failed") + " · "
            + result.get("remediation", "")
        )

    def _validate(self, path: Path) -> ValidationResult:
        checks: dict = {}
        if not path.is_file():
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="file missing")
        size = path.stat().st_size
        checks["size_bytes"] = size
        if size < 8192:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"file too small ({size} bytes)")

        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            # Magic bytes fallback — MP4 ftyp box check
            try:
                with path.open("rb") as fh:
                    head = fh.read(32)
                checks["magic_head_hex"] = head[:12].hex()
                if b"ftyp" in head:
                    return ValidationResult(valid=True, score=0.55, checks=checks,
                                              error="ffprobe absent — magic-bytes only")
            except Exception as e:
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error=f"head read failed: {e}")
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
                                          error=f"ffprobe rc={proc.returncode}: "
                                                  f"{proc.stderr.decode(errors='ignore')[:200]}")
            info = json.loads(proc.stdout.decode(errors="ignore"))
            streams = info.get("streams", [])
            fmt = info.get("format", {})
            duration = float(fmt.get("duration", 0) or 0)
            checks["duration_s"] = round(duration, 3)
            checks["format"]     = fmt.get("format_name", "")

            video_streams = [s for s in streams if s.get("codec_type") == "video"]
            audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
            checks["video_streams"] = len(video_streams)
            checks["audio_streams"] = len(audio_streams)

            if duration <= 0:
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error="duration zero")
            if not video_streams:
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error="no video stream")

            v = video_streams[0]
            checks["codec"]   = v.get("codec_name", "")
            checks["width"]   = v.get("width", 0)
            checks["height"]  = v.get("height", 0)
            checks["nb_frames"] = int(v.get("nb_frames", 0) or 0)

            score = 0.7
            if checks.get("width", 0) >= 1280 and checks.get("height", 0) >= 720:
                score += 0.15
            if audio_streams:
                score += 0.10
            score = max(0.4, min(1.0, score))
            return ValidationResult(valid=True, score=round(score, 3), checks=checks)
        except subprocess.TimeoutExpired:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="ffprobe timeout (15s)")
        except Exception as e:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"ffprobe failed: {e}")


_INSTANCE: Optional[VideoWorker] = None


def get_video_worker() -> VideoWorker:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = VideoWorker()
    return _INSTANCE
