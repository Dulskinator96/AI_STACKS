"""ui/workspace_factory.py — RULE 3: LAZY TAB FACTORY.

Replaces the eager addTab pattern. Boot inserts WorkspaceStub placeholders
for each registered tab; first activation runs the builder which swaps
the stub for the real widget. Indexes are frozen at registration time —
all stored tab indices (`_py_tab_index`, `_portal_tab_index`, etc.)
remain valid.

Public API:
    LazyWorkspaceFactory(tab_widget, dashboard)
    .register(label, builder_fn, contract=None) -> slot_idx
    .activate(slot_idx)                  # idempotent build
    .name_to_index(label) -> int|None
    .built_count(), .total_count()
    .built_names()
    .install_on(tabs)                    # wires currentChanged
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


class LazyWorkspaceFactory:
    """Owns the boot-time placeholder installation and click-driven
    widget construction. Must be installed BEFORE any builder runs."""

    def __init__(self, tab_widget: Any, dashboard: Any):
        self._tabs = tab_widget
        self._dashboard = dashboard
        self._slots: dict[int, dict] = {}
        self._name_idx: dict[str, int] = {}
        self._current_slot: Optional[int] = None
        self._build_failures: dict[int, str] = {}

    def register(self, label: str, builder_fn: Callable[[], None],
                 contract: Any = None) -> int:
        """Install a placeholder WorkspaceStub at the next addTab slot.
        Returns the slot index — fixed for the lifetime of the session."""
        stub = self._make_stub(label)
        idx = self._tabs.addTab(stub, label)
        self._slots[idx] = {
            "label":     label,
            "builder":   builder_fn,
            "built":     False,
            "stub":      stub,
            "widget":    None,
            "contract":  contract,
            "registered_at": time.time(),
        }
        self._name_idx[label] = idx
        return idx

    def install_on(self, tabs: Any) -> None:
        """Connect the tab's currentChanged signal to drive activation."""
        try:
            tabs.currentChanged.connect(self._on_tab_changed)
        except Exception as e:
            _log.warning("LazyWorkspaceFactory install failed: %s", e)

    def activate(self, slot_idx: int) -> bool:
        """Idempotent build. Returns True if a build ran (or already built)."""
        slot = self._slots.get(slot_idx)
        if slot is None:
            return False
        if slot["built"]:
            return True
        slot["built"] = True
        try:
            from truth.receipt_engine import record_execution
        except Exception:
            record_execution = None

        t0 = time.time()
        self._current_slot = slot_idx
        try:
            slot["builder"]()
        except Exception as e:
            slot["built"] = False
            self._build_failures[slot_idx] = str(e)
            _log.exception("lazy builder '%s' failed", slot["label"])
            if record_execution is not None:
                try:
                    record_execution(
                        task=f"workspace_capability:{slot['label']}:build_failed",
                        executor="LazyWorkspaceFactory",
                        duration_ms=(time.time() - t0) * 1000.0,
                        verified=False,
                        compute_sha256=False,
                        failure_reason=str(e)[:200],
                    )
                except Exception:
                    pass
            return False
        finally:
            self._current_slot = None

        if record_execution is not None:
            try:
                record_execution(
                    task=f"workspace_capability:{slot['label']}:built",
                    executor="LazyWorkspaceFactory",
                    duration_ms=(time.time() - t0) * 1000.0,
                    verified=True,
                    compute_sha256=False,
                    evidence={"slot_idx": slot_idx, "label": slot["label"]},
                )
            except Exception:
                pass
        return True

    def install_widget(self, widget: Any) -> None:
        """Called from inside a builder to install the actual widget at
        the currently-activating slot. Replaces the placeholder; tab
        label and index are preserved."""
        idx = self._current_slot
        if idx is None or idx not in self._slots:
            # Builder called outside an activate() — defensive fallback:
            # append at end (matches legacy addTab behavior).
            self._tabs.addTab(widget, "untitled")
            return
        slot = self._slots[idx]
        label = self._tabs.tabText(idx) or slot["label"]
        # Suppress signal recursion while swapping.
        try:
            self._tabs.blockSignals(True)
            self._tabs.removeTab(idx)
            self._tabs.insertTab(idx, widget, label)
        finally:
            self._tabs.blockSignals(False)
        slot["widget"] = widget
        slot["stub"] = None

    def name_to_index(self, label: str) -> Optional[int]:
        return self._name_idx.get(label)

    def widget_for(self, label: str) -> Optional[Any]:
        idx = self.name_to_index(label)
        if idx is None:
            return None
        slot = self._slots.get(idx, {})
        return slot.get("widget")

    def current_slot(self) -> Optional[int]:
        return self._current_slot

    def built_count(self) -> int:
        return sum(1 for s in self._slots.values() if s["built"])

    def total_count(self) -> int:
        return len(self._slots)

    def built_names(self) -> list[str]:
        return [s["label"] for s in self._slots.values() if s["built"]]

    def is_lazy_tab(self, idx: int) -> bool:
        return idx in self._slots

    def _make_stub(self, label: str) -> Any:
        try:
            from PyQt6.QtWidgets import QLabel
            from PyQt6.QtCore import Qt
            stub = QLabel(f"  Loading {label.strip()}…")
            stub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stub.setStyleSheet(
                "QLabel { background: #06091c; color: #5070a0; "
                "font-size: 14pt; padding: 32px; }"
            )
            return stub
        except Exception:
            return None

    def _on_tab_changed(self, idx: int) -> None:
        self.activate(idx)
