
import os
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from pathlib import Path

# AI_MONITOR Imports
import helixchain
from simcore import SimCore
import truth_layer

_log = logging.getLogger(__name__)

# =========================
# PATCH CORE SCHEMA OBJECTS
# =========================

import re
import uuid


@dataclass
class Patch:
    """Structured patch produced by parse_patch_response."""
    diff:     str
    mode:     str
    risk:     float
    metadata: dict


def parse_patch_response(raw_output: str) -> Optional[Patch]:
    """Parse CodeForge block format. Returns None on malformed output.

    Expected format:
        <<< OLD_CODE
        ...exact existing snippet...
        >>> NEW_CODE
        ...replacement snippet...
        <<< END

    Risk heuristic: hunk length + multi-line span. Conservative bias.
    """
    if not isinstance(raw_output, str) or not raw_output:
        return None
    if "<<< UNRESOLVED >>>" in raw_output:
        return None
    if "<<< OLD_CODE" not in raw_output or ">>> NEW_CODE" not in raw_output:
        return None
    if "<<< END" not in raw_output:
        return None
    # Round-trip: ensure both markers present in correct order
    old_idx = raw_output.find("<<< OLD_CODE")
    new_idx = raw_output.find(">>> NEW_CODE")
    end_idx = raw_output.find("<<< END")
    if not (old_idx < new_idx < end_idx):
        return None

    # Extract old + new
    old_match = re.search(r"<<< OLD_CODE\n(.*?)\n>>> NEW_CODE",
                          raw_output, re.DOTALL)
    new_match = re.search(r">>> NEW_CODE\n(.*?)\n<<< END",
                          raw_output, re.DOTALL)
    if not (old_match and new_match):
        return None
    old_code = old_match.group(1)
    new_code = new_match.group(1)
    if not old_code.strip():
        return None

    # Risk heuristic: longer hunks + multi-line span = higher risk
    line_span = max(old_code.count("\n"), new_code.count("\n")) + 1
    char_delta = abs(len(new_code) - len(old_code))
    risk = min(0.85, 0.10 + 0.05 * line_span + 0.0005 * char_delta)
    if line_span >= 25 or char_delta >= 2000:
        risk = max(risk, 0.90)  # auto-bumps to manual gate

    return Patch(
        diff=raw_output,
        mode="codeforge_block",
        risk=round(risk, 3),
        metadata={"id": str(uuid.uuid4()), "line_span": line_span,
                   "char_delta": char_delta},
    )


def validate_diff(file_content: str, diff: str) -> bool:
    """Structural check before patch application.

    Ensures: diff is non-empty, contains both markers, and the OLD_CODE
    snippet actually exists in file_content (substring match).
    """
    if not isinstance(diff, str) or not diff:
        return False
    if "<<< OLD_CODE" not in diff or ">>> NEW_CODE" not in diff:
        return False
    old_match = re.search(r"<<< OLD_CODE\n(.*?)\n>>> NEW_CODE",
                          diff, re.DOTALL)
    if not old_match:
        return False
    old_code = old_match.group(1).strip()
    if not old_code:
        return False
    # Must be present in the actual file content
    return old_code in file_content


# =========================
# CORE PATCH ENGINE
# =========================

