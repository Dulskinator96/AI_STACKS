# synthesis.py — STRATUM Creative Synthesis Engine
# ──────────────────────────────────────────────────────────────────────────────
# STRATUM generates. Not just text — images, video sequences, audio briefs,
# and styled documents. Every creative output is logged and indexed.
#
# Image generation backends (in priority order):
#   1. Stable Diffusion WebUI API (local, http://localhost:7860)
#   2. Ollama-vision model (describe → generate via VLM)
#   3. PIL generative art (geometric / code-driven — always available)
#
# Video generation:
#   - Frame sequence generation via PIL → FFmpeg encoding
#   - Transition effects, overlays, annotation burns
#
# Audio:
#   - pyttsx3 TTS for voice briefs (local, no API key needed)
#
# Design philosophy: every output is aesthetically considered.
# Colors, typography, composition are treated as first-class concerns.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import sys
import json
import math
import time
import random
import hashlib
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

_HERE    = Path(__file__).resolve().parent
SAVE_DIR = Path.home() / "Documents" / "AI_Monitor"
SYNTH_DIR = SAVE_DIR / "synthesis"
SYNTH_DIR.mkdir(parents=True, exist_ok=True)

# Stable Diffusion WebUI API endpoint
SD_API_BASE  = os.environ.get("SD_API_URL", "http://localhost:7860")
SD_API_TXT2IMG = f"{SD_API_BASE}/sdapi/v1/txt2img"
SD_API_IMG2IMG = f"{SD_API_BASE}/sdapi/v1/img2img"


# ── PIL availability ──────────────────────────────────────────────────────────

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import numpy as np
    NP_OK = True
except ImportError:
    NP_OK = False


# ── Design System ─────────────────────────────────────────────────────────────

DESIGN_PALETTE = {
    "void":     "#0d1117",
    "surface":  "#161b22",
    "border":   "#21262d",
    "accent":   "#58a6ff",
    "accent2":  "#3fb950",
    "accent3":  "#f78166",
    "text":     "#c9d1d9",
    "text_dim": "#8b949e",
    "gold":     "#d4a017",
    "plasma":   "#bc8cff",
}

def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


# ── Stable Diffusion Interface ────────────────────────────────────────────────

