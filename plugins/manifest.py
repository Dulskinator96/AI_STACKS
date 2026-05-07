"""
plugins.manifest — Standard dormant plugin manifest set.

Declarations only. No third-party SDKs, no network calls, no plugin code.
Importing this module is safe on a stock Python install.
"""
from __future__ import annotations

from plugins import PluginManifest


STANDARD_MANIFESTS: tuple[PluginManifest, ...] = (
    PluginManifest(
        name="obsidian",
        description="Obsidian vault sync — markdown + frontmatter ingest.",
        required_config=("vault_path",),
    ),
    PluginManifest(
        name="external_ai",
        description="External AI APIs (e.g. OpenAI, Anthropic). "
                    "STRATUM is offline-first; this is purely opt-in.",
        required_config=("api_key", "provider"),
    ),
    PluginManifest(
        name="unreal",
        description="Unreal Engine bridge — scene + asset interchange.",
        required_config=("project_path",),
    ),
    PluginManifest(
        name="davinci",
        description="DaVinci Resolve integration — scripting bridge.",
        required_config=("scripting_path",),
    ),
    PluginManifest(
        name="dolphin",
        description="Dolphin Emulator bridge — sandboxed subprocess for "
                    "GameCube / Wii ISOs. Frames captured via shared memory; "
                    "input routed via InputAdapter.",
        required_config=("dolphin_exe", "iso_path"),
    ),
    PluginManifest(
        name="audio_playback",
        description="Local audio playback adapter (pyaudio / sounddevice). "
                    "Soft-imports the SDK on activation; falls back to slug "
                    "passthrough when SDK is unavailable.",
        required_config=("backend",),
    ),
)
