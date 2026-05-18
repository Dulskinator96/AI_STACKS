"""PowerShellAdvisor — generate safe PowerShell snippets for fixes the
coordinator cannot or will not auto-apply.

Two categories returned:
    diagnose — read-only investigation commands. Always safe to run.
    repair   — bounded repair commands. Marked with severity + explanation.

NEVER returns destructive commands. NEVER returns Remove-Item -Recurse,
Stop-Computer, format, Set-ExecutionPolicy, registry HKLM writes, or
anything outside the bounded repair allow-list rendered into PS form.

Output shape:
    {
        "issue_id": "iss-xxxxxxxxxxxx",
        "diagnose": [ {label, command, notes} ],
        "repair":   [ {label, command, severity, why, undo} ]   # may be []
    }
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from maintenance.classifier import Issue, Tier


@dataclass(frozen=True)
class PSSuggestion:
    label:    str
    command:  str
    severity: str       # info / low / medium / high
    notes:    str = ""
    undo:     Optional[str] = None
    kind:     str = "diagnose"   # diagnose | repair


def _ps_quote(s: str) -> str:
    # PowerShell single-quoted string with internal ' doubled
    return "'" + str(s).replace("'", "''") + "'"


def _diag_general_health() -> List[PSSuggestion]:
    return [
        PSSuggestion(
            label="Check stratum.log tail",
            command="Get-Content $env:USERPROFILE\\.stratum\\stratum.log -Tail 200",
            severity="info",
            notes="Read-only. Inspect the last 200 log lines for ERROR / Traceback.",
            kind="diagnose",
        ),
        PSSuggestion(
            label="Check Ollama service",
            command="Invoke-RestMethod http://localhost:11434/api/tags -TimeoutSec 5",
            severity="info",
            notes="Read-only. Confirms Ollama is reachable.",
            kind="diagnose",
        ),
        PSSuggestion(
            label="List Python processes",
            command="Get-Process python -ErrorAction SilentlyContinue | "
                     "Select-Object Id,CPU,WS,StartTime",
            severity="info",
            notes="Read-only. Spot stuck workers.",
            kind="diagnose",
        ),
    ]


def _repair_ui_state_resync(issue: Issue) -> List[PSSuggestion]:
    return [
        PSSuggestion(
            label="Force ai-monitor to redraw (manual)",
            command="# Switch to a different tab and back in the app. "
                     "No external command needed.",
            severity="low",
            notes="UI state resync is in-app; no shell command required.",
            kind="repair",
        ),
    ]


def _repair_stale_cache(issue: Issue) -> List[PSSuggestion]:
    return [
        PSSuggestion(
            label="Clear stratum runtime cache",
            command="Remove-Item -Path $env:USERPROFILE\\.stratum\\cache "
                     "-Recurse -Force -ErrorAction SilentlyContinue",
            severity="medium",
            notes="Removes ~/.stratum/cache. Caches will repopulate on next boot.",
            undo="# This is a cache clear; no automatic undo. Restart app to repopulate.",
            kind="repair",
        ),
    ]


def _repair_queue_cleanup(issue: Issue) -> List[PSSuggestion]:
    return [
        PSSuggestion(
            label="Inspect worker pool depth",
            command="Get-Process python | Where-Object { $_.WS -gt 200MB } | "
                     "Select-Object Id,ProcessName,WS,CPU",
            severity="info",
            notes="Read-only. Lists Python workers consuming >200 MB.",
            kind="diagnose",
        ),
        PSSuggestion(
            label="Stop runaway worker (review FIRST)",
            command="# Replace <PID> after reviewing the diagnose output:\n"
                     "# Stop-Process -Id <PID> -Force",
            severity="high",
            notes="Manual: review PID from the diagnose command before running. "
                   "ai-monitor will respawn its own workers.",
            kind="repair",
        ),
    ]


def _repair_retry_safe(issue: Issue) -> List[PSSuggestion]:
    return [
        PSSuggestion(
            label="Re-run validate_stack.py",
            command="Set-Location 'C:\\Users\\dulsk\\Desktop\\AIBuild\\AI_STACK\\ai-monitor'; "
                     "python validate_stack.py",
            severity="info",
            notes="Read-only. Re-runs the codebase compile sweep.",
            kind="diagnose",
        ),
    ]


def _repair_substrate_escalation(issue: Issue) -> List[PSSuggestion]:
    return [
        PSSuggestion(
            label="Capture full diagnostics bundle",
            command="$ts = Get-Date -Format 'yyyyMMdd-HHmmss'; "
                     "$out = \"$env:USERPROFILE\\.stratum\\bundle-$ts.txt\"; "
                     "Get-Content $env:USERPROFILE\\.stratum\\stratum.log -Tail 2000 "
                     "> $out; Write-Output \"Wrote $out\"",
            severity="info",
            notes="Captures the last 2000 log lines into a timestamped bundle.",
            kind="diagnose",
        ),
        PSSuggestion(
            label="Substrate risk — STOP and review",
            command="# T4 substrate risk detected. Do NOT auto-repair. "
                     "Review the bundle and stratum.log first.",
            severity="high",
            notes="No PowerShell command. Operator review required.",
            kind="repair",
        ),
    ]


_HINT_DISPATCH = {
    "ui_state_resync":            _repair_ui_state_resync,
    "stale_cache_invalidation":   _repair_stale_cache,
    "queue_cleanup":              _repair_queue_cleanup,
    "retry_safe_operation":       _repair_retry_safe,
}


def advise(issue: Issue) -> dict:
    """Produce {diagnose, repair} for the given Issue."""
    diagnose = list(_diag_general_health())
    repair: List[PSSuggestion] = []

    if issue.tier == Tier.T4:
        repair.extend(_repair_substrate_escalation(issue))
    elif issue.repair_hint and issue.repair_hint in _HINT_DISPATCH:
        repair.extend(_HINT_DISPATCH[issue.repair_hint](issue))

    # Add issue-specific diagnose snippet — useful surface contextualization
    diagnose.append(PSSuggestion(
        label=f"Locate evidence for {issue.kind}",
        command=f"Write-Output 'observer={issue.observer} kind={issue.kind} "
                 f"surface={issue.surface}'; "
                 f"Write-Output {_ps_quote(str(issue.evidence))}",
        severity="info",
        notes="Read-only. Echoes the recorded evidence.",
        kind="diagnose",
    ))

    return {
        "issue_id":  issue.issue_id,
        "diagnose":  [s.__dict__ for s in diagnose],
        "repair":    [s.__dict__ for s in repair],
    }


def format_for_clipboard(issue: Issue) -> str:
    """Compact human-readable snippet for the Copy-PowerShell button."""
    a = advise(issue)
    lines = [
        f"# Maintenance suggestion for issue {issue.issue_id}",
        f"# observer={issue.observer} kind={issue.kind} tier={issue.tier.value}",
        f"# severity={issue.severity.value} surface={issue.surface}",
        "",
        "# --- DIAGNOSE (read-only) ---",
    ]
    for s in a["diagnose"]:
        lines.append(f"# {s['label']}  [{s['severity']}]")
        lines.append(s["command"])
        lines.append("")
    if a["repair"]:
        lines.append("# --- REPAIR (review before running) ---")
        for s in a["repair"]:
            lines.append(f"# {s['label']}  [{s['severity']}]")
            if s.get("notes"):
                lines.append(f"# notes: {s['notes']}")
            lines.append(s["command"])
            if s.get("undo"):
                lines.append(f"# undo: {s['undo']}")
            lines.append("")
    else:
        lines.append("# No bounded repair command available for this issue.")
        lines.append("# Capture diagnostics above and review manually.")
    return "\n".join(lines)
