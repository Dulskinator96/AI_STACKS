"""runtime/workspace_contract.py — RULE 7 enforcement.

A WorkspaceCapabilityContract declares which capabilities a workspace
(tab) needs from the runtime. Construction validates the contract
against the live registry; any unmet REQUIRED capability raises a
CapabilityViolation. Optional capabilities are silently resolved or
None.

Usage from a builder:

    contract = WorkspaceCapabilityContract(
        name="perception",
        required=["maintenance.cortex"],
        optional=["maintenance.ui_state"],
    )
    services = contract.bind(locator)
    cortex = services["maintenance.cortex"]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from runtime.service_locator import RuntimeServiceLocator, get_service_locator

_log = logging.getLogger(__name__)


class CapabilityViolation(RuntimeError):
    """A required capability was not available at bind time."""
    def __init__(self, workspace: str, missing: list[str]):
        super().__init__(
            f"workspace '{workspace}' missing required capabilities: {missing}"
        )
        self.workspace = workspace
        self.missing = missing


@dataclass
class WorkspaceCapabilityContract:
    name: str
    required: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)

    def bind(self, locator: Optional[RuntimeServiceLocator] = None) -> dict[str, Any]:
        """Resolve every declared capability. Raises CapabilityViolation
        if any required capability is unavailable. Returns a flat dict."""
        loc = locator or get_service_locator()
        resolved: dict[str, Any] = {}
        missing: list[str] = []
        for cap in self.required:
            svc = loc.resolve(cap)
            resolved[cap] = svc
            if svc is None:
                missing.append(cap)
        for cap in self.optional:
            resolved[cap] = loc.resolve(cap)
        if missing:
            self._emit_violation_receipt(missing)
            raise CapabilityViolation(self.name, missing)
        self._emit_bound_receipt(resolved)
        return resolved

    def bind_soft(self, locator: Optional[RuntimeServiceLocator] = None) -> dict[str, Any]:
        """Like bind() but never raises — missing required caps come back
        as None and the violation is recorded as PARTIAL."""
        loc = locator or get_service_locator()
        resolved: dict[str, Any] = {}
        missing: list[str] = []
        for cap in self.required + self.optional:
            svc = loc.resolve(cap)
            resolved[cap] = svc
            if cap in self.required and svc is None:
                missing.append(cap)
        if missing:
            self._emit_violation_receipt(missing, partial=True)
        else:
            self._emit_bound_receipt(resolved)
        return resolved

    def _emit_bound_receipt(self, resolved: dict[str, Any]) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"workspace_capability:{self.name}:bound",
                executor="WorkspaceCapabilityContract",
                duration_ms=0.0,
                verified=True,
                compute_sha256=False,
                evidence={
                    "required": list(self.required),
                    "optional": list(self.optional),
                    "resolved": [k for k, v in resolved.items() if v is not None],
                    "absent":   [k for k, v in resolved.items() if v is None],
                },
            )
        except Exception:
            pass

    def _emit_violation_receipt(self, missing: list[str], partial: bool = False) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"workspace_capability:{self.name}:violation",
                executor="WorkspaceCapabilityContract",
                duration_ms=0.0,
                verified=False,
                compute_sha256=False,
                failure_reason=("partial_bind" if partial else "required_unavailable"),
                evidence={"missing": list(missing), "required": list(self.required)},
            )
        except Exception:
            pass
