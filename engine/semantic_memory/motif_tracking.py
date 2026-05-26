"""engine/semantic_memory/motif_tracking.py — recurring motif detection."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)
_PATH = Path(__file__).resolve().parent.parent.parent / "telemetry" / "motif_registry.json"


_MOTIF_PATTERNS = [
    (r"\b(neon|cyber|rim ?light|hologr)", "neon_cyber"),
    (r"\b(legendary|epic|heroic|mythic)", "heroic_scale"),
    (r"\b(dark|grim|noir|brooding)", "dark_undercurrent"),
    (r"\b(emotional|melanchol|wistful|longing)", "emotional_anchor"),
    (r"\b(cinemat|trailer|sequence|montage)", "cinematic_framing"),
    (r"\b(tactical|strategy|simul|map)", "tactical_systems"),
    (r"\b(forest|desert|ruin|temple|cathedr)", "place_iconic"),
    (r"\b(fight|battle|combat|clash)", "conflict_beats"),
    (r"\b(soundtrack|score|theme|underscore)", "sound_anchor"),
    (r"\b(stylized|painterly|cel|anime)", "stylization"),
]


class MotifTracker:
    """Counts recurring creative motifs across intent history. JSON-backed."""

    def __init__(self):
        self._lock = threading.RLock()
        self._counter: Counter = Counter()
        self._load()
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.motif_tracker", self)
        except Exception:
            pass

    def _load(self) -> None:
        if not _PATH.is_file():
            return
        try:
            data = json.loads(_PATH.read_text(encoding="utf-8"))
            self._counter.update(data.get("motifs", {}))
        except Exception as e:
            _log.warning("motif load failed: %s", e)

    def _persist(self) -> None:
        try:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = {"motifs": dict(self._counter), "updated_at": time.time()}
            _PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as e:
            _log.warning("motif persist failed: %s", e)

    def observe(self, intent_text: str) -> list:
        """Detect motifs in an intent and update counts. Returns the
        motif tags detected in this observation."""
        t = (intent_text or "").lower()
        detected: list[str] = []
        for pat, tag in _MOTIF_PATTERNS:
            if re.search(pat, t):
                detected.append(tag)
        with self._lock:
            for tag in detected:
                self._counter[tag] += 1
            self._persist()
        return detected

    def top_motifs(self, n: int = 5) -> list:
        with self._lock:
            return [tag for tag, _ in self._counter.most_common(n)]

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "motifs":      dict(self._counter),
                "top":         [tag for tag, _ in self._counter.most_common(5)],
                "total_observed": sum(self._counter.values()),
            }


_INSTANCE: Optional[MotifTracker] = None


def get_motif_tracker() -> MotifTracker:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = MotifTracker()
    return _INSTANCE