def run_patch_pipeline(file_path, intent, context, file_content, ai_call_fn):
    _log.info(f"Starting patch pipeline for {file_path}")

    # STEP 1 — build packet
    packet = build_patch_packet(file_path, intent, context, file_content)

    # STEP 2 — AI generation
    raw_output = ai_call_fn(packet)

    # STEP 3 — parse
    patch = parse_patch_response(raw_output)

    if patch is None:
        return {
            "status": "rejected",
            "reason": "parse failure",
            "file": file_path
        }

    # STEP 4 — validate diff
    if not validate_diff(file_content, patch.diff):
        return {
            "status": "rejected",
            "reason": "invalid diff",
            "file": file_path
        }

    # STEP 5 — risk gate
    if patch.risk >= 0.90:  # Raised threshold for autonomous mode
        return {
            "status": "blocked",
            "reason": "manual approval required",
            "file": file_path,
            "patch": patch
        }

    # ── AUDIT AUTHORITY PRE-FLIGHT ──
    audit = truth_layer.get_audit()
    before_hash = audit.calculate_hash(file_path)

    # STEP 6 — apply patch
    success = apply_patch(file_path, patch.diff)
    if not success:
        return {
            "status": "failed",
            "reason": "IO error during patch application",
            "file": file_path
        }

    # ── AUDIT AUTHORITY VERIFICATION ──
    after_hash = audit.calculate_hash(file_path)
    verdict = audit.verify_patch(file_path, before_hash, after_hash)
    
    if not audit.commit(file_path, verdict):
        _log.error(f"AUDIT FAILURE: {verdict['reason']}")
        return {
            "status": "failed",
            "reason": verdict["reason"],
            "file": file_path,
            "audit_result": verdict
        }

    # STEP 7 — sync system state
    sync_helixchain(file_path)

    # STEP 8 — log result
    log_patch(file_path, intent, patch, "applied")

    # STEP 9 — final output
    return {
        "status": "applied",
        "file": file_path,
        "mode": patch.mode,
        "audit_result": verdict
    }


# =========================
# REAL IMPLEMENTATIONS
# =========================

def build_patch_packet(file_path, intent, context, file_content):
    return {
        "file": file_path,
        "intent": intent,
        "context": context,
        "content": file_content
    }


def apply_patch(file_path, diff):
    """
    Applies a CodeForge OLD_CODE -> NEW_CODE block.

    SAFETY: requires the OLD_CODE to occur EXACTLY ONCE in the file (verbatim,
    including indentation). Refuses ambiguous matches (count != 1) to avoid
    accidental substring corruption of docstrings/comments.
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return False

        content = path.read_text(encoding="utf-8")

        if not ("<<< OLD_CODE" in diff and ">>> NEW_CODE" in diff):
            return False

        import re
        old_match = re.search(r"<<< OLD_CODE\n(.*?)\n>>> NEW_CODE",
                              diff, re.DOTALL)
        new_match = re.search(r">>> NEW_CODE\n(.*?)\n<<< END",
                              diff, re.DOTALL)
        if not (old_match and new_match):
            return False

        # Preserve EXACT old/new (NO strip) -- indentation must match.
        old_code = old_match.group(1)
        new_code = new_match.group(1)

        # Empty or whitespace-only OLD_CODE is forbidden (too loose)
        if not old_code or not old_code.strip():
            return False

        match_count = content.count(old_code)
        if match_count == 0:
            _log.warning("apply_patch: OLD_CODE not found verbatim in %s",
                         file_path)
            return False
        if match_count > 1:
            _log.warning(
                "apply_patch: OLD_CODE matches %d sites in %s -- ambiguous, "
                "refusing", match_count, file_path,
            )
            return False

        new_content = content.replace(old_code, new_code, 1)
        path.write_text(new_content, encoding="utf-8")
        return True
    except Exception as exc:
        _log.error(f"apply_patch failed: {exc}")
        return False


def log_patch(file_path, intent, patch, status):
    """
    Notify simcore of the mutation.
    """
    try:
        sc = SimCore()
        sc.tick({
            "action": "patch",
            "target": file_path,
            "payload": {
                "patch_id": patch.metadata.get("id", "unknown"),
                "risk": patch.risk,
                "mode": patch.mode,
                "intent": str(intent)
            }
        })
    except Exception as exc:
        _log.warning(f"log_patch failed to notify simcore: {exc}")


def sync_helixchain(file_path):
    """
    Re-index file DNA after mutation.
    """
    try:
        path = Path(file_path)
        dna = helixchain.helixread_file(path)
        # In a real system, we'd update a DB here.
        # helixchain.sync_to_detbank has this logic.
        _log.info(f"helixchain re-indexed {file_path}: {len(dna.functions)} funcs")
    except Exception as exc:
        _log.warning(f"sync_helixchain failed: {exc}")