"""realms/audio_engine/pipeline.py — REAL audio generation.

Backends:
  · pyttsx3        — local TTS (speech path). Writes real .wav.
  · Bark           — neural TTS if installed.
  · audiocraft     — MusicGen for soundtracks if installed.
  · procedural     — numpy-based ambient synthesis (always available
                      when numpy is). Real synthesis, not fake.

Capabilities:
  · narration / voiceover  → pyttsx3 → Bark fallback
  · soundtrack / ambient   → audiocraft → procedural fallback

Reality Enforcement: every backend probe is real. Procedural ambient is
NOT fake — it's actual additive synthesis (sine + triangle + noise mix).
"""
from __future__ import annotations

import io
import logging
import math
import struct
import time
import wave
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


def run(kind: str, params: dict) -> dict:
    """kind: 'narration' | 'soundtrack' | 'ambient' | 'voiceover'.
    Returns: {outcome, artifacts, backend, error, ...}.
    """
    intent = params.get("intent_text", "")
    spec   = params.get("spec")
    psess  = params.get("session")
    track_index = int(params.get("track_index", 0))

    if psess is None:
        return {"outcome": "FAIL", "error": "missing session", "artifacts": []}

    out_dir = Path(psess.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if kind in ("narration", "voiceover"):
        return _route_speech(intent, spec, psess, out_dir)
    # soundtrack / ambient
    return _route_soundtrack(intent, spec, psess, out_dir, track_index)


# ── Speech path ────────────────────────────────────────────────────────
def _route_speech(intent: str, spec, psess, out_dir: Path) -> dict:
    # 1. Bark
    r = _try_bark(intent, out_dir, psess)
    if r["outcome"] == "OK":
        return r
    # 2. pyttsx3
    return _try_pyttsx3(intent, out_dir, psess)


def _try_bark(intent: str, out_dir: Path, psess) -> dict:
    try:
        from bark import generate_audio, SAMPLE_RATE   # type: ignore
    except ImportError:
        return {"outcome": "UNAVAILABLE", "error": "Bark not installed",
                "artifacts": [], "backend": "bark"}
    try:
        import numpy as np
        audio_array = generate_audio(intent[:200])
        out_path = out_dir / f"bark_{int(time.time()*1000)}.wav"
        # Bark returns float32 -1..1; write as 16-bit PCM
        a = (audio_array * 32767).clip(-32768, 32767).astype(np.int16)
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(SAMPLE_RATE))
            w.writeframes(a.tobytes())
        _register(psess, out_path, "bark")
        return {"outcome": "OK", "artifacts": [str(out_path)],
                "backend": "bark"}
    except Exception as e:
        return {"outcome": "FAIL", "error": str(e),
                "artifacts": [], "backend": "bark"}


def _try_pyttsx3(intent: str, out_dir: Path, psess) -> dict:
    try:
        import pyttsx3
    except ImportError:
        return {"outcome": "UNAVAILABLE", "error": "pyttsx3 not installed",
                "remediation": "pip install pyttsx3",
                "artifacts": [], "backend": "pyttsx3"}
    try:
        eng = pyttsx3.init()
        out_path = out_dir / f"pyttsx3_{int(time.time()*1000)}.wav"
        # pyttsx3 save_to_file is the supported persistence path
        eng.save_to_file(intent[:400], str(out_path))
        eng.runAndWait()
        if not out_path.is_file() or out_path.stat().st_size == 0:
            return {"outcome": "FAIL",
                    "error": "pyttsx3 produced no file",
                    "artifacts": [], "backend": "pyttsx3"}
        _register(psess, out_path, "pyttsx3")
        return {"outcome": "OK", "artifacts": [str(out_path)],
                "backend": "pyttsx3"}
    except Exception as e:
        return {"outcome": "FAIL", "error": str(e),
                "artifacts": [], "backend": "pyttsx3"}


# ── Soundtrack path ────────────────────────────────────────────────────
def _route_soundtrack(intent: str, spec, psess, out_dir: Path,
                       track_index: int) -> dict:
    # 1. audiocraft
    r = _try_audiocraft(intent, spec, out_dir, psess, track_index)
    if r["outcome"] == "OK":
        return r
    # 2. procedural ambient (numpy)
    return _try_procedural(intent, spec, out_dir, psess, track_index)


def _try_audiocraft(intent: str, spec, out_dir: Path, psess, track_index: int) -> dict:
    try:
        from audiocraft.models import MusicGen   # type: ignore
    except ImportError:
        return {"outcome": "UNAVAILABLE", "error": "audiocraft not installed",
                "artifacts": [], "backend": "audiocraft"}
    try:
        import torchaudio   # type: ignore
        model = MusicGen.get_pretrained("small")
        model.set_generation_params(duration=12)
        prompt = _build_soundtrack_prompt(intent, spec)
        wav = model.generate([prompt])
        out_path = out_dir / f"audiocraft_{int(time.time()*1000)}_{track_index:02d}.wav"
        torchaudio.save(str(out_path), wav[0].cpu(), model.sample_rate)
        _register(psess, out_path, "audiocraft")
        return {"outcome": "OK", "artifacts": [str(out_path)],
                "backend": "audiocraft", "prompt": prompt}
    except Exception as e:
        return {"outcome": "FAIL", "error": str(e),
                "artifacts": [], "backend": "audiocraft"}


