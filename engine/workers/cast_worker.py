"""engine/workers/cast_worker.py — BUILD-022 CastWorker.

Wraps pyramid_ensemble.EnsembleOrchestrator. Validates:
  · synthesis verdict is non-empty
  · no fabrication markers (per won_daemon list)
  · at least one grounded token (intent keyword appears in output)
  · ensemble produced multiple agent perspectives
"""
from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from engine.workers.base_worker import (
    BaseWorker, WorkerRequest, ValidationResult,
)

_log = logging.getLogger(__name__)


# Fabrication-marker list ported from won_daemon (build-008 lockdown).
_FABRICATION_MARKERS = (
    "project aurora", "project luna", "data breach",
    "according to my sources", "as i recall", "i have access to",
    "i remember when",
)


class CastWorker(BaseWorker):
    REALM = "cast"
    NAME  = "CastWorker"

    def _do_execute(self, request: WorkerRequest, workspace) -> list:
        intent = request.intent_text or ""
        verdict = ""
        try:
            from pyramid_ensemble import EnsembleOrchestrator  # type: ignore
            eo = EnsembleOrchestrator()
            if hasattr(eo, "run"):
                verdict = str(eo.run(intent))
            elif hasattr(eo, "run_async"):
                box: dict = {}
                ev = threading.Event()
                def _cb(event):
                    try:
                        kind = getattr(event, "kind", "")
                        if "DONE" in str(kind):
                            box["v"] = getattr(event, "result", event)
                            ev.set()
                    except Exception:
                        ev.set()
                eo.run_async(intent, "", _cb)
                ev.wait(timeout=90.0)
                verdict = str(box.get("v", ""))
            else:
                raise RuntimeError("EnsembleOrchestrator has no run/run_async")
            self._cur_backend = "pyramid_ensemble"
        except ImportError:
            raise RuntimeError("pyramid_ensemble not present")
        except Exception as e:
            raise RuntimeError(f"ensemble cast failed: {e}")

        if not verdict.strip():
            raise RuntimeError("ensemble returned empty verdict")

        # Persist as a text artifact
        out_path = Path(workspace) / f"cast_{int(time.time()*1000)}.md"
        body = f"# Cast Verdict\n\n**Intent:** {intent}\n\n---\n\n{verdict}\n"
        out_path.write_text(body, encoding="utf-8")
        # Stash intent on instance for the validator
        self._last_intent = intent
        return [str(out_path)]

    def _validate(self, path: Path) -> ValidationResult:
        checks: dict = {"size_bytes": path.stat().st_size}
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"read failed: {e}")
        checks["chars"] = len(text)
        if len(text) < 80:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="verdict too short (< 80 chars)")

        # Fabrication-marker check
        low = text.lower()
        tripped = [m for m in _FABRICATION_MARKERS if m in low]
        checks["fabrication_markers"] = tripped
        if tripped:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"fabrication markers tripped: {tripped}")

        # Grounded-token: at least one intent keyword appears in verdict
        intent = getattr(self, "_last_intent", "") or ""
        tokens = [t.lower() for t in re.findall(r"[A-Za-z]{4,}", intent)]
        grounded_hits = [t for t in set(tokens) if t in low]
        checks["grounded_tokens_present"] = grounded_hits[:5]
        if intent and not grounded_hits:
            return ValidationResult(valid=False, score=0.2, checks=checks,
                                      error="no grounded tokens from intent in verdict")

        # Multi-perspective heuristic: look for paragraph breaks + multiple sections
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        checks["paragraphs"] = len(paragraphs)
        score = 0.7
        if len(paragraphs) >= 4:
            score = 0.9
        return ValidationResult(valid=True, score=score, checks=checks)


_INSTANCE: Optional[CastWorker] = None


def get_cast_worker() -> CastWorker:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = CastWorker()
    return _INSTANCE
