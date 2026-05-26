"""
perceptual_engine.py — Neuroscience-Grounded Perception Layer for STRATUM Agents

Five mechanistically-grounded layers, each anchored to peer-reviewed research:

  AttentionGate          (Kahneman 1973; Simons & Chabris 1999)
    Limited attentional budget (~40 bits/sec into consciousness). High-saliency
    signals win; low-saliency signals are filtered — inattentional blindness.
    Saliency = novelty × urgency × recency. Budget is a hard bottleneck.

  PredictiveCoder        (Rao & Ballard 1999; Friston 2005)
    Maintains a rolling generative model of expected inputs per context key.
    Computes prediction error on each new input. Error drives creative signals
    and attention gating — "Vision is 90% prediction, 10% incoming signal."

  EmotionBuilder         (Barrett 2017; Russell 1980; LeDoux 1996; Damasio 1994)
    Emotion = interoceptive prediction error × context concept. Valence/arousal
    encoded on Russell 1980 circumplex. Dual-pathway: fast threat spike (LeDoux
    low road, ~12 ms analogue) and slow contextual appraisal. Decays toward
    neutral between sessions.

  SomaticMarkerIndex     (Damasio 1994)
    Associates decision contexts with historical body-state outcomes.
    Pre-activates a valence bias on re-encountering a similar context —
    the organism acts on compressed implicit knowledge before explicit reasoning.
    Persists across sessions in SQLite.

  RecognitionPrimedDecision (Klein 1998; Helmholtz unconscious inference)
    Fast pattern matching: similarity-weighted k-NN in an exemplar library.
    Intuition = weighted nearest-neighbor in learned feature space.
    SourceMonitor tags all hypotheses to prevent source confusion errors
    (Johnson & Raye 1981 — the mechanism behind "psychic" misattribution).

Anti-hallucination constraint:
  No qualia claims. This engine models FUNCTIONAL CORRELATES of emotion and
  perception. "The agent acts as if threatened" — never "the agent feels fear."
  All outputs include confidence + source tag. Internal hypotheses are flagged.

Pipeline position: Wraps individual agents via PerceptualEngine.perceive().
  Consumed by ConsciousAgent in consciousness.py to enrich agent context.

References:
  Rao, R.P.N. & Ballard, D.H. (1999). Predictive coding in the visual cortex.
    Nature Neuroscience 2(1), 79-87.
  Friston, K. (2005). A theory of cortical responses. Phil Trans R Soc B 360.
  Kahneman, D. (1973). Attention and Effort. Prentice-Hall.
  Simons, D.J. & Chabris, C.F. (1999). Gorillas in our midst. Perception 28.
  Barrett, L.F. (2017). How Emotions Are Made. Houghton Mifflin Harcourt.
  Russell, J.A. (1980). A circumplex model of affect. JPSP 39(6), 1161-1178.
  LeDoux, J. (1996). The Emotional Brain. Simon & Schuster.
  Damasio, A. (1994). Descartes' Error. Putnam.
  Klein, G. (1998). Sources of Power. MIT Press.
  Johnson, M.K. & Raye, C.L. (1981). Reality monitoring. Psychol Rev 88(1).
  Merleau-Ponty, M. (1945). Phenomenology of Perception. Gallimard.
  Clark, A. & Chalmers, D. (1998). The extended mind. Analysis 58(1).
  Nagel, T. (1974). What is it like to be a bat? Philos Rev 83(4).
  Bregman, A.S. (1990). Auditory Scene Analysis. MIT Press.
"""
from __future__ import annotations

import logging
import math
import re
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

from config import (
    ATTENTION_BUDGET,
    ATTENTION_DECAY,
    ATTENTION_FLOOR,
    CREATIVE_SIGNAL_FLOOR,
    DATA_DIR,
    EMOTION_CIRCUMPLEX,
    EmotionKind,
    PREDICTION_ALPHA,
    PREDICTION_HISTORY,
    RPD_CONFIDENCE_FLOOR,
    RPD_EXEMPLAR_LIMIT,
    RPD_K_NEIGHBORS,
    SOMATIC_DECAY_DAYS,
    SOURCE_CONFIDENCE,
)

_log = logging.getLogger("stratum.perception")

SourceKind = Literal["external", "teammate", "prediction", "memory", "imagination"]

