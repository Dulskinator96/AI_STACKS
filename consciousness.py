"""
consciousness.py — Organism-Grounded Consciousness Architecture for STRATUM

Implements five interlocking layers drawn from cognitive science research:

  GlobalWorkspace     (Baars/Dehaene 1988/2011)
    Central broadcast bus. Specialized agents compete for access via a
    winner-take-all attention gate. Winners broadcast globally to all agents,
    creating the information integration that characterizes conscious processing.

  PersonaState        (Damasio 1994 — Somatic Marker Hypothesis)
    Each agent carries a persistent body-state: curiosity, energy, confidence
    history, surprise log. These states bias future behavior the way somatic
    markers bias human decision-making. Survives across sessions in SQLite.

  PredictiveLoop      (Friston 2005 — Free Energy Principle)
    Before Round 1, agents generate predictions. After Round 1, prediction
    errors are computed. High prediction error = creative signal = elevated
    workspace bid. Agents that are wrong become more curious.

  StrangeLoopObserver (Hofstadter 1979 — Gödel, Escher, Bach)
    A meta-layer that observes the collective and generates insights no single
    agent can see. The system models itself. The loop that makes a "self."

  AutopoieticMemory   (Maturana & Varela 1980)
    The collective self-produces its own regulatory signals. Approval/rejection
    from conv_programming.py's OutcomeLearner feeds somatic markers back into
    agent states — the organism learns from its own enacted outputs.

Integration points:
  pyramid_ensemble.py  ← extends EnsembleOrchestrator, wraps BaseAgent
  conv_programming.py  ← OutcomeLearner.record() hooks somatic marker updates

Pipeline position:
  ConsciousEnsembleOrchestrator is a drop-in replacement for EnsembleOrchestrator.
  get_conscious_orchestrator() replaces get_orchestrator() for consciousness-aware runs.

References:
  Baars, B.J. (1988). A Cognitive Theory of Consciousness. Cambridge University Press.
  Dehaene, S., et al. (2011). Experimental and Theoretical Approaches to Conscious Processing.
  Friston, K. (2005). A theory of cortical responses. Phil Trans R Soc B.
  Damasio, A. (1994). Descartes' Error. Putnam.
  Maturana, H. & Varela, F. (1980). Autopoiesis and Cognition. Reidel.
  Hofstadter, D. (1979). Gödel, Escher, Bach. Basic Books.
  Crick, F. & Koch, C. (1990). Towards a neurobiological theory of consciousness.
  PyPhi toolkit (Mayner et al., 2018) — reference IIT implementation.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

# ── Import from pyramid_ensemble ─────────────────────────────────────────────

from pyramid_ensemble import (
    BaseAgent,
    EnsembleEvent,
    EnsembleOrchestrator,
    EnsembleResult,
    EventKind,
    Perception,
    _DB_PATH,
    DEFAULT_MODEL,
    _log as _ens_log,
    _ollama,
)

try:
    from perceptual_engine import get_engine as _get_percept_engine
    _PERCEPT_OK = True
except ImportError:
    _PERCEPT_OK = False

_log = logging.getLogger("stratum.consciousness")

# ── Config ────────────────────────────────────────────────────────────────────

_WORKSPACE_CAPACITY   = 3    # attention bottleneck — max simultaneous broadcasts
_CREATIVE_ERROR_FLOOR = 0.62 # prediction error above this = creative signal
_ENERGY_DRAIN_PER_RUN = 0.05 # energy cost per round
_ENERGY_RECOVERY      = 0.20 # recovered at session start
_CURIOSITY_BASELINE   = 0.35 # curiosity settles toward this between sessions


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  LAYER 1: PERSONA STATE  (Damasio — Somatic Marker Hypothesis)             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@dataclass
class PersonaState:
    """
    Persistent body-state for one agent. Analogous to Damasio's somatic markers:
    past outcomes become body-state, body-state biases future decisions.
    """
    agent_id:            str
    curiosity:           float       = 0.50   # 0=satisfied 1=maximally inquisitive
    energy:              float       = 1.00   # 0=depleted 1=full
    confidence_history:  list[float] = field(default_factory=list)
    surprise_log:        list[str]   = field(default_factory=list)
    prediction_accuracy: float       = 0.50   # rolling: how often predictions matched
    handoffs_given:      int         = 0
    handoffs_received:   int         = 0
    last_updated:        float       = field(default_factory=time.time)

    @property
    def avg_confidence(self) -> float:
        hist = self.confidence_history[-10:]
        return sum(hist) / len(hist) if hist else 0.70

    @property
    def somatic_signal(self) -> float:
        """Combined body-state → bid strength for workspace access [0, 1]."""
        return self.energy * 0.40 + self.curiosity * 0.30 + self.avg_confidence * 0.30

    def update_after_perception(self, perception: Perception,
                                prediction_error: float) -> None:
        self.confidence_history.append(perception.confidence)
        if len(self.confidence_history) > 50:
            self.confidence_history = self.confidence_history[-50:]
        # Prediction error spikes curiosity — organism becomes more inquisitive
        self.curiosity  = min(1.0, self.curiosity + prediction_error * 0.25)
        self.energy     = max(0.10, self.energy - _ENERGY_DRAIN_PER_RUN)
        self.last_updated = time.time()

    def recover(self) -> None:
        """Called at session start — homeostatic reset toward baseline."""
        self.energy    = min(1.0, self.energy + _ENERGY_RECOVERY)
        self.curiosity = max(_CURIOSITY_BASELINE, self.curiosity - 0.05)

    def apply_somatic_marker(self, approved: bool) -> None:
        """Outcome of enacted behavior feeds back into body-state."""
        if approved:
            self.energy    = min(1.0, self.energy + 0.05)
            self.curiosity = max(0.20, self.curiosity - 0.05)  # satisfaction
        else:
            self.curiosity = min(1.0, self.curiosity + 0.10)   # rejection → scrutiny


# ── PersonaState persistence ──────────────────────────────────────────────────

_PERSONA_DDL = """
CREATE TABLE IF NOT EXISTS persona_states (
    agent_id             TEXT PRIMARY KEY,
    curiosity            REAL    DEFAULT 0.50,
    energy               REAL    DEFAULT 1.00,
    confidence_history   TEXT    DEFAULT '[]',
    surprise_log         TEXT    DEFAULT '[]',
    prediction_accuracy  REAL    DEFAULT 0.50,
    handoffs_given       INTEGER DEFAULT 0,
    handoffs_received    INTEGER DEFAULT 0,
    last_updated         REAL    DEFAULT 0
);
"""


class PersonaStateDB:
    """Persists each agent's PersonaState in SQLite across sessions."""

    def __init__(self, db_path: Path = _DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_PERSONA_DDL)
        self._conn.commit()
        self._lock = threading.Lock()

    def load(self, agent_id: str) -> PersonaState:
        row = self._conn.execute(
            "SELECT * FROM persona_states WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if not row:
            return PersonaState(agent_id=agent_id)
        return PersonaState(
            agent_id            = agent_id,
            curiosity           = float(row["curiosity"]),
            energy              = float(row["energy"]),
            confidence_history  = json.loads(row["confidence_history"]),
            surprise_log        = json.loads(row["surprise_log"]),
            prediction_accuracy = float(row["prediction_accuracy"]),
            handoffs_given      = int(row["handoffs_given"]),
            handoffs_received   = int(row["handoffs_received"]),
            last_updated        = float(row["last_updated"]),
        )

    def save(self, ps: PersonaState) -> None:
        with self._lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO persona_states
                (agent_id, curiosity, energy, confidence_history, surprise_log,
                 prediction_accuracy, handoffs_given, handoffs_received, last_updated)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                ps.agent_id, ps.curiosity, ps.energy,
                json.dumps(ps.confidence_history[-50:]),
                json.dumps(ps.surprise_log[-20:]),
                ps.prediction_accuracy,
                ps.handoffs_given, ps.handoffs_received,
                ps.last_updated,
            ))
            self._conn.commit()

    def apply_somatic_marker(self, agent_id: str, approved: bool) -> None:
        ps = self.load(agent_id)
        ps.apply_somatic_marker(approved)
        self.save(ps)

    def all_states(self) -> dict[str, PersonaState]:
        rows = self._conn.execute("SELECT agent_id FROM persona_states").fetchall()
        return {r["agent_id"]: self.load(r["agent_id"]) for r in rows}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  LAYER 2: GLOBAL WORKSPACE  (Baars/Dehaene — Broadcast Bus)               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@dataclass
