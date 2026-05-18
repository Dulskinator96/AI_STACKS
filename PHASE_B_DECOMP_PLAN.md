# Phase B Decomposition Plan — Live Runtime Graph

**Authoring:** 2026-05-17 · **Doctrine:** CLAUDE.md SOLID/MVC + "one class, one reason to change"
**Status:** PLAN ONLY — supersedes `MODULE_DECOMPOSITION_PLAN.md` (2026-05-16) by reframing around runtime tiers instead of pure file-cut. No edits to `app.py` are authorized by this document.

## Current state
- **app.py LOC:** 8571 (was 8462 at last inventory; +109 since)
- **Top-level classes:** 16 · **total methods across them:** ~210
- **Top-level functions:** 22 (boot helpers, `main()`, splash, single-instance)
- **Biggest classes (live, from `_decomp_inventory.py` re-run):**
  1. `HistoryDashboard`  L835–4817  ~3983 LOC · 126 methods (QMainWindow tab host)
  2. `AIMonitorApp`      L8121–end  ~450 LOC (orchestration root — grew since prior plan)
  3. `LabWidget`         L6009–6632 ~624 LOC
  4. `PortalWindow`      L5397–6007 ~611 LOC
  5. `FloatingWidget`    L7549–8037 ~489 LOC
- Other Qt views: `ManifestWindow` (~386), `DiagnosticsPanel` (~367), `DNAPanel` (~289), `MemPalacePanel` (~261)
- Non-Qt: `SelfModEngine` (~149), `_LazyImport`/`_LazyOK`/`NativeBridge`/`Worker`/`_StatusShim` (small shims)

Phase A already landed: `core/lifecycle.py`, `core/profiler.py`, `core/state_manager.py`, `core/services.py`, `truth/receipt_engine.py`, `ui/memory_agent.py`, `ui/maintenance_panel.py`, the full `maintenance/` tree.

## Target tier structure
```
lifecycle/      <- boot, splash, single-instance, tray, fatal-startup, comtypes cache
ui_shell/       <- HistoryDashboard slim + tab host + repair bar + theme application
orchestration/  <- AIMonitorApp top-level coord (NativeBridge, Worker, daemon hooks)
agent_runtime/  <- WON daemon glue, gemini bridge proxies, pulse, harvester, SelfModEngine
state_engine/   <- extend core/state_manager (profile load/save, _StatusShim, get_active_theme)
telemetry/      <- consolidate profiler, receipts, daemon-status, notification routing
```
(Existing `core/` stays. `lifecycle/`, `ui_shell/`, `orchestration/`, `agent_runtime/`, `state_engine/` are NEW siblings — `state_engine/` re-exports from `core/state_manager.py` for back-compat.)

## Per-tier extraction targets

### lifecycle/  (HIGH risk — boot chain order is load-bearing)
- `_prepare_comtypes_cache_for_frozen_exe()` L64 → `lifecycle/comtypes_cache.py`
- `_acquire_single_instance_lock()` L8039 → `lifecycle/single_instance.py`
- `_make_boot_splash()` L8082 → `lifecycle/splash.py`
- `startup_log()`, `show_fatal_startup_error()` L315/322 → `lifecycle/fatal.py`
- `_tray_icon_path()`, `app_root()`, `_resource_roots()` L302/287/294 → `lifecycle/paths.py`

### ui_shell/  (HIGH — touches every tab)
- `HistoryDashboard` L835–4817 → `ui_shell/dashboard.py` (slim shell after tab extraction)
- Per-tab build methods → `ui_shell/tabs/{timeline,lab,dna,palace,diagnostics,portal,manifest,repair_bar}.py` (each exposes `build(parent) -> QWidget`)
- `apply_app_theme`, `register_custom_theme`, `_build_theme_style`, `get_active_theme` L4935–4998 → `ui_shell/theme.py`
- Independent Qt views (move whole-class, no internal split needed):
  - `LabWidget` → `ui_shell/views/lab_widget.py`
  - `PortalWindow` → `ui_shell/views/portal_window.py`
  - `FloatingWidget` → `ui_shell/views/floating_widget.py`
  - `ManifestWindow` → `ui_shell/views/manifest_window.py`
  - `DiagnosticsPanel` → `ui_shell/views/diagnostics_panel.py`
  - `DNAPanel` → `ui_shell/views/dna_panel.py`
  - `MemPalacePanel` → `ui_shell/views/mempalace_panel.py`

### orchestration/  (MED — central coord)
- `AIMonitorApp` L8121–end → `orchestration/app_root.py` (keep `main()` in `app.py` for launcher compat)
- `NativeBridge` L272 → `orchestration/native_bridge.py`
- `Worker(QThread)` L588 → `orchestration/worker.py`
- `build_chaperone_prompt()` L367 → `orchestration/chaperone_prompt.py`