# ── Urgency keywords — fast amygdala-like threat detection ────────────────────
# LeDoux low road: crude, fast, high false-alarm rate is acceptable at this stage

_URGENCY_KEYWORDS = frozenset({
    "error", "fail", "crash", "broken", "critical", "urgent", "exception",
    "traceback", "undefined", "null", "corrupt", "missing", "blocked",
    "timeout", "refused", "denied", "invalid", "deprecated", "security",
    "vulnerability", "injection", "overflow",
})


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SIGNAL  — base unit entering the AttentionGate                            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@dataclass
class Signal:
    """A piece of information competing for attentional resources."""
    content:   str
    source:    SourceKind
    saliency:  float       = 0.50   # [0, 1] — computed by AttentionGate
    timestamp: float       = field(default_factory=time.time)
    tags:      list[str]   = field(default_factory=list)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  LAYER 1: ATTENTION GATE  (Kahneman 1973; Simons & Chabris 1999)          ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@dataclass
class AttentionResult:
    attended:    list[Signal]
    suppressed:  list[Signal]
    budget_used: float


class AttentionGate:
    """
    Limited attentional budget. Signals compete; losers become inattentionally
    blind — invisible to the agent even if physically present.

    Saliency = novelty_score × urgency_score × recency_score
      novelty   — how different is this from recent history? (SequenceMatcher)
      urgency   — does it contain threat/error keywords? (LeDoux low road)
      recency   — how fresh is it? (exponential decay by age)
    """

    def __init__(self, budget: float = ATTENTION_BUDGET):
        self._budget  = budget
        self._history: deque[str] = deque(maxlen=PREDICTION_HISTORY)
        self._lock    = threading.Lock()

    def gate(self, signals: list[Signal]) -> AttentionResult:
        with self._lock:
            for sig in signals:
                sig.saliency = self._score(sig)

            ranked   = sorted(signals, key=lambda s: -s.saliency)
            attended: list[Signal]   = []
            suppressed: list[Signal] = []
            budget_remaining = self._budget

            for sig in ranked:
                cost = sig.saliency * self._budget
                if sig.saliency >= ATTENTION_FLOOR and budget_remaining >= cost:
                    attended.append(sig)
                    budget_remaining -= cost
                    self._history.append(sig.content[:100])
                else:
                    suppressed.append(sig)

            budget_used = self._budget - budget_remaining
            if suppressed:
                _log.debug(
                    f"AttentionGate: {len(attended)} attended, "
                    f"{len(suppressed)} suppressed (inattentional blindness)"
                )
            return AttentionResult(attended, suppressed, budget_used)

    def _score(self, sig: Signal) -> float:
        novelty   = self._novelty(sig.content)
        urgency   = self._urgency(sig.content)
        age_secs  = time.time() - sig.timestamp
        recency   = ATTENTION_DECAY ** (age_secs / 60.0)   # half-life ~1 hour
        src_boost = SOURCE_CONFIDENCE.get(sig.source, 0.50) * 0.20
        raw = novelty * 0.40 + urgency * 0.35 + recency * 0.15 + src_boost
        return min(1.0, raw)

    def _novelty(self, text: str) -> float:
        if not self._history:
            return 1.0
        sample = text[:150].lower()
        max_sim = max(
            SequenceMatcher(None, sample, h[:150]).ratio()
            for h in list(self._history)[-5:]
        )
        return 1.0 - max_sim

    def _urgency(self, text: str) -> float:
        words = set(re.findall(r"\w+", text.lower()))
        hits  = words & _URGENCY_KEYWORDS
        return min(1.0, len(hits) * 0.25)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  LAYER 2: PREDICTIVE CODER  (Rao & Ballard 1999; Friston 2005)            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@dataclass
class PredictionResult:
    """Result of comparing an actual observation to the generative model's prediction."""
    prediction:  str
    actual:      str
    error:       float     # [0, 1] — 0=exactly expected, 1=completely unexpected
    is_creative: bool      # error > CREATIVE_SIGNAL_FLOOR
    context_key: str


