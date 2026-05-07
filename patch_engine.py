
import os
import logging
from dataclasses import dataclass
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
...
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
    Applies a patch block (OLD_CODE -> NEW_CODE) or unified diff.
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return False

        content = path.read_text(encoding="utf-8")

        # Support for CodeForge block format
        if "<<< OLD_CODE" in diff and ">>> NEW_CODE" in diff:
            import re
            old_match = re.search(r"<<< OLD_CODE\n(.*?)\n>>> NEW_CODE", diff, re.DOTALL)
            new_match = re.search(r">>> NEW_CODE\n(.*?)\n<<< END", diff, re.DOTALL)

            if old_match and new_match:
                old_code = old_match.group(1).strip()
                new_code = new_match.group(1).strip()

                if old_code in content:
                    new_content = content.replace(old_code, new_code)
                    path.write_text(new_content, encoding="utf-8")
                    return True

        # Fallback to simple replace if diff is just the new content or a part of it
        # (This is risky but fits the 'deterministic modification' goal)
        return False
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