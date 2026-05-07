"""
simcore_director.py — STRATUM Cognitive Core for the Simulation Engine.

Per AI_MONITOR spec §2 (COGNITIVE CORE), this layer is DESIGNER + DIRECTOR only.

HARD RULES (enforced):
    - This module NEVER calls SnapshotStore.append, ValidationLayer.validate
      side-effects, or anything that mutates state.
    - It ONLY:
        1. classifies operator intent (IntentRouter)
        2. compiles natural language → Rule DSL (RuleCompiler)
        3. proposes candidate Events for the engine to validate (AIDirector)
    - The engine (simcore.py) is the ONLY source of truth.
    - All proposed Events still pass through ValidationLayer; rejections are
      surfaced as Director suggestions, never forced.

Public API:
    IntentRouter.classify(text) -> IntentDecision
    RuleCompiler.compile(text) -> CompiledRule         (DSL stub; deterministic)
    AIDirector.propose(world, text) -> list[Event]     (proposed; not applied)
    AIDirector.frame(world, last_tick) -> str          (narrative framing)

This module is Model-layer per CLAUDE.md §5: NO PyQt6 imports.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from simcore import Event, WorldState

_log = logging.getLogger(__name__)


# ── Intent classification ────────────────────────────────────────────────────

@dataclass
class IntentDecision:
    """Where the operator wants this input to go."""
    target: str                     # 'simulation' | 'render' | 'rule' | 'frame'
    action_hint: str = ""           # e.g. 'move', 'take', 'design_rule'
    confidence: float = 0.0
    reason: str = ""


class IntentRouter:
    """Rule-based classifier. Deterministic (same input → same decision)."""

    _ACTION_KEYS: dict[str, tuple[str, ...]] = {
        "move":   ("go ", "walk ", "head ", "move "),
        "take":   ("take ", "grab ", "pick up ", "get "),
        "drop":   ("drop ", "place ", "leave "),
        "light":  ("light ", "ignite "),
        "unlock": ("unlock ", "open with "),
    }
    _RULE_KEYS  = ("rule:", "design rule", "new rule", "add rule", "let ")
    _RENDER_KEYS = ("render", "show me", "describe", "look around", "where am i")
    _FRAME_KEYS = ("narrate", "frame", "tell the story", "what's happening")

    def classify(self, text: str) -> IntentDecision:
        if not text:
            return IntentDecision(target="simulation",
                                  reason="empty input → no-op simulation tick")
        lower = text.strip().lower()
        if any(k in lower for k in self._RULE_KEYS):
            return IntentDecision(target="rule", action_hint="design_rule",
                                  confidence=0.85,
                                  reason="rule-design keyword match")
        if any(k in lower for k in self._FRAME_KEYS):
            return IntentDecision(target="frame", action_hint="narrate",
                                  confidence=0.7,
                                  reason="framing keyword match")
        if any(k in lower for k in self._RENDER_KEYS):
            return IntentDecision(target="render", action_hint="project",
                                  confidence=0.7,
                                  reason="render keyword match")
        for action, keys in self._ACTION_KEYS.items():
            if any(lower.startswith(k) for k in keys):
                return IntentDecision(target="simulation", action_hint=action,
                                      confidence=0.8,
                                      reason=f"action keyword {action!r}")
        return IntentDecision(target="simulation", action_hint="unknown",
                              confidence=0.2,
                              reason="default → simulation; engine will reject "
                                     "if rule unknown")


# ── Rule Compiler (text → DSL) ───────────────────────────────────────────────

@dataclass
class CompiledRule:
    """A rule expressed as a structured DSL object. Deterministic compile.

    The runtime can attach this to ValidationLayer dynamically — adding new
    rules without code changes. For now the compiler is a stub that surfaces
    structure; an LLM hook can be added later without changing callers.
    """
    name: str
    triggers:      list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    effects:       list[str] = field(default_factory=list)
    raw_text:      str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "triggers": self.triggers,
            "preconditions": self.preconditions, "effects": self.effects,
            "raw_text": self.raw_text,
        }


class RuleCompiler:
    """Stub compiler: extracts triggers / when / then clauses from text.

    Grammar (case-insensitive, line-based):
        rule:  <name>
        when:  <trigger>
        if:    <precondition>     (repeatable)
        then:  <effect>           (repeatable)
    """

    _DIRECTIVES = ("rule:", "when:", "if:", "then:")

    def compile(self, text: str) -> CompiledRule:
        rule = CompiledRule(name="unnamed", raw_text=text)
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            low = line.lower()
            if low.startswith("rule:"):
                rule.name = line.split(":", 1)[1].strip() or "unnamed"
            elif low.startswith("when:"):
                rule.triggers.append(line.split(":", 1)[1].strip())
            elif low.startswith("if:"):
                rule.preconditions.append(line.split(":", 1)[1].strip())
            elif low.startswith("then:"):
                rule.effects.append(line.split(":", 1)[1].strip())
        if rule.name == "unnamed" and rule.triggers:
            rule.name = re.sub(r"\W+", "_",
                               rule.triggers[0])[:40].strip("_") or "unnamed"
        return rule


# ── AI Director — proposes Events; never applies ─────────────────────────────

class AIDirector:
    """Maps natural language → proposed Events.

    Critically: returns a *list of proposed Events* with status=PROPOSED.
    The engine validates and decides. Director never touches snapshots.
    """

    _DIR_WORDS = {"north", "south", "east", "west", "up", "down",
                  "in", "out"}

    def __init__(self, router: IntentRouter | None = None) -> None:
        self.router = router or IntentRouter()

    # Map a single input line → at most one proposed Event
    def propose(self, world: WorldState, text: str,
                actor: str = "player") -> list[Event]:
        decision = self.router.classify(text)
        if decision.target != "simulation":
            return []
        action = decision.action_hint
        text_l = text.strip().lower()

        if action == "move":
            direction = next(
                (w for w in self._DIR_WORDS
                 if re.search(rf"\b{w}\b", text_l)),
                None,
            )
            if not direction:
                return []
            return [Event.propose(actor=actor, action="move",
                                  payload={"direction": direction})]

        if action in ("take", "drop", "light"):
            target = self._best_entity_in_text(world, text_l)
            if not target:
                return []
            return [Event.propose(actor=actor, action=action, target=target)]

        if action == "unlock":
            target = self._best_entity_in_text(world, text_l)
            if not target:
                return []
            with_key = self._key_in_holds(world, actor)
            return [Event.propose(actor=actor, action="unlock", target=target,
                                  payload={"with": with_key})]

        return []

    @staticmethod
    def _best_entity_in_text(world: WorldState, text: str) -> str | None:
        for ent_id in world.entities:
            tokens = re.split(r"[_\s]+", ent_id.lower())
            if all(t in text for t in tokens if t):
                return ent_id
        return None

    @staticmethod
    def _key_in_holds(world: WorldState, actor: str) -> str | None:
        ent = world.entities.get(actor, {})
        for held in ent.get("holds", []):
            if "key" in held.lower():
                return held
        return None

    # Narrative framing — pure read-only over WorldState. NEVER mutates.
    def frame(self, world: WorldState, last_tick: dict[str, Any] | None = None
              ) -> str:
        player = world.entities.get("player", {})
        room_id = player.get("room")
        room = world.rooms.get(room_id, {}) if room_id else {}
        room_name = room.get("name", room_id or "the void")
        exits = ", ".join(sorted(room.get("exits", {}).keys())) or "none"
        held = player.get("holds", [])
        items_here = [
            eid for eid, e in world.entities.items()
            if e.get("kind") == "item" and e.get("room") == room_id
        ]
        lines = [
            f"You stand in {room_name}.",
            f"Exits: {exits}.",
            f"You carry: {', '.join(held) if held else 'nothing'}.",
            f"Visible: {', '.join(items_here) if items_here else 'no loose items'}.",
        ]
        if last_tick and not last_tick.get("accepted", True):
            lines.append(f"(your last attempt failed: {last_tick.get('reason')})")
        if world.variables.get("torch_lit"):
            lines.append("A warm light steadies the air around you.")
        return "\n".join(lines)


# ── Convenience top-level binding ────────────────────────────────────────────

class CognitiveCore:
    """Bundles IntentRouter + RuleCompiler + AIDirector for callers.
    Holds NO state — every call is pure with respect to the engine."""

    def __init__(self) -> None:
        self.router = IntentRouter()
        self.compiler = RuleCompiler()
        self.director = AIDirector(self.router)

    def propose_for_input(self, world: WorldState, text: str
                          ) -> tuple[IntentDecision, list[Event],
                                     CompiledRule | None]:
        decision = self.router.classify(text)
        events: list[Event] = []
        rule: CompiledRule | None = None
        if decision.target == "simulation":
            events = self.director.propose(world, text)
        elif decision.target == "rule":
            rule = self.compiler.compile(text)
        return (decision, events, rule)


# ── CLI — quick check ────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="simcore_director")
    p.add_argument("text", help="operator input to classify + propose")
    args = p.parse_args(argv)

    from simcore import SimCore
    sc = SimCore()
    sc.bootstrap()
    cc = CognitiveCore()
    decision, events, rule = cc.propose_for_input(sc.current_world(), args.text)
    print(json.dumps({
        "decision": {
            "target": decision.target, "action_hint": decision.action_hint,
            "confidence": decision.confidence, "reason": decision.reason,
        },
        "proposed_events": [e.to_dict() for e in events],
        "compiled_rule": rule.to_dict() if rule else None,
        "frame": cc.director.frame(sc.current_world()),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