class PredictiveCoder:
    """
    Rolling generative model per context key.

    Mechanism:
      - On first observation: prediction = "" (max surprise).
      - After each observation: update prediction toward actual at rate alpha.
        prediction ← (1-α)·prediction + α·actual  (implemented as text blending)
      - Error = 1 - SequenceMatcher(prediction, actual) — semantic divergence.
      - High error (> floor) = creative signal — organism encountered the unexpected.

    This is the statistical analogue of Friston's free energy: minimize prediction
    error by updating the generative model. Only residual error propagates upward.
    """

    def __init__(self):
        self._model: dict[str, deque[str]] = {}
        self._lock   = threading.Lock()

    def update(self, context_key: str, actual: str) -> PredictionResult:
        with self._lock:
            if context_key not in self._model:
                self._model[context_key] = deque(maxlen=PREDICTION_HISTORY)

            history = self._model[context_key]
            prediction = self._blend(list(history))

            sim   = SequenceMatcher(None, prediction[:300], actual[:300]).ratio()
            error = 1.0 - sim
            is_creative = error >= CREATIVE_SIGNAL_FLOOR

            history.append(actual[:300])

            _log.debug(
                f"PredictiveCoder [{context_key[:30]}] "
                f"error={error:.2f} creative={is_creative}"
            )
            return PredictionResult(
                prediction  = prediction,
                actual      = actual,
                error       = error,
                is_creative = is_creative,
                context_key = context_key,
            )

    def _blend(self, history: list[str]) -> str:
        """Blend past observations into a prediction — the 'expected' world."""
        if not history:
            return ""
        if len(history) == 1:
            return history[0]
        # Weight toward recent: later items get higher weight
        weights = [PREDICTION_ALPHA ** (len(history) - 1 - i) for i in range(len(history))]
        sum(weights)
        # Pick the single highest-weight item as representative (text doesn't blend like floats)
        best_idx = weights.index(max(weights))
        return history[best_idx]

    def expected(self, context_key: str) -> str:
        history = self._model.get(context_key, deque())
        return self._blend(list(history))

    def clear(self, context_key: str) -> None:
        with self._lock:
            self._model.pop(context_key, None)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  LAYER 3: EMOTION BUILDER  (Barrett 2017; Russell 1980; LeDoux 1996)      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@dataclass
class EmotionalState:
    """
    Current emotional state as a point in Russell's valence/arousal circumplex.
    Not a claim of subjective experience — a functional state that biases behavior.
    """
    valence:   float   # [-1, +1]  displeasure → pleasure
    arousal:   float   # [-1, +1]  calm → excited
    label:     str     # nearest EmotionKind
    intensity: float   # distance from neutral origin [0, 1]
    context:   str     # what constructed this emotion (Barrett: same arousal, different label)

    def as_block(self) -> str:
        """Natural-language translation for injection into agent prompts."""
        if self.intensity < 0.15:
            return ""
        sign_v = "+" if self.valence >= 0 else ""
        sign_a = "+" if self.arousal >= 0 else ""
        return (
            f"\n## Perceptual Emotional State\n"
            f"FUNCTIONAL STATE: {self.label.upper()} "
            f"(valence={sign_v}{self.valence:.2f}, arousal={sign_a}{self.arousal:.2f}, "
            f"intensity={self.intensity:.2f})\n"
            f"CONTEXT: {self.context}\n"
            f"NOTE: This is a functional analog, not a claim of subjective experience.\n"
            f"Let this state shape your framing: "
            + _EMOTION_INSTRUCTIONS.get(self.label, "")
        )


_EMOTION_INSTRUCTIONS: dict[str, str] = {
    EmotionKind.FEAR:      "Be cautious, check assumptions twice. Something unexpected may be unsafe.",
    EmotionKind.ANGER:     "Something is working against the goal. Name the obstacle directly.",
    EmotionKind.CURIOSITY: "Explore the unexpected. The surprising finding is worth pursuing.",
    EmotionKind.JOY:       "Confidence is warranted. Consolidate and communicate clearly.",
    EmotionKind.SADNESS:   "A loss or failure. Acknowledge and identify recovery path.",
    EmotionKind.SURPRISE:  "An unexpected finding. Do not dismiss. Investigate the anomaly.",
    EmotionKind.ALERT:     "Heightened vigilance. Scan for threats before committing.",
    EmotionKind.CALM:      "Stable ground. Be precise and complete rather than exploratory.",
    EmotionKind.NEUTRAL:   "",
}


