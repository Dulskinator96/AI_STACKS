# core/biases.py
from __future__ import annotations

_DEFAULTS = {
    "sensory": 1.0,
    "compression": 1.0,
    "description_only": 1.0,
    "awe": 1.0,
}

class BiasEngine:
    """
    Encapsulates bias weights. Prefer this over the raw TENDENCIES dict.
    Accepts an optional seed from settings.yaml bias_weights to override defaults.
    """

    def __init__(self, seed: dict | None = None):
        self._weights: dict[str, float] = {**_DEFAULTS, **(seed or {})}

    def adjust(self, name: str, delta: float) -> None:
        """Shift a bias by delta, clamped to [0.0, 2.0]."""
        if name not in self._weights:
            raise KeyError(f"Unknown bias '{name}'. Valid keys: {list(self._weights)}")
        self._weights[name] = max(0.0, min(2.0, self._weights[name] + delta))

    def get(self, name: str) -> float:
        return self._weights[name]

    def snapshot(self) -> dict[str, float]:
        """Return a copy of current weights (safe for logging)."""
        return dict(self._weights)

    def reset(self) -> None:
        self._weights = dict(_DEFAULTS)
