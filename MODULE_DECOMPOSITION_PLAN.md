# Module Decomposition Plan — app.py + pyramid_ui.py

**Status:** PLAN ONLY · awaiting ratification before execution
**Authoring:** 2026-05-16 post-V13 sweep
**Doctrine:** CLAUDE.md SOLID/KISS/MVC + "one class, one reason to change"
**Inventory evidence:** `telemetry/decomp_inventory.json`

---

## Why decompose

| Module | LOC | Size | Classes | Qt classes | Largest class |
|---|---|---|---|---|---|
| **app.py** | 8462 | 364 KB | 16 | 10 | **HistoryDashboard: 4013 LOC / 126 methods** |
| **pyramid_ui.py** | 1943 | 76 KB | 13 | 10 | **PyramidWidget: 515 LOC / 22 methods** |

`HistoryDashboard` alone is **47% of app.py**. A single class with 126 methods violates SRP, drives change-set blast radius, and slows boot (PyInstaller scans the whole file even for unused tabs). pyramid_ui.py is less acute but still benefits from clean View/Worker separation per CLAUDE.md §5.

The decomposition is **structural cleanup**, not feature change. Each extracted module preserves its public API surface so callers don't break.

---

## SEAM ANALYSIS — app.py (10 Qt views + AIMonitorApp + SelfModEngine + helpers)

### Tier 1 — Extract independent Qt views (low risk, high signal)