class SDClient:
    """Stable Diffusion WebUI API client."""

    NEGATIVE_PROMPT = (
        "blurry, low quality, bad anatomy, watermark, signature, text, "
        "jpeg artifacts, overexposed, underexposed, ugly, distorted"
    )

    @classmethod
    def is_available(cls) -> bool:
        try:
            import requests as _r
            r = _r.get(f"{SD_API_BASE}/sdapi/v1/sd-models", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    @classmethod
    def txt2img(
        cls,
        prompt:   str,
        negative: str = "",
        width:    int = 512,
        height:   int = 512,
        steps:    int = 20,
        cfg:      float = 7.5,
        seed:     int = -1,
    ) -> Optional[Path]:
        """Generate image from text prompt. Returns path to saved PNG."""
        try:
            import requests as _r
            import base64

            payload = {
                "prompt":          prompt,
                "negative_prompt": negative or cls.NEGATIVE_PROMPT,
                "width":           width,
                "height":          height,
                "steps":           steps,
                "cfg_scale":       cfg,
                "seed":            seed,
                "sampler_name":    "Euler a",
            }
            r = _r.post(SD_API_TXT2IMG, json=payload, timeout=120)
            if r.status_code != 200:
                return None

            imgs = r.json().get("images", [])
            if not imgs:
                return None

            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug = hashlib.md5(prompt.encode()).hexdigest()[:6]
            out  = SYNTH_DIR / f"img_{ts}_{slug}.png"

            img_bytes = base64.b64decode(imgs[0])
            out.write_bytes(img_bytes)
            return out
        except Exception:
            return None


# ── PIL Generative Art ────────────────────────────────────────────────────────

class GenerativeArt:
    """
    PIL-based generative art — always available, no API needed.
    Creates aesthetically considered images from text seeds.
    """

    @classmethod
    def create_concept_card(
        cls,
        title:    str,
        content:  str,
        width:    int = 800,
        height:   int = 450,
        theme:    str = "stratum",
    ) -> Optional[Path]:
        """Create a styled concept card image."""
        if not PIL_OK:
            return None

        bg   = _hex_to_rgb(DESIGN_PALETTE["void"])
        acc  = _hex_to_rgb(DESIGN_PALETTE["accent"])
        acc2 = _hex_to_rgb(DESIGN_PALETTE["accent2"])
        txt  = _hex_to_rgb(DESIGN_PALETTE["text"])
        dim  = _hex_to_rgb(DESIGN_PALETTE["text_dim"])

        img  = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(img)

        # Gradient background overlay using diagonal lines
        for i in range(0, width + height, 4):
            alpha = max(0, min(255, int(255 * (1 - i / (width + height)))))
            color = tuple(int(c * alpha / 255) for c in acc)
            draw.line([(i, 0), (0, i)], fill=color, width=1)

        # Header bar
        draw.rectangle([(0, 0), (width, 60)], fill=_hex_to_rgb(DESIGN_PALETTE["surface"]))
        draw.rectangle([(0, 58), (width, 62)], fill=acc)

        # STRATUM badge
        draw.rectangle([(width - 110, 15), (width - 10, 45)], fill=acc)
        try:
            font_title = ImageFont.truetype("consola.ttf", 18)
            font_body  = ImageFont.truetype("consola.ttf", 13)
            font_badge = ImageFont.truetype("consola.ttf", 11)
        except Exception:
            font_title = font_body = font_badge = ImageFont.load_default()

        draw.text((width - 105, 20), "STRATUM", fill=bg, font=font_badge)

        # Title
        draw.text((20, 18), title[:60], fill=txt, font=font_title)

        # Content lines
        words  = content.split()
        lines  = []
        line   = ""
        max_w  = 70
        for w in words:
            if len(line) + len(w) + 1 <= max_w:
                line = (line + " " + w).strip()
            else:
                lines.append(line)
                line = w
        if line:
            lines.append(line)

        y = 80
        for ln in lines[:12]:
            draw.text((20, y), ln, fill=txt, font=font_body)
            y += 22

        # Accent line at bottom
        draw.rectangle([(0, height - 30), (width, height)], fill=_hex_to_rgb(DESIGN_PALETTE["surface"]))
        ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        draw.text((20, height - 22), f"STRATUM · {ts_str}", fill=dim, font=font_badge)

        # Decorative corner element
        for r in range(5, 30, 5):
            draw.arc([(width - 60 + r, height - 60 + r), (width - r, height - r)],
                     0, 360, fill=acc2, width=1)

        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = hashlib.md5(title.encode()).hexdigest()[:6]
        out  = SYNTH_DIR / f"card_{ts}_{slug}.png"
        img.save(str(out), "PNG")
        return out

    @classmethod
    def create_waveform(
        cls,
        data:   list[float],
        label:  str = "Signal",
        width:  int = 900,
        height: int = 300,
    ) -> Optional[Path]:
        """Render a data series as a styled waveform visualization."""
        if not PIL_OK or not data:
            return None

        bg  = _hex_to_rgb(DESIGN_PALETTE["void"])
        acc = _hex_to_rgb(DESIGN_PALETTE["accent"])
        acc2 = _hex_to_rgb(DESIGN_PALETTE["accent2"])
        txt = _hex_to_rgb(DESIGN_PALETTE["text"])

        img  = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(img)

        # Grid lines
        for i in range(0, height, 40):
            draw.line([(0, i), (width, i)], fill=_hex_to_rgb(DESIGN_PALETTE["border"]), width=1)

        # Normalize data to height
        mn, mx = min(data), max(data)
        rng    = mx - mn or 1
        mid    = height // 2
        scale  = (height - 60) / 2

        pts = []
        for i, v in enumerate(data):
            x = int(i / len(data) * width)
            y = int(mid - (v - mn) / rng * scale * 2 + scale)
            pts.append((x, y))

        if len(pts) > 1:
            draw.line(pts, fill=acc, width=2)

            # Fill under the line
            poly = [(pts[0][0], mid)] + pts + [(pts[-1][0], mid)]
            for p in poly:
                x, y = p
                draw.line([(x, y), (x, mid)], fill=(*acc, 40), width=1)

        # Label
        try:
            font = ImageFont.truetype("consola.ttf", 12)
        except Exception:
            font = ImageFont.load_default()
        draw.text((10, 5), label, fill=txt, font=font)
        draw.text((10, height - 20),
                  f"min={mn:.2f} max={mx:.2f} pts={len(data)}", fill=acc2, font=font)

        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = SYNTH_DIR / f"wave_{ts}.png"
        img.save(str(out), "PNG")
        return out

    @classmethod
    def create_neural_map(
        cls,
        nodes:  list[str],
        edges:  list[tuple[int, int]],
        title:  str = "Neural Map",
        width:  int = 800,
        height: int = 600,
    ) -> Optional[Path]:
        """Render a node-edge graph as a styled neural network diagram."""
        if not PIL_OK or not nodes:
            return None

        bg  = _hex_to_rgb(DESIGN_PALETTE["void"])
        acc = _hex_to_rgb(DESIGN_PALETTE["accent"])
        acc2 = _hex_to_rgb(DESIGN_PALETTE["accent2"])
        pla = _hex_to_rgb(DESIGN_PALETTE["plasma"])
        txt = _hex_to_rgb(DESIGN_PALETTE["text"])
        bdr = _hex_to_rgb(DESIGN_PALETTE["border"])

        img  = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(img)

        # Place nodes in a circle
        cx, cy = width // 2, height // 2
        r_place = min(width, height) // 2 - 80
        positions = {}
        n = len(nodes)
        for i, node in enumerate(nodes):
            angle = 2 * math.pi * i / n - math.pi / 2
            x = int(cx + r_place * math.cos(angle))
            y = int(cy + r_place * math.sin(angle))
            positions[i] = (x, y)

        # Draw edges
        for src, dst in edges:
            if src in positions and dst in positions:
                draw.line([positions[src], positions[dst]], fill=bdr, width=1)

        # Draw nodes
        try:
            font = ImageFont.truetype("consola.ttf", 10)
        except Exception:
            font = ImageFont.load_default()

        for i, (x, y) in positions.items():
            draw.ellipse([(x - 18, y - 18), (x + 18, y + 18)], fill=acc, outline=acc2)
            label = nodes[i][:8]
            draw.text((x - len(label) * 3, y - 5), label, fill=bg, font=font)

        # Title
        draw.text((20, 15), title, fill=txt, font=font)

        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = SYNTH_DIR / f"nmap_{ts}.png"
        img.save(str(out), "PNG")
        return out


# ── Video Generation ──────────────────────────────────────────────────────────

class VideoSynth:
    """
    Generate video from frame sequences via FFmpeg.
    PIL generates each frame; FFmpeg encodes to MP4.
    """

    @classmethod
    def ffmpeg_available(cls) -> bool:
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=3)
            return True
        except Exception:
            return False

    @classmethod
    def create_title_sequence(
        cls,
        title:    str,
        subtitle: str = "",
        duration: float = 5.0,
        fps:      int = 24,
        width:    int = 1280,
        height:   int = 720,
    ) -> Optional[Path]:
        """
        Generate a styled title card video sequence.
        Uses PIL frames + FFmpeg encoding.
        """
        if not PIL_OK:
            return None

        frames_dir = SYNTH_DIR / "frames_tmp"
        frames_dir.mkdir(exist_ok=True)

        total_frames = int(duration * fps)
        bg   = _hex_to_rgb(DESIGN_PALETTE["void"])
        acc  = _hex_to_rgb(DESIGN_PALETTE["accent"])
        txt  = _hex_to_rgb(DESIGN_PALETTE["text"])
        dim  = _hex_to_rgb(DESIGN_PALETTE["text_dim"])

        try:
            font_l = ImageFont.truetype("consola.ttf", 48)
            font_m = ImageFont.truetype("consola.ttf", 24)
            font_s = ImageFont.truetype("consola.ttf", 14)
        except Exception:
            font_l = font_m = font_s = ImageFont.load_default()

        for frame_n in range(total_frames):
            t     = frame_n / total_frames  # 0.0 → 1.0
            img   = Image.new("RGB", (width, height), bg)
            draw  = ImageDraw.Draw(img)

            # Animated scan lines
            for y in range(0, height, 6):
                alpha = int(20 + 10 * math.sin(y * 0.1 + t * 10))
                draw.line([(0, y), (width, y)], fill=(*acc[:3], alpha), width=1)

            # Fade in title
            fade = min(1.0, t * 3)
            title_col = tuple(int(c * fade) for c in txt)

            # Center title
            title_x = (width - len(title) * 28) // 2
            title_y = height // 2 - 40
            draw.text((title_x, title_y), title[:30], fill=title_col, font=font_l)

            # Animated underline
            bar_w = int(width * 0.6 * min(1.0, t * 2))
            bar_x = (width - int(width * 0.6)) // 2
            draw.rectangle([(bar_x, title_y + 65), (bar_x + bar_w, title_y + 68)], fill=acc)

            # Subtitle
            if subtitle and t > 0.4:
                sub_fade = min(1.0, (t - 0.4) * 4)
                sub_col  = tuple(int(c * sub_fade) for c in dim)
                sub_x    = (width - len(subtitle) * 14) // 2
                draw.text((sub_x, title_y + 85), subtitle[:60], fill=sub_col, font=font_m)

            # Frame counter (debug strip)
            ts_str = datetime.now().strftime("%H:%M:%S")
            draw.text((10, height - 25), f"STRATUM · {ts_str} · f{frame_n}", fill=dim, font=font_s)

            frame_path = frames_dir / f"frame_{frame_n:05d}.png"
            img.save(str(frame_path), "PNG")

        # Encode with FFmpeg
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = SYNTH_DIR / f"video_{ts}.mp4"

        if cls.ffmpeg_available():
            try:
                subprocess.run([
                    "ffmpeg", "-y",
                    "-framerate", str(fps),
                    "-i", str(frames_dir / "frame_%05d.png"),
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-crf", "18",
                    str(out)
                ], capture_output=True, timeout=120)
                # Cleanup frames
                for f in frames_dir.glob("frame_*.png"):
                    try: f.unlink()
                    except Exception: pass
                if out.exists():
                    return out
            except Exception:
                pass

        # Fallback: return first frame as PNG if FFmpeg unavailable
        first = frames_dir / "frame_00000.png"
        if first.exists():
            out_img = SYNTH_DIR / f"titlecard_{ts}.png"
            first.rename(out_img)
            return out_img
        return None


