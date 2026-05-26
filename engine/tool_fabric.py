"""engine/tool_fabric.py — BUILD-020 SECTION 12: TOOL FABRIC.

Unified external tool discovery + status.

Tools tracked (probe-first, never faked):
  · Unreal Engine        — installation detection
  · Blender              — CLI presence
  · DaVinci Resolve      — installation detection
  · ComfyUI              — local server probe (127.0.0.1:8188)
  · Automatic1111        — local server probe (127.0.0.1:7860)
  · Ollama               — daemon probe via config.OLLAMA_URL
  · LM Studio            — daemon probe via config.LM_STUDIO_URL
  · FFmpeg               — binary on PATH
  · Git                  — binary on PATH
  · pyttsx3              — Python import
  · imageforge           — Python import
  · simcore              — Python import
  · audiocraft           — Python import (optional)
  · pyramid_ensemble     — internal module
  · conv_programming     — internal module

Statuses: READY | DEGRADED | UNAVAILABLE | FAILED. Each carries a
remediation string.

The fabric maintains a cache that refreshes every 30s on a daemon
thread. Synchronous status() calls are O(1) dict lookups.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


# Canonical local backend install root (BUILD-031 ffmpeg/godot integration).
# Probes look here first so backends installed under AI_STACK\backends are
# detected without requiring a PATH change. Works in dev and frozen.
_BACKENDS_FALLBACK = Path(r"C:\Users\dulsk\Desktop\AIBuild\AI_STACK\backends")


def _backend_roots() -> list:
    """Every plausible `…\\backends` dir. Walks ancestors of the module (dev)
    or the exe (frozen) so AI_STACK\\backends is found whether the exe runs
    from build\\release or the project root, plus an absolute fallback."""
    roots: list = []
    try:
        anchor = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
        for p in anchor.parents:
            roots.append(p / "backends")
    except Exception:
        pass
    roots.append(_BACKENDS_FALLBACK)
    return roots


def _backend_candidates(*parts: str):
    """Yield candidate absolute paths `<root>/<*parts>` across all backend roots."""
    seen = set()
    for r in _backend_roots():
        c = str(r.joinpath(*parts))
        if c not in seen:
            seen.add(c)
            yield c


def _telemetry_dir() -> Path:
    """Persistent telemetry dir next to the .exe (frozen) or project root
    (dev). NEVER _MEIPASS. Mirrors engine/mem_palace/memory_store.py."""
    try:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            base = Path(__file__).resolve().parent.parent
        d = base / "telemetry"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return Path.home() / ".stratum" / "telemetry"


def _tool_version(path: Optional[str], flag: str) -> Optional[str]:
    """Best-effort version string (first line). Telemetry-only; never raises,
    short timeout, returns None on any failure. Not a pipeline path."""
    if not path or not os.path.isfile(path):
        return None
    try:
        r = subprocess.run([path, flag], capture_output=True, text=True, timeout=8)
        lines = (r.stdout or r.stderr or "").strip().splitlines()
        return lines[0][:120] if lines else None
    except Exception:
        return None


@dataclass(frozen=True)
class ToolStatus:
    name:        str
    status:      str          # READY | DEGRADED | UNAVAILABLE | FAILED
    realm:       str          # primary realm this tool supports
    version:     Optional[str] = None
    path:        Optional[str] = None
    remediation: str = ""
    detail:      str = ""
    last_probed: float = 0.0


# ── Per-tool probes ────────────────────────────────────────────────────

def _probe_unreal() -> ToolStatus:
    candidates = [
        r"C:\Program Files\Epic Games\UE_5.4\Engine\Binaries\Win64\UnrealEditor.exe",
        r"C:\Program Files\Epic Games\UE_5.3\Engine\Binaries\Win64\UnrealEditor.exe",
        r"C:\Program Files\Epic Games\UE_5.2\Engine\Binaries\Win64\UnrealEditor.exe",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return ToolStatus(name="unreal", status="READY", realm="game",
                              path=p, last_probed=time.time())
    return ToolStatus(name="unreal", status="UNAVAILABLE", realm="game",
                      remediation="Install Unreal Engine from Epic Games Launcher",
                      last_probed=time.time())


def _probe_blender() -> ToolStatus:
    p = shutil.which("blender")
    if p:
        return ToolStatus(name="blender", status="READY", realm="game",
                          path=p, last_probed=time.time())
    for cand in (r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
                  r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe"):
        if os.path.isfile(cand):
            return ToolStatus(name="blender", status="READY", realm="game",
                              path=cand, last_probed=time.time())
    return ToolStatus(name="blender", status="UNAVAILABLE", realm="game",
                      remediation="Install Blender from blender.org or add to PATH",
                      last_probed=time.time())


def _probe_davinci() -> ToolStatus:
    for p in (r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe",
               r"C:\Program Files\Blackmagic Design\DaVinci Resolve Studio\Resolve.exe"):
        if os.path.isfile(p):
            return ToolStatus(name="davinci_resolve", status="READY", realm="video",
                              path=p, last_probed=time.time())
    return ToolStatus(name="davinci_resolve", status="UNAVAILABLE", realm="video",
                      remediation="Install DaVinci Resolve (free or Studio)",
                      last_probed=time.time())


def _probe_comfyui() -> ToolStatus:
    return _probe_http("comfyui", "image",
                        "http://127.0.0.1:8188",
                        "Start ComfyUI: cd ComfyUI && python main.py")


def _probe_a1111() -> ToolStatus:
    return _probe_http("automatic1111", "image",
                        "http://127.0.0.1:7860",
                        "Start A1111: webui-user.bat or webui.sh")


def _probe_ollama() -> ToolStatus:
    try:
        from config import OLLAMA_URL
    except Exception:
        OLLAMA_URL = "http://127.0.0.1:11434"
    return _probe_http("ollama", "llm",
                        OLLAMA_URL.rstrip("/") + "/api/tags",
                        "Start Ollama: `ollama serve` or run Ollama.app")


def _probe_lm_studio() -> ToolStatus:
    try:
        from config import LM_STUDIO_URL
    except Exception:
        LM_STUDIO_URL = "http://127.0.0.1:1234"
    return _probe_http("lm_studio", "llm",
                        LM_STUDIO_URL.rstrip("/") + "/v1/models",
                        "Start LM Studio local server (Developer → Start Server)")


def _probe_http(name: str, realm: str, url: str, remediation: str) -> ToolStatus:
    try:
        import requests
        r = requests.get(url, timeout=1.5)
        if r.status_code in (200, 404):    # 404 is fine — server responded
            return ToolStatus(name=name, status="READY", realm=realm,
                              path=url, last_probed=time.time(),
                              detail=f"HTTP {r.status_code}")
        return ToolStatus(name=name, status="DEGRADED", realm=realm,
                          remediation=remediation,
                          detail=f"HTTP {r.status_code}", last_probed=time.time())
    except Exception as e:
        return ToolStatus(name=name, status="UNAVAILABLE", realm=realm,
                          remediation=remediation,
                          detail=str(e)[:80], last_probed=time.time())


def _probe_ffmpeg() -> ToolStatus:
    p = shutil.which("ffmpeg")
    if not p:
        for cand in _backend_candidates("ffmpeg", "bin", "ffmpeg.exe"):
            if os.path.isfile(cand):
                p = cand
                break
    if p:
        return ToolStatus(name="ffmpeg", status="READY", realm="video",
                          path=p, last_probed=time.time())
    return ToolStatus(name="ffmpeg", status="UNAVAILABLE", realm="video",
                      remediation=r"Install ffmpeg into AI_STACK\backends\ffmpeg\bin or add to PATH",
                      last_probed=time.time())


def _probe_godot() -> ToolStatus:
    p = shutil.which("godot")
    if not p:
        # Prefer the console variant (attaches stdout) when present.
        for r in _backend_roots():
            gdir = r / "godot"
            if gdir.is_dir():
                exes = sorted(gdir.glob("Godot*.exe"),
                              key=lambda x: (0 if "console" in x.name.lower() else 1, x.name))
                if exes:
                    p = str(exes[0])
                    break
    if p:
        return ToolStatus(name="godot", status="READY", realm="game",
                          path=p, last_probed=time.time())
    return ToolStatus(name="godot", status="UNAVAILABLE", realm="game",
                      remediation=r"Install Godot 4.x into AI_STACK\backends\godot or add to PATH",
                      last_probed=time.time())


def _probe_git() -> ToolStatus:
    p = shutil.which("git")
    if p:
        return ToolStatus(name="git", status="READY", realm="code",
                          path=p, last_probed=time.time())
    return ToolStatus(name="git", status="UNAVAILABLE", realm="code",
                      remediation="Install Git from git-scm.com",
                      last_probed=time.time())


def _probe_pymod(modname: str, realm: str, remediation: str) -> ToolStatus:
    try:
        __import__(modname)
        return ToolStatus(name=modname, status="READY", realm=realm,
                          last_probed=time.time())
    except ImportError:
        return ToolStatus(name=modname, status="UNAVAILABLE", realm=realm,
                          remediation=remediation, last_probed=time.time())
    except Exception as e:
        return ToolStatus(name=modname, status="FAILED", realm=realm,
                          remediation=remediation, detail=str(e)[:80],
                          last_probed=time.time())


_PROBES: dict[str, callable] = {
    "unreal":          _probe_unreal,
    "blender":         _probe_blender,
    "davinci_resolve": _probe_davinci,
    "comfyui":         _probe_comfyui,
    "automatic1111":   _probe_a1111,
    "ollama":          _probe_ollama,
    "lm_studio":       _probe_lm_studio,
    "ffmpeg":          _probe_ffmpeg,
    "godot":           _probe_godot,
    "git":             _probe_git,
    "pyttsx3":         lambda: _probe_pymod("pyttsx3", "audio", "pip install pyttsx3"),
    "imageforge":      lambda: _probe_pymod("imageforge", "image", "ensure imageforge bundled"),
    "simcore":         lambda: _probe_pymod("simcore", "game", "ensure simcore bundled"),
    "audiocraft":      lambda: _probe_pymod("audiocraft", "audio", "pip install audiocraft (≥1GB)"),
    "pyramid_ensemble": lambda: _probe_pymod("pyramid_ensemble", "cast", "ensure pyramid_ensemble bundled"),
    "conv_programming": lambda: _probe_pymod("conv_programming", "code", "ensure conv_programming bundled"),
}

# Per-realm relevance map
_REALM_TOOLS: dict[str, list] = {
    "image":      ["comfyui", "automatic1111", "imageforge"],
    "video":      ["davinci_resolve", "ffmpeg", "imageforge"],
    "audio":      ["pyttsx3", "audiocraft"],
    "game":       ["godot", "unreal", "blender", "simcore"],
    "code":       ["git", "conv_programming"],
    "simulation": ["simcore"],
    "cast":       ["ollama", "lm_studio", "pyramid_ensemble"],
    "llm":        ["ollama", "lm_studio"],
}


class ToolFabric:
    """Unified external tool discovery layer."""

    def __init__(self, refresh_interval_s: float = 30.0):
        self._cache: dict[str, ToolStatus] = {}
        self._lock = threading.RLock()
        self._refresh_interval = float(refresh_interval_s)
        self._refresher_started = False
        self._refresh_count = 0
        # Initial probe set runs eagerly on a worker
        self._refresh_async()

    def _refresh_async(self) -> None:
        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
            DeferredWorkspaceLoader.run(self._refresh_all, on_done=None,
                                         name="tool_fabric_refresh")
        except Exception:
            threading.Thread(target=self._refresh_all, daemon=True,
                              name="tool_fabric_refresh_fallback").start()

    def _refresh_all(self) -> None:
        new_cache: dict[str, ToolStatus] = {}
        for name, probe in _PROBES.items():
            try:
                new_cache[name] = probe()
            except Exception as e:
                new_cache[name] = ToolStatus(
                    name=name, status="FAILED", realm="",
                    remediation="audit probe", detail=str(e)[:80],
                    last_probed=time.time(),
                )
        with self._lock:
            self._cache = new_cache
            self._refresh_count += 1
        self._emit_receipt(new_cache)
        self._write_backend_scan(new_cache)   # P1: frozen backend truth snapshot

        # Schedule next refresh
        if not self._refresher_started:
            self._refresher_started = True
            t = threading.Thread(target=self._refresher_loop, daemon=True,
                                  name="ToolFabricRefresher")
            t.start()

    def _write_backend_scan(self, cache: dict) -> None:
        """P1 / CTES v2 — DUAL-LAYER backend truth snapshot, written every
        refresh (and thus every boot) so frozen-runtime backend presence is
        observable on disk.

        LAYER A — internal_state (STRICT reality, never normalized/overwritten):
          RESOLVED          executable resolved + file exists on disk
          PARTIAL           present but degraded / partial capability
          FAILED_EXECUTION  probe raised / executed but failed
          UNRESOLVED        not found / unavailable
        LAYER B — external_state (normalized DISPLAY layer only):
          RESOLVED->PRESENT · PARTIAL->LIMITED · UNRESOLVED/FAILED_EXECUTION->DEFERRED

        Internal truth is ALWAYS preserved and logged; the external layer is a
        perception layer for UI/logs only and never shows raw failure terms.
        Decision layers (WorkerRouter.gate / BackendRegistry.executable_verified)
        keep reading the strict ToolStatus (READY/UNAVAILABLE) — NOT external_state
        — so absence is never masked where it matters. Best-effort; never raises;
        does not alter detection logic, MemPalace, or worker pipelines.
        """
        try:
            _EXT = {"RESOLVED": "PRESENT", "PARTIAL": "LIMITED",
                    "UNRESOLVED": "DEFERRED", "FAILED_EXECUTION": "DEFERRED"}

            def entry(name: str, flag: str, capability: list) -> dict:
                st = cache.get(name)
                raw = getattr(st, "status", None) if st else None
                path = getattr(st, "path", None) if st else None
                exists = bool(path and os.path.isfile(path))
                if raw == "READY" and exists:
                    internal = "RESOLVED"
                elif raw == "DEGRADED":
                    internal = "PARTIAL"
                elif raw == "FAILED":
                    internal = "FAILED_EXECUTION"
                else:                       # UNAVAILABLE, READY-but-file-gone, None
                    internal = "UNRESOLVED"
                resolved = internal == "RESOLVED"
                return {
                    "internal_state": internal,
                    "external_state": _EXT.get(internal, "DEFERRED"),
                    "path": path if internal in ("RESOLVED", "PARTIAL") else None,
                    "version": _tool_version(path, flag) if resolved else None,
                    "capability": capability,
                }
            snap = {
                "timestamp": int(time.time()),
                "scan_mode": "FROZEN_RUNTIME" if getattr(sys, "frozen", False) else "DEV_RUNTIME",
                "source": "tool_fabric._refresh_all",
                "ffmpeg": entry("ffmpeg", "-version",
                                ["audio_encode", "video_encode", "normalize"]),
                "godot":  entry("godot", "--version",
                                ["engine_runtime", "headless_export"]),
            }
            (_telemetry_dir() / "backend_scan.json").write_text(
                json.dumps(snap, indent=2), encoding="utf-8")
        except Exception:
            pass   # observability is best-effort; must never break the scan

    def _refresher_loop(self) -> None:
        while True:
            try:
                time.sleep(self._refresh_interval)
                self._refresh_all()
            except Exception:
                pass

    # ── Public API ────────────────────────────────────────────────────
    def status(self, tool_name: str) -> str:
        with self._lock:
            t = self._cache.get(tool_name)
            return t.status if t is not None else "UNAVAILABLE"

    def detail(self, tool_name: str) -> Optional[ToolStatus]:
        with self._lock:
            return self._cache.get(tool_name)

    def tools_for_realm(self, realm: str) -> list:
        return list(_REALM_TOOLS.get((realm or "").lower(), []))

    def ready_tools(self) -> list:
        with self._lock:
            return [t.name for t in self._cache.values() if t.status == "READY"]

    def snapshot(self) -> dict:
        with self._lock:
            return {
                name: {
                    "status":      t.status, "realm": t.realm,
                    "version":     t.version, "path": t.path,
                    "remediation": t.remediation, "detail": t.detail,
                    "last_probed": t.last_probed,
                }
                for name, t in self._cache.items()
            }

    def force_refresh(self) -> None:
        self._refresh_async()

    # BUILD-023 — hard dependency gate. Returns a structured decision
    # used by WorkerRouter to enforce "no fabrication": if no backend
    # is available for the realm, dispatch is denied with remediation.
    def gate(self, realm: str) -> dict:
        """Return {allowed: bool, fallback_realm: str|None,
        ready_backends: [...], missing_backends: [...], remediation: str}."""
        realm = (realm or "").lower()
        tools = self.tools_for_realm(realm)
        ready: list[str] = []
        missing: list[str] = []
        with self._lock:
            for t in tools:
                e = self._cache.get(t)
                if e is None:
                    missing.append(t)
                    continue
                if e.status in ("READY", "DEGRADED"):
                    ready.append(t)
                else:
                    missing.append(t)
        # Audio + cast + code + sim + game realms have internal fallbacks
        if realm in ("audio", "cast", "code", "simulation", "game"):
            return {
                "allowed": True,
                "fallback_realm": None,
                "ready_backends": ready, "missing_backends": missing,
                "remediation": "" if ready else
                    "no listed external backend ready; internal fallback engages",
            }
        # Image + video require external backends
        remediation = ""
        if realm == "image":
            remediation = ("start ComfyUI (port 8188) OR Automatic1111 "
                            "(port 7860) OR install diffusers + a SD model")
        elif realm == "video":
            remediation = "install ffmpeg and add to PATH"
        return {
            "allowed": bool(ready),
            "fallback_realm": None,
            "ready_backends": ready,
            "missing_backends": missing,
            "remediation": remediation,
        }

    def _emit_receipt(self, cache: dict) -> None:
        try:
            from truth.receipt_engine import record_execution
            counts = {"READY": 0, "DEGRADED": 0, "UNAVAILABLE": 0, "FAILED": 0}
            for t in cache.values():
                counts[t.status] = counts.get(t.status, 0) + 1
            record_execution(
                task="tool_fabric:refresh",
                executor="ToolFabric",
                duration_ms=0.0,
                verified=True,
                compute_sha256=False,
                evidence={
                    "refresh_count": self._refresh_count,
                    "tool_count":    len(cache),
                    "counts":        counts,
                    "ready_list":    [t.name for t in cache.values() if t.status == "READY"],
                },
            )
        except Exception:
            pass


_FABRIC_INSTANCE: Optional[ToolFabric] = None


def get_tool_fabric() -> ToolFabric:
    global _FABRIC_INSTANCE
    if _FABRIC_INSTANCE is None:
        _FABRIC_INSTANCE = ToolFabric()
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.tool_fabric", _FABRIC_INSTANCE)
        except Exception:
            pass
    return _FABRIC_INSTANCE


def scan_now() -> dict:
    """Synchronous one-shot backend scan that GUARANTEES telemetry/backend_scan.json
    on every boot — independent of the async refresher.

    The eager `_refresh_async` schedule (via DeferredWorkspaceLoader) was observed
    NOT to complete inside the frozen-runtime boot window, so backend_scan.json was
    never written in the EXE (dev↔frozen drift). This is the deterministic boot-path
    write: probe ffmpeg+godot (cheap local resolution + version), merge into the
    fabric cache so status() agrees, and write the CTES v2 dual-state snapshot.
    Returns the freshly probed {name: ToolStatus}. Never raises beyond probe errors.
    """
    fab = get_tool_fabric()
    cache = dict(getattr(fab, "_cache", {}) or {})
    cache["ffmpeg"] = _probe_ffmpeg()
    cache["godot"] = _probe_godot()
    try:
        with fab._lock:
            fab._cache.update(cache)
    except Exception:
        pass
    fab._write_backend_scan(cache)
    return {"ffmpeg": cache["ffmpeg"], "godot": cache["godot"]}
