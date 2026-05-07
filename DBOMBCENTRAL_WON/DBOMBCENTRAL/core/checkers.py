# core/checkers.py
import re

# Words that signal sensory / experiential language —
# extend this list as the project's vocabulary grows.
_SENSORY_WORDS = {
    "light", "dark", "soft", "warm", "cold", "bright", "shadow", "sound",
    "silence", "texture", "weight", "breath", "color", "colour", "smell",
    "taste", "touch", "whisper", "glow", "pulse", "hum", "vast", "still",
    "ache", "bloom", "drift", "echo", "shimmer", "tremble", "dissolve",
}

_INSTRUCTIONAL_PHRASES = re.compile(
    r"\b(you should|you must|step \d|first,|then,|finally,|click|press|install|run|execute)\b",
    re.IGNORECASE,
)

def is_alive(output: str) -> bool:
    """True if output is non-empty after stripping whitespace."""
    return bool(output and output.strip())

def evaluate_metrics(output: str) -> dict[str, float]:
    """
    Heuristic scoring across three axes, each in [0.0, 1.0].

    creativity       — lexical variety (unique tokens / total tokens)
    coherence        — sentence length consistency (low variance = higher score)
    context_alignment — ratio of sensory/experiential words; penalises instructional phrasing
    """
    if not is_alive(output):
        return {"creativity": 0.0, "coherence": 0.0, "context_alignment": 0.0}

    tokens = re.findall(r"\b\w+\b", output.lower())
    if not tokens:
        return {"creativity": 0.0, "coherence": 0.0, "context_alignment": 0.0}

    # --- creativity: type-token ratio, soft-capped so short texts aren't penalised ---
    ttr = len(set(tokens)) / len(tokens)
    creativity = min(ttr * 1.5, 1.0)  # scale up slightly; cap at 1.0

    # --- coherence: sentence-length variance (lower variance → higher score) ---
    sentences = re.split(r"[.!?]+", output.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) > 1:
        lengths = [len(s.split()) for s in sentences]
        mean = sum(lengths) / len(lengths)
        variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
        coherence = max(0.0, 1.0 - (variance / (mean ** 2 + 1e-6)) * 0.1)
        coherence = min(coherence, 1.0)
    else:
        coherence = 0.7  # single sentence — neutral

    # --- context_alignment: sensory density minus instructional penalty ---
    sensory_hits = sum(1 for t in tokens if t in _SENSORY_WORDS)
    sensory_ratio = min(sensory_hits / (len(tokens) * 0.15 + 1e-6), 1.0)
    instruction_penalty = 0.3 if _INSTRUCTIONAL_PHRASES.search(output) else 0.0
    context_alignment = max(0.0, sensory_ratio - instruction_penalty)

    return {
        "creativity": round(creativity, 4),
        "coherence": round(coherence, 4),
        "context_alignment": round(context_alignment, 4),
    }