def _try_procedural(intent: str, spec, out_dir: Path, psess, track_index: int) -> dict:
    """Real additive synthesis — not fake. Produces a .wav with a
    sustained pad + slow beat + textural noise. Profile chosen by
    tone/style if present."""
    try:
        try:
            import numpy as np
        except ImportError:
            return {"outcome": "UNAVAILABLE", "error": "numpy not available",
                    "artifacts": [], "backend": "procedural_audio"}

        sample_rate = 44100
        duration_s = 12.0
        n_samples = int(sample_rate * duration_s)
        t = np.linspace(0, duration_s, n_samples, endpoint=False)

        # Style → tonal centre + texture
        style = (getattr(spec, "style", "") or "").lower()
        tone  = (getattr(spec, "tone",  "") or "").lower()

        # Root frequency by tone
        if tone in ("legendary", "epic", "triumph"):
            root = 220.0   # A3
        elif tone in ("dark", "intense", "horror", "fear"):
            root = 110.0   # A2
        elif tone in ("serene", "melancholic", "longing"):
            root = 174.61  # F3
        else:
            root = 196.0   # G3

        # Pad: root + fifth + minor third or major third
        is_minor = tone in ("dark", "melancholic", "horror", "fear",
                              "mysterious", "eerie", "longing")
        third = root * (6/5 if is_minor else 5/4)
        fifth = root * 3/2
        oct_   = root * 2

        # Slow LFO on amplitude
        lfo = 0.5 + 0.5 * np.sin(2 * np.pi * 0.25 * t)
        pad = (
            0.40 * np.sin(2 * np.pi * root * t) +
            0.32 * np.sin(2 * np.pi * third * t) +
            0.30 * np.sin(2 * np.pi * fifth * t) +
            0.18 * np.sin(2 * np.pi * oct_ * t)
        ) * lfo

        # Texture: filtered noise
        rng = np.random.default_rng(int(time.time()) ^ track_index)
        noise = rng.standard_normal(n_samples).astype(np.float32)
        # simple low-pass via running mean (real signal processing)
        kernel = max(8, int(sample_rate / 1500))
        noise = np.convolve(noise, np.ones(kernel) / kernel, mode="same") * 0.12

        # Slow heartbeat at ~60 bpm for cinematic ambitions
        is_cinematic = "cinematic" in style or "epic" in tone or "legendary" in tone
        beat = np.zeros(n_samples)
        if is_cinematic:
            beat_freq = 60.0 / 60.0  # 1 Hz
            for i in range(int(duration_s * beat_freq) + 1):
                center = int(i / beat_freq * sample_rate)
                if center >= n_samples:
                    break
                # Decaying low pulse
                length = min(sample_rate // 4, n_samples - center)
                env = np.exp(-np.linspace(0, 5, length))
                tone_pulse = 0.35 * env * np.sin(2 * np.pi * 55 * np.linspace(0, length/sample_rate, length))
                beat[center:center + length] += tone_pulse

        signal = pad + noise + beat
        # Normalize, fade in/out
        peak = float(np.max(np.abs(signal)))
        if peak > 0:
            signal = signal * (0.7 / peak)
        fade = int(sample_rate * 1.5)
        signal[:fade]  *= np.linspace(0, 1, fade)
        signal[-fade:] *= np.linspace(1, 0, fade)

        # Write 16-bit PCM
        out_path = out_dir / f"procedural_{int(time.time()*1000)}_{track_index:02d}.wav"
        a = (signal * 32767).clip(-32768, 32767).astype(np.int16)
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(a.tobytes())
        _register(psess, out_path, "procedural_audio")

        return {"outcome": "OK", "artifacts": [str(out_path)],
                "backend": "procedural_audio",
                "duration_s": duration_s,
                "root_hz": root, "minor": is_minor, "cinematic": is_cinematic}
    except Exception as e:
        return {"outcome": "FAIL", "error": str(e),
                "artifacts": [], "backend": "procedural_audio"}


def _build_soundtrack_prompt(intent: str, spec) -> str:
    parts = [intent or "cinematic theme"]
    if spec is not None:
        if getattr(spec, "soundtrack_profile", None):
            parts.append(spec.soundtrack_profile)
        if getattr(spec, "tone", None):
            parts.append(spec.tone)
        if getattr(spec, "emotion", None):
            parts.append(spec.emotion)
    return ", ".join(p for p in parts if p)


def _register(psess, path: Path, backend: str) -> None:
    try:
        from engine.production_core import get_production_core
        get_production_core().register_artifact(psess, str(path), backend)
    except Exception:
        pass