# ── Audio Synthesis ───────────────────────────────────────────────────────────

class AudioBrief:
    """Text-to-speech briefing via pyttsx3 (local, no API needed)."""

    @classmethod
    def speak(cls, text: str, rate: int = 175, volume: float = 0.9) -> bool:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", rate)
            engine.setProperty("volume", volume)
            engine.say(text)
            engine.runAndWait()
            return True
        except Exception:
            return False

    @classmethod
    def save_wav(cls, text: str, out_path: Path) -> Optional[Path]:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.save_to_file(text, str(out_path))
            engine.runAndWait()
            if out_path.exists():
                return out_path
        except Exception:
            pass
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def generate_image(prompt: str, width: int = 512, height: int = 512) -> Optional[Path]:
    """
    Generate an image from a text prompt.
    Tries SD WebUI first. Returns None if backend unavailable.
    """
    if SDClient.is_available():
        result = SDClient.txt2img(prompt, width=width, height=height)
        if result:
            return result

    return None


def generate_video(title: str, subtitle: str = "", duration: float = 4.0) -> Optional[Path]:
    """Generate a title sequence video."""
    return VideoSynth.create_title_sequence(title, subtitle, duration)


def create_concept_card(title: str, content: str) -> Optional[Path]:
    return GenerativeArt.create_concept_card(title, content)


def create_neural_map(nodes: list, edges: list, title: str = "Architecture") -> Optional[Path]:
    return GenerativeArt.create_neural_map(nodes, edges, title)


def speak_brief(text: str) -> bool:
    return AudioBrief.speak(text)


def status() -> dict:
    return {
        "sd_available":     SDClient.is_available(),
        "pil_available":    PIL_OK,
        "ffmpeg_available": VideoSynth.ffmpeg_available(),
        "synthesis_dir":    str(SYNTH_DIR),
        "files_generated":  len(list(SYNTH_DIR.glob("*.*"))),
    }