Each view is self-contained: receives signals from `AIMonitorApp`, renders, emits signals back. They do not call into each other directly (verified by structural grep — no view imports another view's class).

| Current home | Lines | New file | Risk |
|---|---|---|---|
| `LabWidget` (5940-6555) | 616 | `ui/lab_widget.py` | LOW |
| `PortalWindow` (5328-5927) | 600 | `ui/portal_window.py` | LOW |
| `FloatingWidget` (7548-8027) | 480 | `ui/floating_widget.py` | LOW |
| `ManifestWindow` (4943-5321) | 379 | `ui/manifest_window.py` | LOW |
| `DiagnosticsPanel` (7181-7545) | 365 | `ui/diagnostics_panel.py` | LOW |
| `DNAPanel` (6565-6828) | 264 | `ui/dna_panel.py` | LOW |
| `MemPalacePanel` (6921-7172) | 252 | `ui/mempalace_panel.py` | LOW |
| `MemoryAgent` (6850-6918) | 69 | `ui/memory_agent.py` (Qt thread) | LOW |

**Subtotal extracted:** 3025 LOC → 8 new files. app.py shrinks to ~5437 LOC.

### Tier 2 — Decompose HistoryDashboard (4013 LOC, 126 methods)

`HistoryDashboard` is the tab-host. It contains:
- Tab creation logic (~1 method per tab × 21 tabs ≈ 21 methods)
- Tab-specific handler methods (callbacks per tab)
- Cross-cutting state (worker pool, repair bar, history list)

Proposed sub-decomposition:

```
HistoryDashboard (slim, 600-800 LOC after decomp)
├── tabs/timeline_tab.py        — git-style history tab
├── tabs/lab_tab.py             — Lab tab wrapper (delegates to LabWidget)
├── tabs/dna_tab.py             — DNA viz tab
├── tabs/palace_tab.py          — MemPalace tab
├── tabs/diagnostics_tab.py     — Diagnostics tab
├── tabs/portal_tab.py          — Portal tab
├── tabs/manifest_tab.py        — Manifest tab
└── tabs/repair_bar.py          — Apply All bar + WON analyses
```

Each tab module exposes a single `build(parent) -> QWidget` factory function. `HistoryDashboard.__init__` becomes a tab-registration loop, not a 4000-line method.

**Risk:** MEDIUM — needs careful signal/slot rewiring per tab. Suggest one tab at a time with smoke test between extractions.

### Tier 3 — Non-Qt extraction

| Class | Lines | Why | New home |
|---|---|---|---|
| `SelfModEngine` | 149 | Self-modification rules; doesn't depend on Qt | `self_mod_engine.py` |
| `_LazyImport` helper | 34 | Boot-time lazy import shim | `bootstrap.py` |

### Tier 4 — Keep in app.py

| Stays | Why |
|---|---|
| `AIMonitorApp` (329 LOC, 13 methods) | Top-level orchestration; SRP-compliant |
| Top-level constants (25) | Per CLAUDE.md §1 these may eventually move to `config.py` |
| `main()` + `__name__ == '__main__'` block | Launcher entry |

**Projected app.py after decomp:** ~1500 LOC (HistoryDashboard slim + AIMonitorApp + entry point).

---

## SEAM ANALYSIS — pyramid_ui.py (1943 LOC)

Per CLAUDE.md §5 MVC: pyramid_ui.py is the **View layer**. Workers must NOT import requests/sqlite directly — they receive Model output via signals. Some current workers may violate this; the decomposition formalizes the boundary.

### Tier 1 — Extract Qt workers (Model→View seam)

```
pyramid_ui.py (View only)
└── pyramid_workers.py (NEW; Presenter/Worker layer)
    ├── IndexWorker       (lines 419-433, 15 LOC)
    ├── AskWorker         (lines 436-445, 10 LOC)
    └── EnsembleWorker    (lines 862-894, 33 LOC)
```

### Tier 2 — Optional split of large View classes

| Class | Lines | Proposed split |
|---|---|---|
| `PyramidWidget` (1414-1928) | 515 | Stays whole — coherent single responsibility |
| `EnsemblePanel` (1127-1377) | 251 | Stays whole |
| `AgentCard` (899-1114) | 216 | Stays whole |
| `GraphCanvas` (237-414) | 178 | Stays whole |
| `ChatView` (558-731) | 174 | Stays whole |

Most pyramid_ui View classes are below the "needs splitting" threshold (300 LOC heuristic). The big win is just the Worker extraction for MVC compliance.

**Projected pyramid_ui.py after decomp:** ~1885 LOC (workers extracted, ~58 LOC moved).

---

## EXECUTION ORDER (when ratified)

1. **Create directory scaffold:** `ui/`, `ui/tabs/`, `pyramid_workers.py` (empty)
2. **Smoke baseline:** `python validate_stack.py` → record 0 failures, capture import time
3. **Phase A — Tier 1 app.py extraction (8 Qt views)** one at a time:
   - Cut class from app.py
   - Paste into `ui/<name>.py`
   - Add `from ui.<name> import <ClassName>` to app.py
   - `python -c "import app"` to verify import graph
   - `python validate_stack.py` → ensure 0 failures
   - Run live GUI quickly (manual)
4. **Phase B — Tier 3 non-Qt extraction** (SelfModEngine, _LazyImport)
5. **Phase C — Tier 1 pyramid_ui workers** → `pyramid_workers.py`
6. **Phase D — Tier 2 HistoryDashboard sub-decomp** (one tab at a time)
7. **Final smoke:** Full app launch + 21-tab visit
8. **Receipt:** Emit `telemetry/decomp_complete.json`

---

## GOVERNANCE GUARANTEES

- **No semantic changes** — decomposition is pure relocation + import rewiring
- **patch_engine audit lane** — each extraction goes through CodeForge OLD/NEW blocks for traceability
- **`validate_stack.py` after each phase** — must remain 0 failures
- **CLAUDE.md doctrine compliance** — all extractions honor SOLID/MVC/no-Qt-in-Model
- **Rollback:** every phase is a single git commit; `git revert` recovers prior state
- **Constitution receipts** — telemetry emits LAW_3 receipts per file moved

---

## OUT OF SCOPE (separate engagements)

- Refactoring tab logic itself (e.g., reducing HistoryDashboard's 126 methods to fewer)
- Moving constants to `config.py` (CLAUDE.md §1 calls for this but it's a separate audit)
- Visual / UX redesign
- New tabs or features

---

## RATIFICATION CHECKLIST

- [ ] Approve Tier 1 app.py extraction (8 files, low risk)
- [ ] Approve Tier 2 HistoryDashboard sub-decomp (tab-by-tab, medium risk)
- [ ] Approve Tier 3 non-Qt extraction (SelfModEngine, _LazyImport)
- [ ] Approve pyramid_ui Worker extraction
- [ ] Authorize execution sequence (A → B → C → D)
- [ ] Confirm rollback strategy (git per phase)

---

**Awaiting Dan ratification before any cut/paste begins.**