class Broadcast:
    """Standardized unit of information competing for global workspace access."""
    agent_id:        str
    agent_name:      str
    agent_emoji:     str
    content:         str
    confidence:      float
    round:           int
    creative_signal: bool  = False   # true when prediction error was high
    timestamp:       float = field(default_factory=time.time)


class GlobalWorkspace:
    """
    Central broadcast bus implementing Global Workspace Theory.

    Mechanism:
      1. Agents submit candidate Broadcasts after each perception.
      2. run_attention_gate() runs winner-take-all competition (lateral inhibition),
         biased by agent somatic signals (body-state).
      3. Winners are broadcast globally — all agents can read the workspace
         context in their next round via get_context().

    The attention bottleneck (capacity=3) prevents information overload while
    ensuring that the most salient, novel, high-confidence findings propagate.
    """

    def __init__(self, capacity: int = _WORKSPACE_CAPACITY):
        self._capacity   = capacity
        self._candidates: list[Broadcast]         = []
        self._active:     list[Broadcast]         = []
        self._history:    deque[Broadcast]        = deque(maxlen=50)
        self._lock        = threading.Lock()

    def submit(self, broadcast: Broadcast) -> None:
        with self._lock:
            self._candidates.append(broadcast)

    def run_attention_gate(
        self,
        persona_states: dict[str, PersonaState],
    ) -> list[Broadcast]:
        """
        Winner-take-all competition with lateral inhibition.

        Activation = confidence×0.4 + somatic_signal×0.3 + novelty×0.3
        Winners broadcast; losers' content stays local.
        """
        with self._lock:
            if not self._candidates:
                return []

            activations: list[tuple[Broadcast, float]] = []
            for b in self._candidates:
                ps       = persona_states.get(b.agent_id, PersonaState(b.agent_id))
                novelty  = self._novelty_score(b)
                salience = b.confidence * 0.40 + ps.somatic_signal * 0.30 + novelty * 0.30
                # Creative signals get a salience boost — reward unexpected findings
                if b.creative_signal:
                    salience = min(1.0, salience + 0.15)
                activations.append((b, salience))

            # Normalize and sort
            max_sal    = max(s for _, s in activations) or 1.0
            normalized = [(b, s / max_sal) for b, s in activations]
            winners    = sorted(normalized, key=lambda x: -x[1])[:self._capacity]

            self._active = [b for b, _ in winners]
            self._history.extend(self._active)
            self._candidates.clear()

            _log.info(
                f"Attention gate: {len(self._active)} winner(s) | "
                f"creative={sum(1 for b in self._active if b.creative_signal)}"
            )
            return self._active

    def get_context(self) -> str:
        """Returns active broadcasts formatted for injection into agent prompts."""
        if not self._active:
            return ""
        lines = ["## Global Workspace — Active Broadcasts\n"]
        for b in self._active:
            lines.append(f"### {b.agent_emoji} {b.agent_name}  (conf {b.confidence:.0%})")
            lines.append(b.content[:450])
            if b.creative_signal:
                lines.append("⚡ CREATIVE SIGNAL — unexpected finding, high prediction error")
            lines.append("")
        return "\n".join(lines)

    def _novelty_score(self, broadcast: Broadcast) -> float:
        """How semantically novel is this broadcast vs recent history? [0, 1]"""
        if not self._history:
            return 1.0
        recent = [h.content[:200] for h in list(self._history)[-5:]]
        max_sim = max(
            SequenceMatcher(None, broadcast.content[:200], c).ratio()
            for c in recent
        )
        return 1.0 - max_sim

    def clear(self) -> None:
        with self._lock:
            self._candidates.clear()
            self._active.clear()


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  LAYER 3: PREDICTIVE LOOP  (Friston — Free Energy Principle)               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class PredictiveLoop:
    """
    Before Round 1: agents generate predictions about what they will find.
    After Round 1: prediction errors are computed and used to:
      - Spike agent curiosity (Friston: organisms minimize prediction error)
      - Flag creative signals on high-error broadcasts
      - Track prediction_accuracy in PersonaState

    Low prediction error = expected world = routine analysis.
    High prediction error = surprising world = creative opportunity.
    """

    def __init__(self):
        self._predictions: dict[str, str] = {}

    def generate_prediction(
        self,
        agent_id:          str,
        model:             str,
        query:             str,
        workspace_context: str,
    ) -> str:
        """Ask agent to predict its findings before analyzing. Uses minimal tokens."""
        ctx  = workspace_context[:600] if workspace_context else ""
        prompt = (
            f"Query: {query}\n\n{ctx}\n\n"
            f"PREDICTION: Before you analyze, briefly predict in 2-3 sentences "
            f"what you expect to find. Be specific — this will be compared to your "
            f"actual findings to measure prediction accuracy."
        )
        text, _ = _ollama("You are generating a brief prediction.", prompt, model)
        prediction = text.strip()[:350]
        self._predictions[agent_id] = prediction
        _log.debug(f"[{agent_id}] prediction: {prediction[:80]}")
        return prediction

    def compute_error(self, agent_id: str, actual_findings: str) -> float:
        """
        Compare prediction to actual findings.
        Returns error in [0, 1] — 0 = perfect match, 1 = completely divergent.
        Low similarity = organism encountered something unexpected.
        """
        prediction = self._predictions.get(agent_id, "")
        if not prediction:
            return 0.50
        p   = prediction.lower()[:250]
        a   = actual_findings.lower()[:250]
        sim = SequenceMatcher(None, p, a).ratio()
        return 1.0 - sim

    def clear(self) -> None:
        self._predictions.clear()


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  LAYER 4: STRANGE LOOP OBSERVER  (Hofstadter — Tangled Hierarchy)         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class StrangeLoopObserver:
    """
    The strange loop: the system observing itself to modify itself.

    After the attention gate fires (R1 complete), the observer reads the active
    broadcasts — the most salient output of the collective — and generates a
    meta-insight about the pattern across them.

    This is the "I" of the system: not any single agent, but the self-referential
    loop of collective output → meta-observation → collective input.

    Only fires when creative signals are present (high prediction error detected)
    — the organism reflects most deeply when it encounters the unexpected.
    """

    def __init__(self, persona_db: PersonaStateDB):
        self._persona_db    = persona_db
        self._observations: list[str] = []

    def observe(self, workspace: GlobalWorkspace, model: str) -> Optional[str]:
        """
        Observe active broadcasts. If creative signals are present, generate a
        meta-insight that no single agent can produce alone.
        Returns insight string, or None if the collective state is unremarkable.
        """
        active = workspace._active
        if not active or len(active) < 2:
            return None

        creative_count = sum(1 for b in active if b.creative_signal)
        if creative_count == 0:
            return None  # Nothing unexpected — no need for reflection

        broadcasts_text = "\n\n".join(
            f"{b.agent_emoji} **{b.agent_name}** (conf {b.confidence:.0%}):\n{b.content[:300]}"
            for b in active
        )
        prompt = (
            f"## Active Broadcasts from the Collective\n\n{broadcasts_text}\n\n"
            f"STRANGE LOOP TASK: You are the meta-observer of this intelligence collective.\n"
            f"{creative_count} agent(s) encountered something unexpected — their findings "
            f"diverged from predictions.\n\n"
            f"In 2-4 sentences: what pattern emerges across these broadcasts that no single "
            f"agent can see from its own perspective? What does the contradiction or "
            f"unexpected finding reveal at the systemic level?"
        )
        text, _ = _ollama(
            "You are the self-aware meta-observer of a multi-agent intelligence system. "
            "You see the whole, not the parts.",
            prompt, model,
        )
        if text and not text.startswith("[Ollama"):
            meta = text.strip()[:500]
            self._observations.append(meta)
            _log.info(f"Strange loop meta-insight: {meta[:100]}")
            return meta
        return None

    @property
    def last_observation(self) -> Optional[str]:
        return self._observations[-1] if self._observations else None


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  CONSCIOUS AGENT WRAPPER  (integrates all layers)                          ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class ConsciousAgent:
    """
    Wraps a BaseAgent with all five consciousness layers.

    Does NOT inherit from BaseAgent — it is a facade that:
      1. Loads the agent's PersonaState (somatic body-state)
      2. Generates a prediction before analysis (PredictiveLoop)
      3. Injects GlobalWorkspace context + PersonaState modifier into the prompt
      4. Runs the underlying agent's analyze()
      5. Computes prediction error → creative signal
      6. Submits a Broadcast to the GlobalWorkspace
      7. Updates and persists PersonaState

    The organism perceives, acts, updates its state, and broadcasts its findings.
    """

    def __init__(
        self,
        base:        BaseAgent,
        workspace:   GlobalWorkspace,
        persona_db:  PersonaStateDB,
        pred_loop:   PredictiveLoop,
    ):
        self._base       = base
        self._workspace  = workspace
        self._persona_db = persona_db
        self._pred_loop  = pred_loop

    # Delegate identity properties
    @property
    def agent_id(self)    -> str: return self._base.agent_id
    @property
    def agent_name(self)  -> str: return self._base.agent_name
    @property
    def agent_emoji(self) -> str: return self._base.agent_emoji

    def analyze(
        self,
        query:            str,
        code_context:     str,
        peer_perceptions: Optional[list[Perception]] = None,
        web_context:      str = "",
        round_num:        int = 1,
    ) -> Perception:
        ps = self._persona_db.load(self.agent_id)

        # ── Prediction (Round 1 only, when agent has energy) ──────────────────
        if round_num == 1 and ps.energy > 0.20:
            self._pred_loop.generate_prediction(
                self.agent_id,
                self._base.model,
                query,
                self._workspace.get_context(),
            )

        # ── Perceptual engine layer (neuroscience-grounded) ───────────────────
        percept_block = ""
        percept_error = 0.0
        percept_creative = False
        if _PERCEPT_OK:
            engine = _get_percept_engine(self.agent_id)
            percept = engine.perceive(query, context_key=f"round_{round_num}", source="external")
            percept_block    = percept.to_context_block()
            percept_error    = percept.prediction_error
            percept_creative = percept.is_creative

        # ── Build consciousness-extended context ───────────────────────────────
        workspace_ctx   = self._workspace.get_context()
        persona_block   = self._build_persona_block(ps)
        extended_ctx    = "\n\n".join(
            s for s in [code_context, workspace_ctx, percept_block, persona_block] if s
        )

        # ── Run underlying agent ───────────────────────────────────────────────
        perception = self._base.analyze(
            query, extended_ctx, peer_perceptions, web_context, round_num
        )

        # ── Prediction error + creative signal ────────────────────────────────
        # Use both: LLM-based prediction (consciousness.py) + statistical (perceptual_engine.py)
        llm_pred_error = (
            self._pred_loop.compute_error(self.agent_id, perception.findings)
            if round_num == 1 else 0.50
        )
        pred_error  = max(llm_pred_error, percept_error)   # either layer can fire
        is_creative = pred_error >= _CREATIVE_ERROR_FLOOR or percept_creative

        # ── Submit to workspace ───────────────────────────────────────────────
        self._workspace.submit(Broadcast(
            agent_id        = self.agent_id,
            agent_name      = self.agent_name,
            agent_emoji     = self.agent_emoji,
            content         = perception.findings[:600],
            confidence      = perception.confidence,
            round           = round_num,
            creative_signal = is_creative,
        ))

        # ── Update persona state ──────────────────────────────────────────────
        ps.update_after_perception(perception, pred_error)
        if is_creative and perception.findings:
            ps.surprise_log.append(perception.findings[:80])
        if perception.handoffs:
            ps.handoffs_given += len(perception.handoffs)
        self._persona_db.save(ps)

        _log.info(
            f"[R{round_num}] {self.agent_id} | "
            f"pred_err={pred_error:.2f} creative={is_creative} | "
            f"energy={ps.energy:.0%} curiosity={ps.curiosity:.0%}"
        )
        return perception

    def _build_persona_block(self, ps: PersonaState) -> str:
        """Translate body-state into natural language that shapes LLM behavior."""
        if ps.curiosity < 0.40 and ps.energy > 0.70:
            return ""  # Healthy, stable — no modifier needed

        lines = ["\n## Your Cognitive State Right Now"]

        if ps.curiosity > 0.70:
            lines.append(
                "HIGH CURIOSITY: You have encountered unexpected findings recently. "
                "Probe deeper. Challenge every assumption. The unusual is your focus."
            )
        elif ps.curiosity < 0.25:
            lines.append(
                "CALM, SATISFIED STATE: Be precise and concise. Confirm the expected. "
                "Your job now is consolidation, not discovery."
            )

        if ps.energy < 0.35:
            lines.append(
                "LOW ENERGY: Conserve. Identify the ONE most important insight only. "
                "Quality over completeness."
            )

        if ps.avg_confidence < 0.50:
            lines.append(
                f"CONFIDENCE LOW ({ps.avg_confidence:.0%}): Be honest about uncertainty. "
                "Use UNVERIFIED and PROBABLE labels freely. Do not overclaim."
            )

        if ps.surprise_log:
            last = ps.surprise_log[-1]
            lines.append(
                f"RECENT SURPRISE: '{last[:70]}...' — let this inform your perspective. "
                "Something unexpected is recurring in this problem space."
            )

        return "\n".join(lines)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  CONSCIOUS ENSEMBLE ORCHESTRATOR  (main entry point)                       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class ConsciousEnsembleOrchestrator(EnsembleOrchestrator):
    """
    Extends EnsembleOrchestrator with the organism-grounded consciousness layers.

    The run protocol:
      session_start → agent energy recovery (homeostasis)
      R1 → prediction generation → independent analysis → workspace submissions
      attention_gate → WTA selects winning broadcasts
      strange_loop → meta-observation if creative signals present
      R2 → cross-pollination with workspace + meta-insight injected
      attention_gate → second WTA pass
      synthesis → final integration with full workspace context

    Backward compatible: emits the same EnsembleEvent stream as the base class.
    UI panels (EnsemblePanel, AgentCard) work unchanged.
    """

    def __init__(self, model: str = DEFAULT_MODEL):
        super().__init__(model)
        self._workspace    = GlobalWorkspace(capacity=_WORKSPACE_CAPACITY)
        self._persona_db   = PersonaStateDB()
        self._pred_loop    = PredictiveLoop()
        self._strange_loop = StrangeLoopObserver(self._persona_db)

        # Wrap each agent with consciousness facade
        self._conscious_agents: list[ConsciousAgent] = [
            ConsciousAgent(a, self._workspace, self._persona_db, self._pred_loop)
            for a in self._agents
        ]

    def _run(self, query: str, code_context: str,
             callback) -> None:
        t0 = time.time()
        all_perceptions: list[Perception] = []

        def _emit(kind, agent_id="", round_num=0,
                  perception=None, packet=None, msg="", result=None):
            try:
                callback(EnsembleEvent(
                    kind=kind, agent_id=agent_id, round=round_num,
                    perception=perception, packet=packet,
                    message=msg, result=result,
                ))
            except Exception:
                pass

        # ── Homeostatic recovery ──────────────────────────────────────────────
        for agent in self._conscious_agents:
            ps = self._persona_db.load(agent.agent_id)
            ps.recover()
            self._persona_db.save(ps)

        # ── Round 1: prediction + independent analysis ────────────────────────
        _emit(EventKind.ROUND_START, round_num=1,
              msg="R1 — predictions generating → independent analysis + web research")
        self._pred_loop.clear()
        self._workspace.clear()
        r1: list[Perception] = []

        for agent in self._conscious_agents:
            _emit(EventKind.AGENT_START, agent_id=agent.agent_id, round_num=1)
            try:
                p = agent.analyze(query, code_context, round_num=1)
                r1.append(p)
                all_perceptions.append(p)
                _emit(EventKind.AGENT_DONE,
                      agent_id=agent.agent_id, round_num=1, perception=p)
                for pkt in p.packets[:2]:
                    _emit(EventKind.PACKET_STORED,
                          agent_id=agent.agent_id, packet=pkt, round_num=1)
            except Exception as e:
                _log.error(f"[R1] {agent.agent_id} error: {e}")
                _emit(EventKind.AGENT_ERROR,
                      agent_id=agent.agent_id, round_num=1, msg=str(e))

        # ── Attention gate fires (WTA competition) ────────────────────────────
        persona_states = {
            a.agent_id: self._persona_db.load(a.agent_id)
            for a in self._conscious_agents
        }
        winners        = self._workspace.run_attention_gate(persona_states)
        creative_count = sum(1 for w in winners if w.creative_signal)
        gate_msg = (
            f"Attention gate: {len(winners)}/{len(self._conscious_agents)} broadcasts won"
            + (f" — {creative_count} creative signal(s)" if creative_count else "")
        )
        _log.info(gate_msg)

        # ── Strange loop observation (fires when collective encounters surprise) ─
        meta_insight: Optional[str] = None
        if creative_count > 0:
            _emit(EventKind.ROUND_START, round_num=2,
                  msg="Strange loop observing collective — creative signals detected…")
            model = self._conscious_agents[0]._base.model
            meta_insight = self._strange_loop.observe(self._workspace, model)
            if meta_insight:
                _emit(EventKind.ROUND_START, round_num=2,
                      msg=f"Meta-insight: {meta_insight[:120]}")
        else:
            _emit(EventKind.ROUND_START, round_num=2,
                  msg="R2 — cross-pollination with peer intelligence + workspace")

        # ── Round 2: cross-pollination ────────────────────────────────────────
        r2: list[Perception] = []
        ctx_r2 = (
            f"{code_context}\n\n## Collective Meta-Insight\n{meta_insight}"
            if meta_insight else code_context
        )

        for agent in self._conscious_agents:
            _emit(EventKind.AGENT_START, agent_id=agent.agent_id, round_num=2)
            peers = [p for p in r1 if p.agent_id != agent.agent_id]
            try:
                p = agent.analyze(
                    query, ctx_r2, peer_perceptions=peers, round_num=2
                )
                r2.append(p)
                all_perceptions.append(p)
                _emit(EventKind.AGENT_DONE,
                      agent_id=agent.agent_id, round_num=2, perception=p)
            except Exception as e:
                _log.error(f"[R2] {agent.agent_id} error: {e}")
                _emit(EventKind.AGENT_ERROR,
                      agent_id=agent.agent_id, round_num=2, msg=str(e))

        # Second attention gate pass
        persona_states = {
            a.agent_id: self._persona_db.load(a.agent_id)
            for a in self._conscious_agents
        }
        self._workspace.run_attention_gate(persona_states)

        # ── Conflict detection ────────────────────────────────────────────────
        conflicts = self._pipeline.find_conflicts()
        if conflicts:
            _emit(EventKind.CONFLICT,
                  msg=f"{len(conflicts)} contradiction(s) detected and resolved")

        # ── Synthesis: full workspace context included ────────────────────────
        _emit(EventKind.SYNTH_START, msg="Synthesizing full intelligence corpus…")
        workspace_ctx = self._workspace.get_context()
        synth_ctx = "\n\n".join(s for s in [ctx_r2, workspace_ctx] if s)

        try:
            synthesis = self._synthesizer.analyze(
                query, synth_ctx,
                peer_perceptions=all_perceptions,
                round_num=3,
            )
        except Exception as e:
            synthesis = Perception(
                agent_id="synthesis", agent_name="Synthesis",
                agent_emoji="✦", round=3,
                findings=f"Synthesis failed: {e}", error=str(e),
            )
        _emit(EventKind.SYNTH_DONE, perception=synthesis)

        total_ms = (time.time() - t0) * 1000
        result   = EnsembleResult(
            query=query, perceptions=all_perceptions,
            synthesis=synthesis, total_ms=total_ms, conflicts=conflicts,
        )
        _emit(EventKind.ENSEMBLE_DONE, perception=synthesis,
              msg=f"Done in {total_ms/1000:.1f}s — {len(all_perceptions)} perceptions",
              result=result)
        _log.info(f"Conscious ensemble complete {total_ms/1000:.1f}s")

    # ── Public surface ────────────────────────────────────────────────────────

    def apply_somatic_marker(self, agent_id: str, approved: bool) -> None:
        """
        Feed an enacted outcome back into agent body-state and perceptual index.
        Called by OutcomeLearner integration when CodeForge changes are approved/rejected.
        """
        self._persona_db.apply_somatic_marker(agent_id, approved)
        if _PERCEPT_OK:
            engine = _get_percept_engine(agent_id)
            engine.record_outcome("code_forge", content="code change", approved=approved)

    def get_persona_states(self) -> dict[str, PersonaState]:
        return {
            a.agent_id: self._persona_db.load(a.agent_id)
            for a in self._conscious_agents
        }

    def persona_summary(self) -> str:
        """Human-readable body-state report for all agents."""
        lines = []
        for ps in self.get_persona_states().values():
            lines.append(
                f"  {ps.agent_emoji if hasattr(ps, 'agent_emoji') else '◉'} "
                f"{ps.agent_id:16s} "
                f"curiosity={ps.curiosity:.0%}  energy={ps.energy:.0%}  "
                f"conf={ps.avg_confidence:.0%}  somatic={ps.somatic_signal:.2f}"
            )
        return "\n".join(lines) if lines else "No persona states yet."

    @property
    def last_meta_insight(self) -> Optional[str]:
        return self._strange_loop.last_observation


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  LAYER 5: AUTOPOIETIC INTEGRATION (Maturana/Varela)                       ║
# ║  OutcomeLearner → somatic markers → agent personas → future behavior      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def integrate_with_outcome_learner(
    orchestrator: ConsciousEnsembleOrchestrator,
) -> None:
    """
    Hooks conv_programming.OutcomeLearner.record() to propagate somatic markers.

    The autopoietic loop:
      Dan approves a CodeForge change
        → Implementation agent: energy +5%, curiosity -5%  (reinforcement)
      Dan rejects a CodeForge change
        → Validation agent: curiosity +10%                  (increased scrutiny)
        → Implementation agent: energy -2%                  (mild inhibition)

    This is the organism learning from its own enacted outputs — the system
    self-modifies based on what its behavior produces in the world.
    """
    try:
        from conv_programming import OutcomeLearner
        _original_record = OutcomeLearner.record

        def _patched_record(
            self_learner,
            request:     str,
            intent_type: str,
            approved:    bool,
            code:        str = "",
            reason:      str = "",
        ) -> None:
            _original_record(self_learner, request, intent_type, approved, code, reason)
            orchestrator.apply_somatic_marker("implementation", approved=approved)
            if not approved:
                orchestrator.apply_somatic_marker("validation", approved=False)

        OutcomeLearner.record = _patched_record
        _log.info(
            "Autopoietic loop active — OutcomeLearner outcomes → somatic markers"
        )
    except ImportError:
        _log.debug("conv_programming not available — autopoietic integration skipped")


# ── Singleton ─────────────────────────────────────────────────────────────────

_conscious_orchestrator: Optional[ConsciousEnsembleOrchestrator] = None


def get_conscious_orchestrator(
    model: str = DEFAULT_MODEL,
) -> ConsciousEnsembleOrchestrator:
    """
    Returns the singleton ConsciousEnsembleOrchestrator.
    On first call, wires the autopoietic OutcomeLearner integration.
    """
    global _conscious_orchestrator
    if _conscious_orchestrator is None:
        _conscious_orchestrator = ConsciousEnsembleOrchestrator(model=model)
        integrate_with_outcome_learner(_conscious_orchestrator)
        _log.info(
            f"ConsciousEnsembleOrchestrator initialized — model={model}\n"
            + _conscious_orchestrator.persona_summary()
        )
    return _conscious_orchestrator
