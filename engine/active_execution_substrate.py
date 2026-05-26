"""engine/active_execution_substrate.py — BUILD-022 ToolFabric rewrite.

ActiveExecutionSubstrate evolves ToolFabric from passive discovery into
an active execution layer. New responsibilities:
  · version detection (ffmpeg -version, godot --version, etc.)
  · subprocess spawning with timeout + capture
  · health verification (e.g., ComfyUI /system_stats reachable)
  · execution capability scoring
  · hardware fit scoring (delegates to ProductionToolFabric)
  · backend benchmarking (timing per tool when first used)

Maintained in parallel with ToolFabric — ToolFabric still does cheap
periodic refresh; this layer adds the "do work via this tool" pathway.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass
class ToolInvocation:
    invocation_id: str
    tool:          str
    cmd:           list
    started_at:    float
    finished_at:   float = 0.0
    returncode:    Optional[int] = None
    stdout:        str = ""
    stderr:        str = ""
    duration_ms:   float = 0.0
    timed_out:     bool = False
    raised:        str = ""

    def to_dict(self) -> dict:
        return {
            "invocation_id": self.invocation_id,
            "tool":          self.tool,
            "cmd_brief":     " ".join(map(str, self.cmd[:6])),
            "started_at":    self.started_at,
            "finished_at":   self.finished_at,
            "duration_ms":   self.duration_ms,
            "returncode":    self.returncode,
            "timed_out":     self.timed_out,
            "raised":        self.raised,
        }


@dataclass
class ToolProfile:
    tool:           str
    version:        str = ""
    last_version_at: float = 0.0
    invocation_count: int = 0
    avg_duration_ms: float = 0.0
    last_invocation: Optional[ToolInvocation] = None
    last_error:     str = ""


class ActiveExecutionSubstrate:
    """Active execution layer over discovered tools."""

    def __init__(self):
        self._profiles: dict[str, ToolProfile] = {}
        self._lock = threading.RLock()
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.active_execution_substrate", self)
        except Exception:
            pass

    # ── Version + health ──────────────────────────────────────────────
    def detect_version(self, tool: str) -> str:
        """Probe `tool --version` (and a few variants). Returns version
        string or '' if not detectable."""
        path = shutil.which(tool)
        if not path:
            return ""
        for flag in ("--version", "-version", "-v", "version"):
            try:
                proc = subprocess.run([path, flag], capture_output=True,
                                        timeout=4)
                out = (proc.stdout or proc.stderr).decode(errors="ignore")
                # Take first non-empty line
                for line in out.splitlines():
                    if line.strip():
                        with self._lock:
                            prof = self._get_profile(tool)
                            prof.version = line.strip()[:120]
                            prof.last_version_at = time.time()
                        return line.strip()[:120]
            except Exception:
                continue
        return ""

    def health_check(self, tool: str) -> dict:
        """Return {available: bool, version: str, where: path|url}."""
        # Map tool → custom probe
        if tool == "comfyui":
            return self._http_health("comfyui", "http://127.0.0.1:8188/system_stats")
        if tool == "automatic1111":
            return self._http_health("automatic1111",
                                       "http://127.0.0.1:7860/sdapi/v1/options")
        if tool == "ollama":
            try:
                from config import OLLAMA_URL
                return self._http_health("ollama", OLLAMA_URL.rstrip("/") + "/api/tags")
            except Exception:
                return self._http_health("ollama",
                                          "http://127.0.0.1:11434/api/tags")
        if tool == "lm_studio":
            try:
                from config import LM_STUDIO_URL
                return self._http_health("lm_studio",
                                          LM_STUDIO_URL.rstrip("/") + "/v1/models")
            except Exception:
                return self._http_health("lm_studio",
                                          "http://127.0.0.1:1234/v1/models")
        # Default: CLI presence + version
        path = shutil.which(tool)
        if not path:
            return {"available": False, "version": "",
                    "where": "", "remediation": f"install {tool}"}
        ver = self.detect_version(tool)
        return {"available": True, "version": ver, "where": path}

    def _http_health(self, tool: str, url: str) -> dict:
        try:
            import requests
            r = requests.get(url, timeout=2)
            if r.status_code in (200, 404):
                return {"available": True, "version": "",
                        "where": url, "http_status": r.status_code}
            return {"available": False, "version": "",
                    "where": url, "http_status": r.status_code,
                    "remediation": "service returned non-200"}
        except Exception as e:
            return {"available": False, "version": "",
                    "where": url, "error": str(e),
                    "remediation": f"start the {tool} service"}

    # ── Subprocess execution ──────────────────────────────────────────
    def run(self, tool: str, args: list, timeout: float = 30.0,
             stdin_bytes: Optional[bytes] = None) -> ToolInvocation:
        """Spawn a subprocess for `tool` with `args`. Captures stdout +
        stderr. Records timing and updates the profile. Never raises —
        all errors are captured into the ToolInvocation."""
        import uuid
        t0 = time.time()
        path = shutil.which(tool)
        invocation = ToolInvocation(
            invocation_id=f"inv-{uuid.uuid4().hex[:10]}",
            tool=tool,
            cmd=[path or tool] + list(args),
            started_at=t0,
        )
        if path is None:
            invocation.raised = f"{tool} not on PATH"
            invocation.finished_at = time.time()
            invocation.duration_ms = (invocation.finished_at - t0) * 1000.0
            self._record(invocation)
            return invocation
        try:
            proc = subprocess.run(
                [path] + [str(a) for a in args],
                input=stdin_bytes,
                capture_output=True, timeout=timeout,
            )
            invocation.returncode = proc.returncode
            invocation.stdout = proc.stdout.decode(errors="ignore")[:4000]
            invocation.stderr = proc.stderr.decode(errors="ignore")[:4000]
        except subprocess.TimeoutExpired:
            invocation.timed_out = True
        except Exception as e:
            invocation.raised = str(e)
        invocation.finished_at = time.time()
        invocation.duration_ms = (invocation.finished_at - t0) * 1000.0
        self._record(invocation)
        return invocation

    def _record(self, inv: ToolInvocation) -> None:
        with self._lock:
            prof = self._get_profile(inv.tool)
            prof.invocation_count += 1
            # Running average
            if prof.invocation_count == 1:
                prof.avg_duration_ms = inv.duration_ms
            else:
                prof.avg_duration_ms = (
                    prof.avg_duration_ms * (prof.invocation_count - 1) +
                    inv.duration_ms
                ) / prof.invocation_count
            prof.last_invocation = inv
            if inv.raised or inv.timed_out or (inv.returncode is not None and inv.returncode != 0):
                prof.last_error = (inv.raised or inv.stderr[:200] or
                                     f"rc={inv.returncode}" or "timeout")
            else:
                prof.last_error = ""
        self._emit_receipt(inv)

    def _get_profile(self, tool: str) -> ToolProfile:
        prof = self._profiles.get(tool)
        if prof is None:
            prof = ToolProfile(tool=tool)
            self._profiles[tool] = prof
        return prof

    # ── Capability scoring (delegates to ProductionToolFabric) ───────
    def capability_score(self, tool: str) -> float:
        try:
            from engine.production_tool_fabric import get_production_tool_fabric
            return get_production_tool_fabric().score(tool).score
        except Exception:
            return 0.5

    # ── Query API ─────────────────────────────────────────────────────
    def profile(self, tool: str) -> dict:
        with self._lock:
            prof = self._profiles.get(tool)
            if prof is None:
                return {"tool": tool, "tracked": False}
            return {
                "tool":            prof.tool,
                "version":         prof.version,
                "invocation_count": prof.invocation_count,
                "avg_duration_ms": round(prof.avg_duration_ms, 1),
                "last_error":      prof.last_error,
                "last_invocation": (prof.last_invocation.to_dict()
                                     if prof.last_invocation else None),
            }

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "profiles":      {t: self.profile(t) for t in self._profiles},
                "tool_count":    len(self._profiles),
            }

    def _emit_receipt(self, inv: ToolInvocation) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"execution_substrate:invoke:{inv.tool}",
                executor="ActiveExecutionSubstrate",
                duration_ms=inv.duration_ms,
                verified=(inv.returncode == 0 and not inv.timed_out and not inv.raised),
                compute_sha256=False,
                failure_reason=(inv.raised or
                                  (f"rc={inv.returncode}" if inv.returncode not in (0, None) else None) or
                                  ("timeout" if inv.timed_out else None)),
                evidence=inv.to_dict(),
            )
        except Exception:
            pass


_INSTANCE: Optional[ActiveExecutionSubstrate] = None


def get_execution_substrate() -> ActiveExecutionSubstrate:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ActiveExecutionSubstrate()
    return _INSTANCE
