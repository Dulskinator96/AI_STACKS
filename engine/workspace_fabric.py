"""engine/workspace_fabric.py — BUILD-020 SECTION 6: DYNAMIC WORKSPACE FABRIC.

Spawn constellations of workspaces from a single intent. Replaces the
"endless static tabs" model with intent-generated, hot-loadable rooms.

Constellation recipes:
  · movie / trailer / cinematic    → screenplay + storyboard + soundtrack
                                       + timeline + lore
  · game / world / simulation       → world_lore + mechanics + soundtrack
                                       + concept_art + sim
  · soundtrack / song / score       → soundtrack + lyric_concept
  · image / scene / portrait        → concept_art + reference_board
  · code / project / scaffold       → architecture + scaffold + test_plan

Each member of a constellation is a separate WorkspaceSession spawned
through the existing DynamicWorkspaceSpawner — preserving the build-018
tab lifecycle. The fabric just orchestrates which members to spawn.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass
class Constellation:
    constellation_id: str
    intent_text:      str
    pattern:          str            # e.g. "movie", "game", "soundtrack"
    realm:            str            # primary realm (delegate to RealmDispatcher)
    sessions:         list = field(default_factory=list)   # WorkspaceSession objects
    spawned_at:       float = 0.0

    def to_dict(self) -> dict:
        return {
            "constellation_id": self.constellation_id,
            "intent_text":      self.intent_text[:200],
            "pattern":           self.pattern,
            "realm":             self.realm,
            "session_count":     len(self.sessions),
            "session_ids":       [s.session_id for s in self.sessions],
            "spawned_at":        self.spawned_at,
        }


# Pattern recipes — (keyword regex → constellation members)
_PATTERNS = [
    ("movie",      r"\b(movie|trailer|cinematic|film|short film|reel)\b",
     ["screenplay", "storyboard", "soundtrack", "timeline", "lore"]),
    ("game",       r"\b(game|playable|gameplay|level|world|simulation)\b",
     ["world_lore", "mechanics", "soundtrack", "concept_art", "sim"]),
    ("soundtrack", r"\b(soundtrack|song|score|track|music|theme)\b",
     ["soundtrack", "lyric_concept"]),
    ("scene",      r"\b(scene|image|portrait|render|illustration|picture)\b",
     ["concept_art", "reference_board"]),
    ("code",       r"\b(project|scaffold|architecture|codebase|module)\b",
     ["architecture", "scaffold", "test_plan"]),
    ("story",      r"\b(story|narrative|chapter|saga|lore)\b",
     ["lore", "screenplay"]),
]

_MEMBER_TO_REALM = {
    "screenplay":     "cast",
    "storyboard":     "image",
    "soundtrack":     "audio",
    "timeline":       "video",
    "lore":           "cast",
    "world_lore":     "cast",
    "mechanics":      "game",
    "concept_art":    "image",
    "sim":            "game",
    "lyric_concept":  "cast",
    "reference_board":"image",
    "architecture":   "code",
    "scaffold":       "code",
    "test_plan":      "code",
}


class WorkspaceFabric:
    """Orchestrates multi-workspace constellations from intent."""

    def __init__(self):
        self._constellations: dict[str, Constellation] = {}
        self._lock = threading.RLock()
        self._spawn_count = 0
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.workspace_fabric", self)
        except Exception:
            pass

    def detect_pattern(self, intent_text: str) -> Optional[str]:
        """Return the pattern name if intent matches a constellation
        recipe, else None."""
        text = (intent_text or "").lower()
        for name, pat, _members in _PATTERNS:
            if re.search(pat, text):
                return name
        return None

    def members_for_pattern(self, pattern: str) -> list:
        for name, _pat, members in _PATTERNS:
            if name == pattern:
                return list(members)
        return []

    def should_spawn_constellation(self, intent_text: str) -> bool:
        """Heuristic: spawn if pattern detected AND intent has at least
        one ambition keyword (legendary/cinematic/production/etc)."""
        if self.detect_pattern(intent_text) is None:
            return False
        text = (intent_text or "").lower()
        ambition_hints = ("legendary", "epic", "cinematic", "production",
                           "polished", "masterpiece", "full", "complete")
        return any(k in text for k in ambition_hints)

    def spawn_constellation(self, intent_text: str,
                              pattern: Optional[str] = None,
                              plan: Any = None) -> Optional[Constellation]:
        """Spawn the constellation members. Returns the Constellation or
        None if no pattern matched. Sessions go through the existing
        DynamicWorkspaceSpawner so the tab lifecycle is preserved."""
        pat = pattern or self.detect_pattern(intent_text)
        if pat is None:
            return None
        members = self.members_for_pattern(pat)
        if not members:
            return None
        try:
            from runtime.workspace_spawner import get_workspace_spawner
            spawner = get_workspace_spawner()
        except Exception as e:
            _log.warning("workspace_spawner unavailable: %s", e)
            return None

        cid = f"const-{uuid.uuid4().hex[:8]}"
        constellation = Constellation(
            constellation_id=cid, intent_text=intent_text or "",
            pattern=pat, realm=_MEMBER_TO_REALM.get(members[0], "cast"),
            spawned_at=time.time(),
        )

        # Spawn each member
        for member in members:
            member_realm = _MEMBER_TO_REALM.get(member, "cast")
            member_intent = f"[{pat}/{member}] {intent_text}"
            session = spawner.spawn(member_intent, member_realm, plan)
            if session is not None:
                constellation.sessions.append(session)
                session.log(f"constellation '{pat}' member: {member}")

        with self._lock:
            self._constellations[cid] = constellation
            self._spawn_count += 1
        self._emit_receipt(constellation)
        return constellation

    def get_constellation(self, cid: str) -> Optional[Constellation]:
        with self._lock:
            return self._constellations.get(cid)

    def active_constellations(self) -> list:
        with self._lock:
            return list(self._constellations.values())

    def stats(self) -> dict:
        with self._lock:
            return {
                "spawn_count":    self._spawn_count,
                "active_count":   len(self._constellations),
                "patterns_known": [p[0] for p in _PATTERNS],
            }

    def _emit_receipt(self, c: Constellation) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"workspace_fabric:constellation:{c.pattern}",
                executor="WorkspaceFabric",
                duration_ms=0.0,
                verified=(len(c.sessions) > 0),
                compute_sha256=False,
                failure_reason=("no sessions spawned" if not c.sessions else None),
                evidence=c.to_dict(),
            )
        except Exception:
            pass


_FABRIC_INSTANCE: Optional[WorkspaceFabric] = None


def get_workspace_fabric() -> WorkspaceFabric:
    global _FABRIC_INSTANCE
    if _FABRIC_INSTANCE is None:
        _FABRIC_INSTANCE = WorkspaceFabric()
    return _FABRIC_INSTANCE