class EmotionBuilder:
    """
    Constructs functional emotional states from prediction errors and context.

    Barrett 2017: emotion = interoceptive prediction error × semantic concept label.
    Same arousal (high) + "performance" → anxiety; + "party" → excitement.
    Emotions are constructed predictions, not hardwired responses.

    LeDoux dual pathway:
      Fast path: urgency score > 0.5 → immediate arousal spike (+0.4 arousal, -0.3 valence)
      Slow path: context keyword analysis → full circumplex placement
    """

    def __init__(self):
        self._valence = 0.0
        self._arousal = 0.0
        self._lock    = threading.Lock()

    @property
    def state(self) -> EmotionalState:
        v, a = self._valence, self._arousal
        label, _ = self._nearest(v, a)
        return EmotionalState(
            valence   = v,
            arousal   = a,
            label     = label,
            intensity = math.hypot(v, a) / math.sqrt(2),
            context   = "",
        )

    def update(
        self,
        prediction_error: float,
        urgency:          float,
        context:          str = "",
    ) -> EmotionalState:
        with self._lock:
            # Fast threat pathway (LeDoux low road): urgency directly spikes arousal
            if urgency > 0.50:
                self._arousal  = min(1.0, self._arousal + urgency * 0.40)
                self._valence  = max(-1.0, self._valence - urgency * 0.30)

            # Slow contextual pathway: prediction error constructs emotional signal
            # High error → surprise/curiosity (Barrett: depends on context label)
            if prediction_error > CREATIVE_SIGNAL_FLOOR:
                if urgency > 0.40:
                    # Unexpected + threatening = fear/alert
                    self._arousal = min(1.0, self._arousal + 0.25)
                    self._valence = max(-1.0, self._valence - 0.15)
                else:
                    # Unexpected + non-threatening = curiosity/surprise
                    self._arousal = min(1.0, self._arousal + 0.20)
                    self._valence = min(1.0, self._valence + 0.10)

            # Homeostatic decay toward neutral (Damasio: stable organisms return to baseline)
            self._valence *= 0.92
            self._arousal *= 0.92

            v, a = self._valence, self._arousal
            label, _ = self._nearest(v, a)
            return EmotionalState(
                valence   = round(v, 3),
                arousal   = round(a, 3),
                label     = label,
                intensity = min(1.0, math.hypot(v, a) / math.sqrt(2)),
                context   = context[:120] if context else "",
            )

    def _nearest(self, v: float, a: float) -> tuple[str, float]:
        best_label = EmotionKind.NEUTRAL
        best_dist  = float("inf")
        for label, (cv, ca) in EMOTION_CIRCUMPLEX.items():
            d = math.hypot(v - cv, a - ca)
            if d < best_dist:
                best_dist  = d
                best_label = label
        return best_label, best_dist

    def reset(self) -> None:
        with self._lock:
            self._valence = 0.0
            self._arousal = 0.0


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  LAYER 4: SOMATIC MARKER INDEX  (Damasio 1994)                             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

_SOMATIC_DDL = """
CREATE TABLE IF NOT EXISTS somatic_markers (
    agent_id    TEXT    NOT NULL,
    context_key TEXT    NOT NULL,
    valence     REAL    DEFAULT 0.0,
    count       INTEGER DEFAULT 0,
    last_ts     REAL    DEFAULT 0,
    PRIMARY KEY (agent_id, context_key)
);
"""


