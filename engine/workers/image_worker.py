"""engine/workers/image_worker.py — BUILD-022 ImageWorker.

Validates:
  · file exists
  · dimensions valid (≥ 64×64)
  · entropy above threshold (uniform/blank rejection)
  · decode succeeds
  · sha256 recorded
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from engine.workers.base_worker import (
    BaseWorker, WorkerRequest, ValidationResult,
)

_log = logging.getLogger(__name__)


class ImageWorker(BaseWorker):
    REALM = "image"
    NAME  = "ImageWorker"

    def _do_execute(self, request: WorkerRequest, workspace) -> list:
        from realms.image_generation.pipeline import run as image_run
        from engine.production_core import get_production_core
        # Use a transient session bound to this workspace so the pipeline
        # writes here directly. Find or build the production session.
        core = get_production_core()
        # The base contract already opened a session; find it by workspace
        psess = None
        with core._lock:
            for s in core._sessions.values():
                if s.output_dir == str(workspace):
                    psess = s
                    break
        if psess is None:
            # Build a synthetic minimal session-like object
            class _S:
                output_dir = str(workspace)
                session_id = workspace.name
                intent_text = request.intent_text
                spec_snapshot = {}
                artifacts = []
            psess = _S()

        result = image_run(
            request.kind or "synthesize",
            {
                "intent_text": request.intent_text,
                "spec":        request.spec,
                "session":     psess,
                "frames":      int(request.params.get("frames", 1)),
            },
        )
        self._cur_backend = result.get("backend", "")
        if result.get("outcome") == "OK":
            return list(result.get("artifacts", []))
        raise RuntimeError(
            result.get("error", "image pipeline failed") + " · "
            + result.get("remediation", "")
        )

    def _validate(self, path: Path) -> ValidationResult:
        checks: dict = {}
        if not path.is_file():
            return ValidationResult(valid=False, score=0.0,
                                      checks=checks, error="file missing")
        try:
            size = path.stat().st_size
            checks["size_bytes"] = size
            if size < 1024:
                return ValidationResult(valid=False, score=0.0,
                                          checks=checks, error="file too small (<1KB)")
        except Exception as e:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"stat failed: {e}")

        # Try PIL for real decode + dimensions + entropy
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
                # Real entropy: convert to grayscale, histogram, Shannon entropy
                try:
                    import math
                    grey = img.convert("L")
                    hist = grey.histogram()
                    total = sum(hist) or 1
                    probs = [c / total for c in hist if c > 0]
                    entropy = -sum(p * math.log2(p) for p in probs)
                    checks["entropy"] = round(entropy, 3)
                    # Random image entropy ≈ 7.5, blank ≈ 0. Threshold 3.0.
                    if entropy < 3.0:
                        return ValidationResult(
                            valid=False, score=0.2, checks=checks,
                            error=f"entropy too low ({entropy:.2f}) — likely blank/uniform",
                        )
                    # Score scales with entropy 3.0..8.0
                    score = max(0.0, min(1.0, (entropy - 3.0) / 5.0))
                    checks["entropy_score"] = round(score, 3)
                    return ValidationResult(valid=True, score=score, checks=checks)
                except Exception as e:
                    # Decode succeeded; we just couldn't compute entropy
                    return ValidationResult(valid=True, score=0.7, checks=checks,
                                              error=f"entropy compute skipped: {e}")
        except ImportError:
            # PIL not available — fall back to magic-bytes check
            try:
                with path.open("rb") as fh:
                    head = fh.read(16)
                checks["magic_head_hex"] = head.hex()
                is_png  = head.startswith(b"\x89PNG\r\n\x1a\n")
                is_jpg  = head.startswith(b"\xff\xd8\xff")
                is_webp = head[:4] == b"RIFF" and head[8:12] == b"WEBP"
                if is_png or is_jpg or is_webp:
                    return ValidationResult(valid=True, score=0.6, checks=checks,
                                              error="PIL absent — magic-bytes check only")
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error="unknown image format header")
            except Exception as e:
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error=f"read failed: {e}")
        except Exception as e:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"decode failed: {e}")


_INSTANCE: Optional[ImageWorker] = None


def get_image_worker() -> ImageWorker:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ImageWorker()
    return _INSTANCE
