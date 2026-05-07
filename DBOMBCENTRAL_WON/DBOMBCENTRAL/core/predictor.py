# core/predictor.py — WON prediction + suggestion engine
"""
Probability-weighted next-step engine. No ML library required.
Uses TF-IDF-style keyword scoring, ACAS phase mapping, and recency weighting.
"""
from collections import Counter
import re
from datetime import datetime

# ACAS phase keyword maps — each phase has signature concepts
_ACAS_PHASES = {
    1: {
        "keywords": ["memory", "foundation", "architecture", "rag", "retrieval", "knowledge", "graph", "storage"],
        "next_vectors": [
            ("Agent Task Decomposition Engine", "Phase 2 entry point — build the engine that breaks objectives into sub-tasks", 0.87),
            ("Meta-Learning Core Integration", "Layer adaptive learning on top of Phase 1 memory foundation", 0.79),
            ("RAG Pipeline Implementation", "Connect retrieval-augmented generation to the memory system", 0.83),
        ]
    },
    2: {
        "keywords": ["agent", "task", "decomposition", "specialized", "coordination", "deploy"],
        "next_vectors": [
            ("Multi-Agent Coordination Protocol", "Design the communication bus between specialized agents", 0.85),
            ("Performance Optimization Module", "Build the feedback loop that refines agent efficiency", 0.78),
            ("Neuro-Symbolic Hybrid Layer", "Begin Phase 3 by layering symbolic logic onto neural outputs", 0.72),
        ]
    },
    3: {
        "keywords": ["integration", "optimize", "communication", "protocol", "conflict", "hybrid"],
        "next_vectors": [
            ("AR 25-50 Compliance Engine", "Phase 4 entry — military-standard documentation auto-generation", 0.88),
            ("System-Wide Benchmark Suite", "Measure efficiency, coherence, and task completion across all agents", 0.81),
            ("Causal Inference Framework", "Upgrade reasoning from correlation to causation", 0.76),
        ]
    },
    4: {
        "keywords": ["compliance", "deployment", "audit", "regulatory", "transparency", "ar 25"],
        "next_vectors": [
            ("Multi-Billion Ideation Engine", "Activate market analysis and innovation synthesis capabilities", 0.84),
            ("Cross-Jurisdictional Regulatory Adapter", "Extend compliance beyond AR 25-50 to EU AI Act / NIST", 0.79),
            ("ACAS v2 Architecture Design", "Begin next-generation architecture informed by Phase 1–4 learnings", 0.91),
        ]
    },
}

_DEFAULT_VECTORS = [
    ("Memory Compression Pass", "Cluster and compress episodic memory for efficiency", 0.71),
    ("Obsidian Knowledge Graph Expansion", "Link all project notes with semantic backlinks", 0.68),
    ("WON Self-Evaluation Loop", "Build the feedback mechanism that scores WON's own outputs", 0.74),
]


class Predictor:
    def suggest(self, memory, tracker, count: int = 3) -> list[dict]:
        """
        Score next-step vectors using:
        1. Current ACAS phase from tracker
        2. Keyword frequency in recent memory
        3. Recency weighting (newer entries score higher)
        Returns top `count` suggestions sorted by probability.
        """
        recent = memory.recall(limit=30)
        phase  = tracker.current_phase()
        keyword_scores = self._score_keywords(recent)

        # Base vectors from current phase
        phase_data = _ACAS_PHASES.get(phase, _ACAS_PHASES[1])
        vectors = list(phase_data["next_vectors"])

        # Adjust probabilities by keyword match
        adjusted = []
        for concept, rationale, base_prob in vectors:
            boost = self._keyword_boost(concept + " " + rationale, keyword_scores)
            adjusted.append({
                "concept":     concept,
                "rationale":   rationale,
                "probability": min(round(base_prob + boost, 2), 0.98),
                "phase":       phase + 1 if phase < 4 else 4,
            })

        # Fill remaining slots from default vectors if needed
        if len(adjusted) < count:
            for concept, rationale, base_prob in _DEFAULT_VECTORS:
                adjusted.append({"concept": concept, "rationale": rationale,
                                  "probability": base_prob, "phase": phase})

        adjusted.sort(key=lambda x: x["probability"], reverse=True)
        return adjusted[:count]

    def _score_keywords(self, entries: list[dict]) -> Counter:
        counts: Counter = Counter()
        now = datetime.utcnow().timestamp()
        for i, e in enumerate(entries):
            weight = 1 + (i / max(len(entries), 1))  # recency boost
            words  = re.findall(r'\b[a-z]{4,}\b', (e.get("content","") or "").lower())
            for w in words:
                counts[w] += weight
        return counts

    def _keyword_boost(self, text: str, scores: Counter) -> float:
        words = re.findall(r'\b[a-z]{4,}\b', text.lower())
        if not words:
            return 0.0
        total = sum(scores.get(w, 0) for w in words)
        return min(total / (len(words) * 10), 0.10)  # cap boost at +0.10