### agent_runtime/  (MED — daemon + mod engine)
- `SelfModEngine` L681 → `agent_runtime/self_mod_engine.py`
- `get_won_pipeline()`, `get_perception()` L553/577 → `agent_runtime/pipeline_provider.py`
- `get_daemon_status()`, `get_daemon_notifications()`, `mark_notifications_read()` L632–665 → `agent_runtime/daemon_proxy.py`
- `ollama_available()` L668 → `agent_runtime/ollama_probe.py`

### state_engine/  (LOW — additive re-exports)
- `load_profile()`, `save_profile()` L351/361 → `state_engine/profile.py` (proxied through existing `core/state_manager.py`)
- `_StatusShim` L5001 → `state_engine/status_shim.py`

### telemetry/  (LOW — already a directory; consolidate routing)
- Daemon notification persistence currently inline in `app.py` → `telemetry/notifications.py`
- `_LazyImport`, `_LazyOK` L126/162 → `telemetry/lazy_import.py` (boot-instrumented shim)

## Risk classification
- **LOW** — `LabWidget`, `PortalWindow`, `FloatingWidget`, `ManifestWindow`, `DiagnosticsPanel`, `DNAPanel`, `MemPalacePanel`, `SelfModEngine`, `_LazyImport`/`_LazyOK`, theme helpers. These are pure cut-and-import.
- **MED** — `AIMonitorApp`, `NativeBridge`, `Worker`, daemon proxies. Cross-reference each other and `HistoryDashboard`; need callsite rewiring.
- **HIGH** — `HistoryDashboard` decomposition (4000 LOC, 126 methods, internal signal/slot web), entire `lifecycle/` chain (order of `_prepare_comtypes_cache → _acquire_single_instance_lock → _make_boot_splash → AIMonitorApp.__init__` is timing-sensitive — wrong order breaks frozen-exe boot).

## Execution sequencing
1. Re-run `_decomp_inventory.py` against current 8571-LOC `app.py`; commit refreshed `telemetry/decomp_inventory.json` as the baseline truth.
2. Capture lifecycle smoke baseline: `python validate_stack.py` + `python -m maintenance.tests.smoke_lifecycle` → record 0 failures + cold-boot ms.
3. **Tier LOW first** — extract the 7 independent Qt views one at a time (each: cut → paste → import-rewire → `python -c "import app"` → `validate_stack.py` → quick GUI launch). Order by size descending: LabWidget, PortalWindow, FloatingWidget, ManifestWindow, DiagnosticsPanel, DNAPanel, MemPalacePanel.
4. **state_engine/** + **telemetry/** additive moves (`load_profile`, `save_profile`, `_LazyImport`, `_StatusShim`, notifications). All LOW.
5. **agent_runtime/** — `SelfModEngine` first (self-contained), then daemon proxies + `ollama_available()` + pipeline providers.
6. **orchestration/** — `NativeBridge`, `Worker`, `build_chaperone_prompt`, then `AIMonitorApp` last.
7. **lifecycle/** — extract bottom-up: `paths.py` → `comtypes_cache.py` → `fatal.py` → `splash.py` → `single_instance.py`. Lifecycle smoke after each.
8. **ui_shell/** — theme first (low risk), then `HistoryDashboard` tab-by-tab (one tab per commit, smoke between). Repair bar last (it cross-cuts).
9. Final: `app.py` collapses to launcher + `main()` (target < 200 LOC). Emit `telemetry/phase_b_complete.json` receipt.

## NOT in scope
- Behavioral changes (pure relocation; signatures and signal/slot wiring preserved)
- New features, new tabs, new tools
- Refactor of `HistoryDashboard`'s 126 methods into fewer methods (separate engagement)
- Moving string constants to `config.py` (CLAUDE.md §1 cleanup is its own audit)
- Touching `pyramid_ui.py` — out of Phase B scope per user direction

## Smoke gates
After every extraction commit:
- `python validate_stack.py` — must remain 0 failures
- `python -m maintenance.tests.smoke_lifecycle` — boot chain green
- `python -c "import app"` — import graph intact
- Manual: launch via `launch_monitor.bat`, click each of the 21 tabs once

## Honest uncertainty
- The 126-method `HistoryDashboard` likely has implicit `self.*` coupling between tab-build methods and shared state (worker pool, repair bar refs). I have not yet mapped that coupling. Tab-by-tab extraction may require introducing a shared `DashboardContext` dataclass; that is a Phase B decision, not pre-decided here.
- `AIMonitorApp` grew ~120 LOC since the prior plan. Re-inventory before Tier-orchestration work.
- Frozen-exe boot order (comtypes/splash/single-instance) is brittle — extraction must preserve exact call sequence. A failed boot is silent; only lifecycle smoke catches it.