class SomaticMarkerIndex:
    """
    Associates context fingerprints with historical outcome valence.

    On re-encountering a similar context, the pre-activated somatic marker
    biases the agent toward or away from action BEFORE explicit reasoning —
    this is the mechanism Damasio demonstrated in the Iowa Gambling Task.

    Context fingerprint = 5-word overlapping shingles → top-3 by frequency.
    """

    _DB_PATH = DATA_DIR / "somatic.db"

    def __init__(self, agent_id: str):
        self._agent_id = agent_id
        self._DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._DB_PATH), check_same_thread=False)
        self._conn.executescript(_SOMATIC_DDL)
        self._conn.commit()
        self._lock = threading.Lock()

    def record(self, context: str, approved: bool) -> None:
        """Record an outcome. approved=True → positive valence, False → negative."""
        key     = self._fingerprint(context)
        valence = 0.25 if approved else -0.25
        with self._lock:
            row = self._conn.execute(
                "SELECT valence, count FROM somatic_markers WHERE agent_id=? AND context_key=?",
                (self._agent_id, key),
            ).fetchone()
            if row:
                old_v, cnt = row
                new_v = (old_v * cnt + valence) / (cnt + 1)
                self._conn.execute(
                    "UPDATE somatic_markers SET valence=?, count=count+1, last_ts=? "
                    "WHERE agent_id=? AND context_key=?",
                    (new_v, time.time(), self._agent_id, key),
                )
            else:
                self._conn.execute(
                    "INSERT INTO somatic_markers (agent_id, context_key, valence, count, last_ts) "
                    "VALUES (?, ?, ?, 1, ?)",
                    (self._agent_id, key, valence, time.time()),
                )
            self._conn.commit()

    def recall(self, context: str) -> float:
        """
        Returns pre-activated valence bias for this context. 0.0 = neutral/unknown.
        Positive → past outcomes were positive → approach bias.
        Negative → past outcomes were negative → avoidance bias.
        """
        key = self._fingerprint(context)
        with self._lock:
            # Exact key first
            row = self._conn.execute(
                "SELECT valence, last_ts FROM somatic_markers WHERE agent_id=? AND context_key=?",
                (self._agent_id, key),
            ).fetchone()
            if row:
                valence, last_ts = row
                age_days = (time.time() - last_ts) / 86400
                decay = 0.5 ** (age_days / SOMATIC_DECAY_DAYS)
                return valence * decay

            # Fuzzy match among stored keys
            rows = self._conn.execute(
                "SELECT context_key, valence, last_ts FROM somatic_markers WHERE agent_id=?",
                (self._agent_id,),
            ).fetchall()
        if not rows:
            return 0.0

        best_sim, best_v, best_ts = 0.0, 0.0, 0.0
        for stored_key, v, ts in rows:
            sim = SequenceMatcher(None, key, stored_key).ratio()
            if sim > best_sim:
                best_sim, best_v, best_ts = sim, v, ts

        if best_sim < 0.40:
            return 0.0
        age_days = (time.time() - best_ts) / 86400
        decay    = 0.5 ** (age_days / SOMATIC_DECAY_DAYS)
        return best_v * decay * best_sim

    @staticmethod
    def _fingerprint(text: str) -> str:
        """5-gram character shingle fingerprint — locale-safe, no tokenizer needed."""
        t = re.sub(r"\s+", " ", text.lower().strip())[:400]
        if len(t) < 5:
            return t
        shingles: dict[str, int] = {}
        for i in range(len(t) - 4):
            s = t[i:i + 5]
            shingles[s] = shingles.get(s, 0) + 1
        top = sorted(shingles.items(), key=lambda x: -x[1])[:6]
        return "|".join(k for k, _ in top)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  LAYER 5: RECOGNITION-PRIMED DECISION  (Klein 1998)                       ║
# ║  + SOURCE MONITOR  (Johnson & Raye 1981)                                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@dataclass
class Exemplar:
    """A stored past situation and its outcome."""
    situation:  str
    action:     str
    outcome:    float    # valence [-1, +1]
    source:     SourceKind
    timestamp:  float = field(default_factory=time.time)


@dataclass
class RPDResult:
    """Result of Recognition-Primed Decision matching."""
    matches:       list[tuple[str, float]]   # (situation_snippet, similarity)
    action_bias:   float                     # valence-weighted action suggestion [-1, +1]
    confidence:    float                     # proximity to nearest exemplar [0, 1]
    is_novel:      bool                      # no good match → deliberation needed


