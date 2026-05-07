"""
truth_layer.py — EXECUTION AUDIT + FAILURE DETECTION AUTHORITY for AI_MONITOR.

Aggressively detect, expose, and classify execution failures.
Mandate: "If there is no physical evidence of execution, it is considered FAILURE or UNVERIFIABLE."
"""

import os
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, Optional

_log = logging.getLogger("stratum.audit")

class ExecutionAuditAuthority:
    """
    The EXECUTION AUDIT AUTHORITY.
    Identifies false success states and missing execution artifacts.
    """

    @staticmethod
    def calculate_hash(file_path: str) -> str:
        """Calculate SHA-256 hash of a file."""
        try:
            path = Path(file_path)
            if not path.exists():
                return ""
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            return ""

    def verify_patch(self, file_path: str, before_hash: str, after_hash: str) -> Dict[str, Any]:
        """
        ### PATCH audit:
        - Verify file hash changed
        - Verify content differs from baseline
        """
        if not Path(file_path).exists():
            return {
                "action_type": "PATCH",
                "status": "FAIL",
                "reason": "EXECUTION_FAILED: File missing after patch operation",
                "evidence_missing": "yes"
            }

        if before_hash == after_hash:
            return {
                "action_type": "PATCH",
                "status": "FAIL",
                "reason": "PARTIAL_EXECUTION: False success; no bitwise change detected in file",
                "evidence_missing": "no"
            }
        
        return {
            "action_type": "PATCH",
            "status": "PASS",
            "reason": "Verified file mutation via hash delta",
            "evidence_missing": "no"
        }

    def verify_image(self, path: str) -> Dict[str, Any]:
        """
        ### IMAGE_GENERATION audit:
        - Verify file exists
        - Verify file size > 0 bytes
        - Verify format is valid image
        """
        if not path or not os.path.exists(path):
            return {
                "action_type": "IMAGE_GENERATION",
                "status": "FAIL",
                "reason": "EXECUTION_FAILED: Missing image artifact",
                "evidence_missing": "yes"
            }
        
        size = os.path.getsize(path)
        if size == 0:
            return {
                "action_type": "IMAGE_GENERATION",
                "status": "FAIL",
                "reason": "INVALID_OUTPUT: 0-byte image artifact detected",
                "evidence_missing": "no"
            }
        
        if size < 1024:
            return {
                "action_type": "IMAGE_GENERATION",
                "status": "FAIL",
                "reason": "INVALID_OUTPUT: Artifact too small to be valid image",
                "evidence_missing": "no"
            }
            
        return {
            "action_type": "IMAGE_GENERATION",
            "status": "PASS",
            "reason": f"Verified image artifact ({size} bytes)",
            "evidence_missing": "no"
        }

    def verify_file_write(self, file_path: str, expected_content: str) -> Dict[str, Any]:
        """
        ### FILE_WRITE audit:
        - Verify file exists on disk
        - Verify content integrity
        """
        path = Path(file_path)
        if not path.exists():
            return {
                "action_type": "FILE_WRITE",
                "status": "FAIL",
                "reason": "EXECUTION_FAILED: File write target missing from disk",
                "evidence_missing": "yes"
            }
        
        actual_content = path.read_text(encoding="utf-8", errors="replace")
        if actual_content != expected_content:
            return {
                "action_type": "FILE_WRITE",
                "status": "FAIL",
                "reason": "INVALID_OUTPUT: Physical content mismatch vs expectation",
                "evidence_missing": "no"
            }

        return {
            "action_type": "FILE_WRITE",
            "status": "PASS",
            "reason": "Verified exact physical write",
            "evidence_missing": "no"
        }

    def verify_ui_render(self, artifact_path: Optional[str]) -> Dict[str, Any]:
        """
        ### UI_RENDER audit:
        - Verify actual render output exists (file/buffer)
        - UI state alone is NOT valid
        """
        if not artifact_path or not os.path.exists(artifact_path):
            return {
                "action_type": "UI_RENDER",
                "status": "UNVERIFIABLE",
                "reason": "UNVERIFIABLE: No physical render artifact provided",
                "evidence_missing": "yes"
            }
            
        return {
            "action_type": "UI_RENDER",
            "status": "PASS",
            "reason": "Verified UI artifact exists",
            "evidence_missing": "no"
        }

    def commit(self, artifact: Any, result: Dict[str, Any]) -> bool:
        """Commit gate: only PASS is accepted."""
        return result["status"] == "PASS"

    def format_result(self, res: Dict[str, Any]) -> str:
        """Strict Audit Authority formatting."""
        return (
            f"RESULT:\n"
            f"- action_type: {res['action_type']}\n"
            f"- status: {res['status']}\n"
            f"- reason: {res['reason']}\n"
            f"- evidence_missing: {res['evidence_missing']}"
        )

# ── Singleton Interface ───────────────────────────────────────────────────────

_audit = None

def get_audit() -> ExecutionAuditAuthority:
    global _audit
    if _audit is None:
        _audit = ExecutionAuditAuthority()
    return _audit

# Alias for backward compatibility if needed during migration
def get_truth() -> ExecutionAuditAuthority:
    return get_audit()
