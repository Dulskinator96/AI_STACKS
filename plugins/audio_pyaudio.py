"""
plugins.audio_pyaudio — Local audio playback AudioAdapter shell.

Conforms to GAME_MODE.md "ADAPTER SYSTEM" §AudioAdapter and the dormant
plugin philosophy: importing this module does NOT import pyaudio; the SDK
is soft-imported only at adapter-init time, and absent SDK is degraded to a
slug-passthrough no-op (never raises, never blocks).

Backends supported (best effort, in order):
    pyaudio      — most common low-level binding
    sounddevice  — alternative

If neither is installed, the adapter is in PASSTHROUGH mode: cue() and
ambient() return the underlying simcore_render slugs unchanged, with no
playback side effect.

Public API:
    PyAudioAudioAdapter(backend="auto")
        .cue(event)    -> str       (AudioAdapter Protocol)
        .ambient(world)-> str       (AudioAdapter Protocol)
        .sdk_loaded    -> bool
"""
from __future__ import annotations

import logging
from typing import Any

from simcore import Event, WorldState
from simcore_render import AudioProjector

_log = logging.getLogger(__name__)


class PyAudioAudioAdapter:
    """AudioAdapter that attempts to play sound, falls back to passthrough.

    The SDK soft-import lives in ``__init__``: if it fails, the adapter
    keeps working (in passthrough) without any error, satisfying the
    contract's "Failures must remain contained" rule.
    """

    def __init__(self, backend: str = "auto") -> None:
        self._backend     = (backend or "auto").lower()
        self._projector   = AudioProjector()
        self._sdk: Any    = None
        self._sdk_name    = ""
        self._try_load_sdk()

    @property
    def sdk_loaded(self) -> bool:
        return self._sdk is not None

    @property
    def backend_name(self) -> str:
        return self._sdk_name or "passthrough"

    def _try_load_sdk(self) -> None:
        candidates: tuple[str, ...]
        if self._backend == "pyaudio":
            candidates = ("pyaudio",)
        elif self._backend in ("sounddevice", "sd"):
            candidates = ("sounddevice",)
        else:  # "auto"
            candidates = ("pyaudio", "sounddevice")
        for mod_name in candidates:
            try:
                mod = __import__(mod_name)
            except Exception as exc:
                _log.debug("audio backend %s unavailable: %s", mod_name, exc)
                continue
            self._sdk      = mod
            self._sdk_name = mod_name
            _log.info("audio backend loaded: %s", mod_name)
            return
        _log.info("no audio backend available; running in passthrough mode")

    # ── AudioAdapter Protocol ──────────────────────────────────────────

    def cue(self, event: Event) -> str:
        slug = self._projector.cue_for(event)
        if self.sdk_loaded:
            self._safe_play(slug)
        return slug

    def ambient(self, world: WorldState) -> str:
        return self._projector.ambient_for(world)

    # ── playback (best-effort, isolated) ───────────────────────────────

    def _safe_play(self, slug: str) -> None:
        """Play a slug if a backend can. Silently no-op on any failure."""
        try:
            # ── Windows Physical Playback Completion ──
            import sys
            if sys.platform == "win32":
                import winsound
                # Simple frequency mapping for cues
                freq_map = {
                    "move": 440,
                    "take": 880,
                    "drop": 220,
                    "light": 1760,
                    "unlock": 1320,
                    "error": 110
                }
                freq = freq_map.get(slug, 440)
                winsound.Beep(freq, 150)
            
            _log.debug("audio play (intent only): backend=%s slug=%s",
                       self._sdk_name, slug)
        except Exception as exc:
            _log.warning("audio playback suppressed: %s", exc)
