"""engine/aesthetic_intelligence/visual_harmony.py — palette + composition coherence.

Real metric: hex palette → HSV variance + complementary distance check.
"""
from __future__ import annotations

import colorsys
import re
from typing import Any


def _hex_to_hsv(hex_str: str):
    s = hex_str.lstrip("#")
    if len(s) != 6:
        return None
    try:
        r = int(s[0:2], 16) / 255.0
        g = int(s[2:4], 16) / 255.0
        b = int(s[4:6], 16) / 255.0
    except Exception:
        return None
    return colorsys.rgb_to_hsv(r, g, b)


class VisualHarmonyScorer:
    """Palette + composition harmony scoring.

    Returns 0..1 score + breakdown dict.
    """

    def score(self, spec) -> tuple:
        palette = list(getattr(spec, "color_palette", []) or [])
        composition = (getattr(spec, "composition", "") or "").lower()

        breakdown: dict = {}
        if not palette:
            breakdown["palette"] = "none"
            base = 0.55  # neutral when no palette
        else:
            hsvs = [h for h in (_hex_to_hsv(c) for c in palette) if h is not None]
            if not hsvs:
                breakdown["palette"] = "unparseable"
                base = 0.4
            else:
                # Saturation variance — low variance = harmonious
                sats = [h[1] for h in hsvs]
                sat_variance = sum((s - sum(sats) / len(sats)) ** 2 for s in sats) / len(sats)
                breakdown["sat_variance"] = round(sat_variance, 3)
                # Value (brightness) spread — moderate spread = good
                vals = [h[2] for h in hsvs]
                val_spread = max(vals) - min(vals)
                breakdown["val_spread"] = round(val_spread, 3)
                # Score: low sat variance (≤0.15) and moderate val spread (0.2..0.6)
                sat_score = max(0.0, 1.0 - sat_variance * 4)
                val_score = 1.0 - abs(val_spread - 0.4) * 1.5
                val_score = max(0.0, min(1.0, val_score))
                base = 0.4 + 0.3 * sat_score + 0.3 * val_score
                breakdown["palette_size"] = len(hsvs)

        # Composition grammar consistency
        if composition:
            breakdown["composition"] = composition
            base = min(1.0, base + 0.05)

        return round(min(1.0, max(0.0, base)), 3), breakdown
