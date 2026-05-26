"""engine/visual_harmony_pixel.py — BUILD-028 REAL pixel analysis.

Replaces the text-semantic spec-only visual harmony from build-027a
with actual PIL/numpy image analysis. Required for image + video realms
per directive Section 5.

Measures (all real, from pixel data):
  · histogram_balance     — entropy of luminance histogram
  · contrast_spread        — std-dev of luminance
  · brightness_hierarchy   — separation between bright and dark regions
  · edge_density           — fraction of pixels above edge-gradient threshold
  · silhouette_readability — central-mass concentration
  · color_harmony          — HSV variance against the spec's palette
  · cinematic_framing      — rule-of-thirds focal placement
  · entropy_distribution   — variance of local entropy across tiles
  · visual_noise_ratio     — high-frequency content fraction

Writes `visual_analysis.json` next to the artifact when invoked.
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VisualAnalysis:
    artifact_path:           str
    width:                   int
    height:                  int
    histogram_balance:       float
    contrast_spread:         float
    brightness_hierarchy:    float
    edge_density:            float
    silhouette_readability:  float
    color_harmony:           float
    cinematic_framing:       float
    entropy_distribution:    float
    visual_noise_ratio:      float
    pixel_score:             float       # weighted composite 0..1
    analyzed_at:             float

    def to_dict(self) -> dict:
        return asdict(self)


class VisualHarmonyPixel:
    """Real pixel analysis. Returns a VisualAnalysis or None if PIL/numpy
    unavailable or the file can't be decoded."""

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.visual_harmony_pixel", self)
        except Exception:
            pass

    def analyze(self, artifact_path: str,
                spec_palette: Optional[list] = None) -> Optional[VisualAnalysis]:
        try:
            from PIL import Image    # type: ignore
            import numpy as np
        except ImportError:
            _log.debug("PIL/numpy unavailable — pixel analysis skipped")
            return None
        p = Path(artifact_path)
        if not p.is_file():
            return None
        try:
            with Image.open(str(p)) as raw:
                img = raw.convert("RGB")
                w, h = img.size
                # Downscale to bounded size for analysis speed
                if max(w, h) > 768:
                    scale = 768 / max(w, h)
                    img = img.resize((int(w * scale), int(h * scale)))
                arr = np.asarray(img, dtype=np.float32)
        except Exception as e:
            _log.debug("image decode failed: %s", e)
            return None

        # Luminance (Rec.709)
        lum = (arr[:, :, 0] * 0.2126 +
               arr[:, :, 1] * 0.7152 +
               arr[:, :, 2] * 0.0722)
        lum_norm = lum / 255.0

        # 1. Histogram balance — entropy of 32-bin luminance histogram
        hist, _ = np.histogram(lum, bins=32, range=(0, 255))
        probs = hist / max(1, hist.sum())
        probs = probs[probs > 0]
        ent = float(-(probs * np.log2(probs)).sum()) if len(probs) > 0 else 0.0
        histogram_balance = min(1.0, ent / 5.0)   # ~5 bits = high diversity

        # 2. Contrast spread — std-dev of luminance
        contrast_spread = float(min(1.0, lum_norm.std() / 0.35))

        # 3. Brightness hierarchy — separation between top + bottom percentiles
        p90 = float(np.percentile(lum_norm, 90))
        p10 = float(np.percentile(lum_norm, 10))
        brightness_hierarchy = min(1.0, (p90 - p10) / 0.8)

        # 4. Edge density — Sobel-style gradient
        gy = np.abs(np.diff(lum, axis=0)).mean()
        gx = np.abs(np.diff(lum, axis=1)).mean()
        edge_strength = (gx + gy) / 2.0
        edge_density = float(min(1.0, edge_strength / 30.0))

        # 5. Silhouette readability — central-mass concentration vs uniform spread
        H, W = lum_norm.shape
        cy, cx = H / 2, W / 2
        # weighted moment: how concentrated is the brightness around the center
        ys, xs = np.indices(lum_norm.shape)
        center_mask = ((ys - cy) ** 2 + (xs - cx) ** 2) < (min(H, W) * 0.30) ** 2
        center_lum = lum_norm[center_mask].mean() if center_mask.any() else lum_norm.mean()
        outer_lum = lum_norm[~center_mask].mean() if (~center_mask).any() else lum_norm.mean()
        silhouette_readability = float(min(1.0, abs(center_lum - outer_lum) * 2.5))

        # 6. Color harmony — HSV saturation variance + alignment with spec palette
        # Convert RGB to HSV
        rgb_norm = arr / 255.0
        mx = rgb_norm.max(axis=2)
        mn = rgb_norm.min(axis=2)
        diff = mx - mn
        s = np.where(mx > 0, diff / np.maximum(mx, 1e-6), 0)
        sat_variance = float(s.std())
        color_harmony_base = float(1.0 - min(1.0, sat_variance * 3))
        # Alignment with spec palette: average distance of mean color to palette colors
        palette_score = 0.5
        if spec_palette:
            palette_rgb = []
            for hex_s in spec_palette:
                try:
                    hex_s = hex_s.lstrip("#")
                    if len(hex_s) == 6:
                        palette_rgb.append([int(hex_s[i:i+2], 16) / 255.0
                                              for i in (0, 2, 4)])
                except Exception:
                    continue
            if palette_rgb:
                mean_rgb = rgb_norm.mean(axis=(0, 1))
                dists = [
                    float(np.sqrt(((mean_rgb - np.asarray(c)) ** 2).sum()))
                    for c in palette_rgb
                ]
                min_dist = min(dists)
                palette_score = float(max(0.0, 1.0 - min_dist))
        color_harmony = round((0.6 * color_harmony_base + 0.4 * palette_score), 3)

        # 7. Cinematic framing — focal mass at rule-of-thirds intersections
        thirds_y = [H // 3, 2 * H // 3]
        thirds_x = [W // 3, 2 * W // 3]
        thirds_mass = 0.0
        radius = min(H, W) // 8
        # Use luminance gradient magnitude as a proxy for "focal interest"
        gradmag = np.zeros_like(lum)
        gradmag[1:, :] += np.abs(np.diff(lum, axis=0))
        gradmag[:, 1:] += np.abs(np.diff(lum, axis=1))
        total_grad = float(gradmag.sum()) + 1.0
        for y in thirds_y:
            for x in thirds_x:
                y0, y1 = max(0, y - radius), min(H, y + radius)
                x0, x1 = max(0, x - radius), min(W, x + radius)
                thirds_mass += float(gradmag[y0:y1, x0:x1].sum())
        cinematic_framing = float(min(1.0, (thirds_mass / total_grad) * 2.0))

        # 8. Entropy distribution — variance of per-tile entropy across 4x4 grid
        tile_h = H // 4
        tile_w = W // 4
        tile_entropies = []
        for ti in range(4):
            for tj in range(4):
                y0 = ti * tile_h
                x0 = tj * tile_w
                tile = lum[y0:y0 + tile_h, x0:x0 + tile_w]
                if tile.size == 0:
                    continue
                th, _ = np.histogram(tile, bins=16, range=(0, 255))
                tp = th / max(1, th.sum())
                tp = tp[tp > 0]
                te = float(-(tp * np.log2(tp)).sum()) if len(tp) > 0 else 0.0
                tile_entropies.append(te)
        if tile_entropies:
            ent_var = float(np.std(tile_entropies))
            # Good cinematic image has moderate variance (some flat regions
            # + some busy regions): ideal around 0.4..0.8
            if 0.3 <= ent_var <= 0.9:
                entropy_distribution = 0.85
            elif ent_var < 0.2:
                entropy_distribution = 0.5    # too uniform
            else:
                entropy_distribution = 0.65   # too chaotic
        else:
            entropy_distribution = 0.5

        # 9. Visual noise ratio — high-frequency content
        # Use small-window variance as a noise proxy
        win = 3
        if H > win and W > win:
            shifted = lum[win:-win, win:-win]
            v_diff = np.abs(lum[win+1:-win+1, win:-win] - shifted) + \
                     np.abs(lum[win:-win, win+1:-win+1] - shifted)
            noise = float(v_diff.mean() / 255.0)
            # Low noise = good; threshold at 0.15
            visual_noise_ratio = float(max(0.0, 1.0 - noise * 4.0))
        else:
            visual_noise_ratio = 0.5

        # Weighted composite (per directive: visual harmony as a real measure)
        pixel_score = (
            0.15 * histogram_balance +
            0.12 * contrast_spread +
            0.10 * brightness_hierarchy +
            0.10 * edge_density +
            0.10 * silhouette_readability +
            0.15 * color_harmony +
            0.13 * cinematic_framing +
            0.08 * entropy_distribution +
            0.07 * visual_noise_ratio
        )
        pixel_score = round(max(0.0, min(1.0, pixel_score)), 3)

        analysis = VisualAnalysis(
            artifact_path=str(p),
            width=int(arr.shape[1]),
            height=int(arr.shape[0]),
            histogram_balance=round(histogram_balance, 3),
            contrast_spread=round(contrast_spread, 3),
            brightness_hierarchy=round(brightness_hierarchy, 3),
            edge_density=round(edge_density, 3),
            silhouette_readability=round(silhouette_readability, 3),
            color_harmony=color_harmony,
            cinematic_framing=round(cinematic_framing, 3),
            entropy_distribution=round(entropy_distribution, 3),
            visual_noise_ratio=round(visual_noise_ratio, 3),
            pixel_score=pixel_score,
            analyzed_at=time.time(),
        )
        # Persist sidecar next to artifact
        try:
            sidecar = p.parent / f"{p.stem}.visual_analysis.json"
            sidecar.write_text(json.dumps(analysis.to_dict(), indent=2),
                                encoding="utf-8")
        except Exception:
            pass
        self._emit_receipt(analysis)
        return analysis

    def _emit_receipt(self, a: VisualAnalysis) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="visual_harmony_pixel:analyzed",
                executor="VisualHarmonyPixel",
                artifact=a.artifact_path,
                duration_ms=0.0, verified=True, compute_sha256=False,
                evidence={
                    "pixel_score":       a.pixel_score,
                    "histogram_balance": a.histogram_balance,
                    "contrast_spread":   a.contrast_spread,
                    "edge_density":      a.edge_density,
                    "color_harmony":     a.color_harmony,
                    "cinematic_framing": a.cinematic_framing,
                    "width": a.width, "height": a.height,
                },
            )
        except Exception:
            pass


_INSTANCE: Optional[VisualHarmonyPixel] = None


def get_visual_harmony_pixel() -> VisualHarmonyPixel:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = VisualHarmonyPixel()
    return _INSTANCE