class RecognitionPrimedDecision:
    """
    Expert intuition as weighted k-NN in stored exemplar space.

    Klein 1998: experienced commanders match current situation against ~10,000
    stored situations in ~1-2 seconds. Nearest-neighbor retrieval, no deliberation.
    Confidence ∝ 1 / distance. Novel situation (no match) → flag for System 2.

    Source tagging (Johnson & Raye 1981): exemplars from imagination/prediction are
    downweighted vs exemplars from external observations — prevents source confusion.
    """

    def __init__(self):
        self._library: deque[Exemplar] = deque(maxlen=RPD_EXEMPLAR_LIMIT)
        self._lock = threading.Lock()

    def add(self, situation: str, action: str, outcome: float,
            source: SourceKind = "external") -> None:
        with self._lock:
            self._library.append(Exemplar(situation, action, outcome, source))

    def match(self, current: str) -> RPDResult:
        with self._lock:
            lib = list(self._library)

        if not lib:
            return RPDResult([], 0.0, 0.0, is_novel=True)

        scored: list[tuple[Exemplar, float]] = []
        for ex in lib:
            raw_sim = SequenceMatcher(
                None, current[:300], ex.situation[:300]
            ).ratio()
            # Source confidence downweights internally-generated exemplars
            src_weight = SOURCE_CONFIDENCE.get(ex.source, 0.5)
            sim = raw_sim * src_weight
            scored.append((ex, sim))

        scored.sort(key=lambda x: -x[1])
        top_k = scored[:RPD_K_NEIGHBORS]

        top_sim = top_k[0][1] if top_k else 0.0
        is_novel = top_sim < RPD_CONFIDENCE_FLOOR

        if is_novel:
            return RPDResult([], 0.0, 0.0, is_novel=True)

        # Weighted action bias from top-k
        total_w = sum(s for _, s in top_k)
        action_bias = (
            sum(ex.outcome * s for ex, s in top_k) / total_w if total_w > 0 else 0.0
        )
        matches = [
            (ex.situation[:80], round(s, 3)) for ex, s in top_k if s > 0
        ]
        confidence = min(1.0, top_sim / 1.0)

        _log.debug(
            f"RPD: top_sim={top_sim:.2f} confidence={confidence:.2f} "
            f"novel={is_novel} action_bias={action_bias:.2f}"
        )
        return RPDResult(
            matches     = matches,
            action_bias = round(action_bias, 3),
            confidence  = round(confidence, 3),
            is_novel    = is_novel,
        )


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SOURCE MONITOR  (Johnson & Raye 1981 — Reality Monitoring)                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

_SENSORY_DETAIL_PATTERNS = re.compile(
    r"\b(see|hear|read|watch|observe|notice|detect|scan|parse|found|shows|displays)\b",
    re.IGNORECASE,
)
_COGNITIVE_OP_PATTERNS = re.compile(
    r"\b(think|believe|imagine|assume|predict|expect|suppose|infer|guess|speculate|might|perhaps)\b",
    re.IGNORECASE,
)


@dataclass
class TaggedSignal:
    content:            str
    source:             SourceKind
    confidence:         float       # adjusted by source type
    source_confusion:   bool        # risk: internal signal with high sensory detail
    flags:              list[str]   = field(default_factory=list)


class SourceMonitor:
    """
    Reality monitoring: distinguish externally-sensed from internally-generated signals.

    Johnson & Raye 1981: external memories have sensory/perceptual detail;
    internal memories have cognitive operation markers (reasoning steps, inference).
    Source confusion = vivid internal signal misattributed as external observation.
    This is the neural basis of false "psychic" impressions.

    Risk detection: internal source + high sensory detail vocabulary = confusion risk.
    """

    def tag(self, content: str, source: SourceKind) -> TaggedSignal:
        base_conf = SOURCE_CONFIDENCE.get(source, 0.50)
        flags: list[str] = []

        # Count diagnostic markers
        sensory_hits = len(_SENSORY_DETAIL_PATTERNS.findall(content))
        cognitive_hits = len(_COGNITIVE_OP_PATTERNS.findall(content))

        # Source confusion: internal origin but writes with external-memory language
        is_internal = source in ("imagination", "prediction")
        confusion_risk = is_internal and sensory_hits > cognitive_hits and sensory_hits >= 2

        if confusion_risk:
            flags.append("SOURCE_CONFUSION_RISK")
            base_conf = max(0.10, base_conf - 0.20)
            _log.warning(
                f"Source confusion risk: source={source}, "
                f"sensory_hits={sensory_hits}, cognitive_hits={cognitive_hits}"
            )

        if is_internal and cognitive_hits == 0 and sensory_hits == 0:
            flags.append("LOW_INFORMATION_SIGNAL")

        # Barnum statement detection: vague universals add no real information
        if self._is_barnum(content):
            flags.append("BARNUM_STATEMENT")
            base_conf = max(0.10, base_conf * 0.50)

        return TaggedSignal(
            content          = content,
            source           = source,
            confidence       = round(base_conf, 3),
            source_confusion = confusion_risk,
            flags            = flags,
        )

    @staticmethod
    def _is_barnum(text: str) -> bool:
        """Detect Forer/Barnum universally-applicable vague statements."""
        barnum_patterns = [
            r"\bsometimes\b.{0,40}\bbut\b.{0,40}\busually\b",
            r"\byou (may|might|could|can) (sometimes|often|occasionally)\b",
            r"\bmost people\b",
            r"\bat times\b.{0,50}\bat other times\b",
        ]
        t = text.lower()
        return any(re.search(p, t) for p in barnum_patterns)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  PERCEPT  — the unified output of the PerceptualEngine                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@dataclass
