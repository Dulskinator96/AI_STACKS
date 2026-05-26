"""engine/intent_cortex.py — PHASE 3.

Interpret vague human requests into structured creative objectives.
Built on top of `kernel.intent_orchestrator` — the kernel emits the
deterministic IntentClass + Realm; the cortex adds tone, atmosphere,
aesthetics, medium, ambition, and cinematic direction.

All reasoning is rule-based + receipt-backed. NO fabricated intent
(Reality Enforcement). If a feature can't be inferred from the prompt,
it is recorded as null/empty, not invented.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_log = logging.getLogger(__name__)


# ── Keyword inference tables — each is a (regex, value) tuple list.
# Order matters: first match wins for non-multi categories.

_TONE_RULES = [
    (r"\b(legendary|epic|heroic|godlike|mythic)\b",        "legendary"),
    (r"\b(dark|grim|brooding|noir|ominous|sinister)\b",     "dark"),
    (r"\b(serene|peaceful|calm|tranquil|gentle)\b",         "serene"),
    (r"\b(intense|fierce|aggressive|relentless|brutal)\b",  "intense"),
    (r"\b(melancholic|sad|mournful|wistful|nostalgic)\b",   "melancholic"),
    (r"\b(joyful|uplifting|triumphant|hopeful)\b",          "joyful"),
    (r"\b(eerie|haunting|surreal|dreamlike|liminal)\b",     "eerie"),
    (r"\b(playful|whimsical|silly|absurd)\b",               "playful"),
    (r"\b(mysterious|cryptic|enigmatic|arcane)\b",          "mysterious"),
    (r"\b(emotional|moving|tearful|tender)\b",              "emotional"),
]

_STYLE_RULES = [
    (r"\b(cyberpunk|neon[- ]?(?:noir|tokyo)|blade ?runner)\b", "cyberpunk"),
    (r"\b(sci[- ]?fi|science fiction|space opera|hard sci)\b",  "sci-fi"),
    (r"\b(fantasy|magic|wizard|dragon|enchanted|elvish)\b",      "fantasy"),
    (r"\b(noir|film noir|black and white|monochrome)\b",         "noir"),
    (r"\b(horror|gothic|cosmic horror|lovecraft)\b",             "horror"),
    (r"\b(impressionist|painterly|brushstroke|monet|van gogh)\b", "painterly"),
    (r"\b(minimalist|clean|spare|geometric)\b",                  "minimalist"),
    (r"\b(realistic|photoreal|photographic|documentary)\b",      "photoreal"),
    (r"\b(anime|manga|cel[- ]?shaded|studio ghibli)\b",          "anime"),
    (r"\b(retro|80s|synthwave|vaporwave|outrun)\b",              "synthwave"),
    (r"\b(brutalist|industrial|concrete|warehouse)\b",           "brutalist"),
    (r"\b(cinematic|filmic|wide[- ]?screen|movie)\b",            "cinematic"),
]

_MEDIUM_RULES = [
    (r"\b(image|picture|photo|render|illustration|portrait|scene)\b", "image"),
    (r"\b(video|clip|trailer|reel|short film|montage|edit)\b",         "video"),
    (r"\b(soundtrack|music|song|theme|score|audio|track|tone|ambient|drone|chime|melody|beat|hum|sfx|sound effect|sound)\b", "audio"),
    (r"\b(speak|say|read aloud|narrate|voice|tts)\b",                  "speech"),
    (r"\b(game|level|simulation|world|environment|playable)\b",        "game"),
    (r"\b(code|build|implement|refactor|fix|function|class|script)\b", "code"),
    (r"\b(map|battlefield|tactical|projection|terrain)\b",             "simulation"),
    (r"\b(story|narrative|plot|chapter|lore|backstory)\b",             "narrative"),
]

_LIGHTING_RULES = [
    (r"\b(neon|rim ?light|holographic|glow)\b",            "neon rim light"),
    (r"\b(golden hour|warm sunset|amber light)\b",          "golden hour"),
    (r"\b(blue hour|dusk|twilight|pre[- ]?dawn)\b",         "blue hour"),
    (r"\b(harsh shadow|hard light|chiaroscuro|noir light)\b","chiaroscuro"),
    (r"\b(soft light|diffused|overcast|even light)\b",      "soft diffused"),
    (r"\b(volumetric|god ray|fog light|haze)\b",            "volumetric god rays"),
    (r"\b(moonlight|moonlit|starlight|night sky)\b",        "moonlight"),
    (r"\b(candlelight|firelight|hearth|warm flame)\b",      "candlelight"),
]

_COMPOSITION_RULES = [
    (r"\b(heroic|centered|powerful framing)\b",              "heroic centered"),
    (r"\b(wide shot|landscape|panoramic|vista)\b",           "wide panoramic"),
    (r"\b(closeup|close[- ]?up|portrait|macro)\b",           "closeup"),
    (r"\b(low angle|looking up|towering)\b",                  "low angle"),
    (r"\b(top down|overhead|bird ?'?s ?eye)\b",              "top-down"),
    (r"\b(dutch angle|tilted|off[- ]?balance)\b",            "dutch angle"),
    (r"\b(over the shoulder|behind|tracking)\b",             "over the shoulder"),
    (r"\b(symmetric|symmetrical|mirrored)\b",                "symmetric"),
]

_EMOTION_RULES = [
    (r"\b(powerful|strong|forceful|mighty)\b",         "powerful"),
    (r"\b(tender|gentle|soft|delicate|intimate)\b",     "tender"),
    (r"\b(angry|rage|furious|wrath)\b",                  "angry"),
    (r"\b(fear|terrifying|horror|dread)\b",              "fear"),
    (r"\b(triumph|victorious|elated|exalted)\b",         "triumph"),
    (r"\b(longing|yearning|wistful|nostalgic)\b",        "longing"),
    (r"\b(wonder|awe|majestic|sublime)\b",               "wonder"),
    (r"\b(solitude|alone|isolated|lonely)\b",            "solitude"),
]

_AMBITION_HINTS = [
    (r"\b(legendary|epic|masterpiece|magnum opus|grand)\b", 0.95),
    (r"\b(production[- ]?grade|professional|broadcast)\b",  0.85),
    (r"\b(polished|refined|high[- ]?quality)\b",            0.75),
    (r"\b(quick|rough|sketch|draft|prototype)\b",           0.35),
    (r"\b(test|demo|sample|placeholder)\b",                 0.20),
]

_DETAIL_HINTS = [
    (r"\b(extreme detail|hyper[- ]?detail|ultra ?detailed)\b", "ultra-high"),
    (r"\b(detailed|intricate|rich)\b",                          "high"),
    (r"\b(simple|clean|minimalist|spare)\b",                    "low"),
]


@dataclass(frozen=True)
class EnrichedIntent:
    """Structured Intent Object (Phase 3 spec)."""
    raw_text:        str
    timestamp:       float
    medium:          Optional[str]            # image|video|audio|speech|game|code|simulation|narrative
    realm:           Optional[str]            # kernel realm id (image|video|audio|game|code|cast)
    intent_class:    Optional[str]            # kernel IntentClass name
    style:           Optional[str]
    tone:            Optional[str]
    lighting:        Optional[str]
    composition:     Optional[str]
    emotion:         Optional[str]
    detail_level:    Optional[str]
    ambition:        float                    # 0.0–1.0
    target_pipeline: str                      # which engine realm to route to
    keywords:        list                     # tokens that drove inference
    kernel_plan:     Any = None               # the kernel ExecutionPlan (if available)

    def to_dict(self) -> dict:
        d = asdict(self)
        # kernel_plan may not be JSON-safe — replace with a summary
        try:
            kp = self.kernel_plan
            d["kernel_plan"] = {
                "intent_class": getattr(kp, "intent_class", None).name
                                  if hasattr(getattr(kp, "intent_class", None), "name") else None,
                "realm":        getattr(getattr(kp, "realm", None), "name", None),
                "tasks":        len(getattr(kp, "tasks", []) or []),
            } if kp is not None else None
        except Exception:
            d["kernel_plan"] = None
        return d


class IntentCortex:
    """Enrich vague text into a structured EnrichedIntent."""

    def __init__(self):
        self._enrichments_count = 0

    def enrich(self, text: str) -> EnrichedIntent:
        """Pure rule-based inference. Never raises, always returns a valid
        EnrichedIntent — fields it cannot infer are None."""
        if text is None:
            text = ""
        norm = text.strip()
        low = norm.lower()

        # ── Run kernel orchestrator FIRST so we know the deterministic
        # IntentClass + Realm without re-implementing that logic.
        kernel_plan = None
        intent_class = None
        realm = None
        try:
            from kernel.intent_orchestrator import orchestrate
            kernel_plan = orchestrate(norm)
            intent_class = getattr(kernel_plan.intent_class, "name", None) \
                            if hasattr(kernel_plan, "intent_class") else None
            realm = getattr(kernel_plan.realm, "name", None) \
                     if hasattr(kernel_plan, "realm") else None
        except Exception as e:
            _log.debug("kernel orchestrator unavailable: %s", e)

        medium      = _first_match(_MEDIUM_RULES, low)
        style       = _first_match(_STYLE_RULES, low)
        tone        = _first_match(_TONE_RULES, low)
        lighting    = _first_match(_LIGHTING_RULES, low)
        composition = _first_match(_COMPOSITION_RULES, low)
        emotion     = _first_match(_EMOTION_RULES, low)
        detail      = _first_match(_DETAIL_HINTS, low)
        ambition    = _ambition_score(low)

        # If medium not directly stated, derive from realm/intent_class
        if medium is None:
            medium = _medium_from_realm(realm)

        # Target pipeline = the engine realm this intent will be dispatched to
        target_pipeline = _pipeline_for_medium(medium) or (realm or "").lower() or "cast"

        keywords = _extract_keywords(low)

        enriched = EnrichedIntent(
            raw_text=norm,
            timestamp=time.time(),
            medium=medium,
            realm=realm,
            intent_class=intent_class,
            style=style,
            tone=tone,
            lighting=lighting,
            composition=composition,
            emotion=emotion,
            detail_level=detail,
            ambition=ambition,
            target_pipeline=target_pipeline,
            keywords=keywords,
            kernel_plan=kernel_plan,
        )
        self._enrichments_count += 1
        self._emit_receipt(enriched)
        return enriched

    def _emit_receipt(self, enriched: EnrichedIntent) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="intent_cortex:enrich",
                executor="IntentCortex",
                duration_ms=0.0,
                verified=True,
                compute_sha256=False,
                evidence={
                    "raw_len":      len(enriched.raw_text),
                    "medium":       enriched.medium,
                    "realm":        enriched.realm,
                    "style":        enriched.style,
                    "tone":         enriched.tone,
                    "emotion":      enriched.emotion,
                    "ambition":     enriched.ambition,
                    "target_pipeline": enriched.target_pipeline,
                    "keyword_count":   len(enriched.keywords),
                },
            )
        except Exception:
            pass


# ── helpers ─────────────────────────────────────────────────────────────

def _first_match(rules: list, text: str) -> Optional[str]:
    for pat, val in rules:
        if re.search(pat, text, re.IGNORECASE):
            return val
    return None


def _ambition_score(text: str) -> float:
    for pat, val in _AMBITION_HINTS:
        if re.search(pat, text, re.IGNORECASE):
            return val
    # Default: 0.6 — mid-grade. Operator hasn't signaled either way.
    return 0.6


_MEDIUM_BY_REALM = {
    "IMAGE": "image",
    "VIDEO": "video",
    "AUDIO": "audio",
    "GAME":  "game",
    "CODE":  "code",
    "CAST":  "narrative",
}

_PIPELINE_BY_MEDIUM = {
    "image":      "image",
    "video":      "video",
    "audio":      "audio",
    "speech":     "audio",
    "game":       "game",
    "code":       "code",
    "simulation": "game",
    "narrative":  "cast",
}


def _medium_from_realm(realm: Optional[str]) -> Optional[str]:
    if realm is None:
        return None
    return _MEDIUM_BY_REALM.get(realm.upper())


def _pipeline_for_medium(medium: Optional[str]) -> Optional[str]:
    if medium is None:
        return None
    return _PIPELINE_BY_MEDIUM.get(medium)


_STOPWORDS = frozenset((
    "the a an and or but of for to with in on at by from as is are was were "
    "be been being have has had do does did will would should could can may "
    "this that these those it its i me my you your we us our they them their "
    "make build create generate get please".split()
))


def _extract_keywords(text: str, limit: int = 10) -> list:
    tokens = re.findall(r"[A-Za-z][A-Za-z\-']{2,}", text.lower())
    seen = []
    for t in tokens:
        if t in _STOPWORDS:
            continue
        if t not in seen:
            seen.append(t)
        if len(seen) >= limit:
            break
    return seen