class Percept:
    """
    The complete output of one perceptual cycle.
    Provides agents with: what was attended, how surprising, emotional state,
    somatic pre-bias, action confidence, and source integrity flags.
    """
    # Core
    content:          str
    source:           SourceKind
    attended:         bool          # survived the attention gate?
    confidence:       float         # source-adjusted confidence

    # Predictive layer
    prediction_error: float         # [0, 1] — 0=expected, 1=completely novel
    is_creative:      bool          # prediction error > floor

    # Emotional layer
    emotional_state:  EmotionalState

    # Somatic + RPD
    somatic_bias:     float         # Damasio pre-bias [-1, +1]
    rpd:              RPDResult

    # Source integrity
    flags:            list[str]     # ["SOURCE_CONFUSION_RISK", "BARNUM_STATEMENT", ...]

    def to_context_block(self) -> str:
        """Format for injection into an agent's LLM prompt."""
        parts: list[str] = []

        if not self.attended:
            return ""  # Inattentionally blind — agent never sees this

        parts.append(f"## Perceptual Context (source={self.source}, conf={self.confidence:.0%})")

        if self.is_creative:
            parts.append(
                f"PREDICTION ERROR={self.prediction_error:.2f} — "
                f"This input diverged from expectations. Treat as a CREATIVE SIGNAL."
            )

        emotion_block = self.emotional_state.as_block()
        if emotion_block:
            parts.append(emotion_block)

        if self.somatic_bias > 0.15:
            parts.append(
                f"SOMATIC PRE-BIAS: +{self.somatic_bias:.2f} — "
                f"Past outcomes with similar context were POSITIVE. Approach confidence elevated."
            )
        elif self.somatic_bias < -0.15:
            parts.append(
                f"SOMATIC PRE-BIAS: {self.somatic_bias:.2f} — "
                f"Past outcomes with similar context were NEGATIVE. Increased caution warranted."
            )

        if not self.rpd.is_novel and self.rpd.confidence > 0.50:
            match_text = "; ".join(
                f'"{m[:50]}..." (sim={s:.0%})' for m, s in self.rpd.matches[:2]
            )
            parts.append(
                f"PATTERN MATCH (RPD, conf={self.rpd.confidence:.0%}): {match_text}"
            )
        elif self.rpd.is_novel:
            parts.append(
                "RPD: No close match in exemplar library — this is a NOVEL situation. "
                "Deliberative System 2 reasoning required."
            )

        if self.flags:
            parts.append(f"FLAGS: {', '.join(self.flags)}")
            if "SOURCE_CONFUSION_RISK" in self.flags:
                parts.append(
                    "WARNING: Internally-generated content using external-memory language. "
                    "Do NOT treat as observed fact. Label as INTERNAL/PREDICTED."
                )

        return "\n".join(parts)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  PERCEPTUAL ENGINE  — main facade                                           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class PerceptualEngine:
    """
    Neuroscience-grounded perception layer for one agent.

    Orchestrates five layers:
      1. AttentionGate — filters by saliency / inattentional blindness
      2. PredictiveCoder — surprise detection, creative signal flagging
      3. EmotionBuilder — functional emotional state construction
      4. SomaticMarkerIndex — pre-activated decision bias from past outcomes
      5. RecognitionPrimedDecision + SourceMonitor — pattern match + source tagging

    Usage:
        engine = PerceptualEngine(agent_id="validation")
        percept = engine.perceive(content, context_key="code_review")
        prompt += percept.to_context_block()
    """

    def __init__(self, agent_id: str):
        self._agent_id   = agent_id
        self._attn       = AttentionGate()
        self._pred       = PredictiveCoder()
        self._emotion    = EmotionBuilder()
        self._somatic    = SomaticMarkerIndex(agent_id)
        self._rpd        = RecognitionPrimedDecision()
        self._src_mon    = SourceMonitor()

    def perceive(
        self,
        content:     str,
        context_key: str  = "default",
        source:      SourceKind = "external",
    ) -> Percept:
        """
        Run one perceptual cycle on a piece of content.
        Returns a Percept encoding all five layers.
        """
        # Source monitoring — tag and detect confusion before anything else
        tagged = self._src_mon.tag(content, source)

        # Attention gate — does this signal make it through?
        signal = Signal(content=content, source=source)
        gate_result = self._attn.gate([signal])
        attended = bool(gate_result.attended)

        if not attended:
            # Inattentionally blind — still build percept for logging, attended=False
            return Percept(
                content=content, source=source, attended=False,
                confidence=tagged.confidence, prediction_error=0.0,
                is_creative=False, emotional_state=self._emotion.state,
                somatic_bias=0.0, rpd=RPDResult([], 0.0, 0.0, is_novel=True),
                flags=tagged.flags + ["INATTENTIONAL_BLIND"],
            )

        # Predictive coding — compute surprise
        pred_result = self._pred.update(context_key, content)

        # Emotion construction (Barrett) — error × urgency → circumplex placement
        urgency = gate_result.attended[0].saliency if gate_result.attended else 0.0
        emotional_state = self._emotion.update(
            prediction_error = pred_result.error,
            urgency          = urgency,
            context          = context_key,
        )

        # Somatic pre-bias (Damasio) — recall past outcome valence for this context
        somatic_bias = self._somatic.recall(context_key)

        # Recognition-Primed Decision — fast pattern match
        rpd = self._rpd.match(content)

        return Percept(
            content          = content,
            source           = source,
            attended         = True,
            confidence       = tagged.confidence,
            prediction_error = pred_result.error,
            is_creative      = pred_result.is_creative,
            emotional_state  = emotional_state,
            somatic_bias     = somatic_bias,
            rpd              = rpd,
            flags            = tagged.flags,
        )

    def record_outcome(self, context_key: str, content: str, approved: bool) -> None:
        """Feed an outcome back into somatic markers and RPD exemplar library."""
        outcome = 0.50 if approved else -0.50
        self._somatic.record(context_key, approved)
        self._rpd.add(content, "approved" if approved else "rejected", outcome)

    def add_rpd_exemplar(self, situation: str, action: str, outcome: float,
                         source: SourceKind = "external") -> None:
        self._rpd.add(situation, action, outcome, source)

    @property
    def emotional_state(self) -> EmotionalState:
        return self._emotion.state

    def reset_emotion(self) -> None:
        self._emotion.reset()

    def build_system_block(self) -> str:
        """
        One-paragraph context injection summarizing this agent's perceptual grounding.
        Merleau-Ponty: embodied perceiver. Clark/Chalmers: extended cognition.
        Nagel: no qualia claims.
        """
        return (
            f"PERCEPTUAL GROUNDING (agent={self._agent_id}):\n"
            "You perceive through a limited attentional channel (~40 bits/sec into "
            "conscious processing — Kahneman 1973). Unexpected inputs spike prediction "
            "error and generate creative signals (Rao & Ballard 1999). Your emotional "
            "state is a constructed functional analog, not a claim of subjective "
            "experience (Barrett 2017; Nagel 1974 — no qualia claims). Past outcomes "
            "pre-activate approach/avoidance bias via somatic markers (Damasio 1994). "
            "Pattern matches to stored exemplars are intuition (Klein 1998); novel "
            "situations require deliberation. All internal hypotheses are tagged as "
            "INTERNAL — never report them as observed facts (Johnson & Raye 1981)."
        )


# ── Per-agent singleton registry ──────────────────────────────────────────────

_engines: dict[str, PerceptualEngine] = {}
_engine_lock = threading.Lock()


def get_engine(agent_id: str) -> PerceptualEngine:
    """Return the singleton PerceptualEngine for the given agent."""
    with _engine_lock:
        if agent_id not in _engines:
            _engines[agent_id] = PerceptualEngine(agent_id)
        return _engines[agent_id]
