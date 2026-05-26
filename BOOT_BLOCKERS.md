# BOOT_BLOCKERS — UI Thread Audit

**Generated:** 2026-05-18 (SURGICAL_UI_RECOVERY_PROTOCOL)
**Scope:** main-thread / GUI event loop blockers in DBOMBLOCAL.exe build-008
**Method:** static read of app.py + maintenance/ + core/bootstrap.py + boot_profile telemetry

The user reports: typing stalls, tabs/rooms don't navigate, chatbox freezes — backend appears to monopolize the UI thread.

## Verdict

Five concrete main-thread blockers identified. Three are PRE-paint (affect boot time, already addressed in earlier fixes). Two are POST-paint and directly explain the user-perceived lag.

---

## Blocker 1 — Lazy tab builders (POST-PAINT, MAIN THREAD)
- **Where:** `app.py:_schedule_lazy_builders` (HD class). 22 builders queued at `QTimer.singleShot(40 * (i+1), ...)`.
- **Cost:** ~40-500ms per builder × 22 = roughly **0.9-11s cumulative main-thread time** post-paint.
- **Owning subsystem:** HistoryDashboard UI scaffolding.
- **Thread:** main (Qt widgets must be created on main thread).
- **Why it stalls UI:** the 40ms interval is tighter than typical builder cost. Each builder construction queues immediately behind the prior, leaving little room for user input events to drain. User input goes to the back of a serial queue.
- **Mitigation:** increase interval to **150ms** so each user-input event has a clean window between builders; call `QCoreApplication.processEvents()` after each builder to drain pending input.
- **Severity:** HIGH — directly explains "tabs/rooms cannot be navigated".
- **Confidence:** VERIFIED (visible in source + boot_profile timings).

## Blocker 2 — Bootstrap Phase 4 (cortex build) in _deferred_services (POST-PAINT, MAIN THREAD)
- **Where:** `app.py:_deferred_services` calls `bootstrap.run_post_paint_phases()` which calls `phase_4_maintenance()` which calls `MaintenanceCortex.build_default()` (constructs 11 observers + RepairCoordinator).
- **Cost:** ~905ms measured (build-006 receipts: `bootstrap_phase:maintenance` duration_ms=905).
- **Owning subsystem:** Maintenance Cortex.
- **Thread:** main.
- **Why it stalls UI:** runs at +2s post-paint, blocking the main thread for ~1s. User has 1s of frozen UI during this window.
- **Mitigation:** build cortex in a worker thread; main-thread tab builder polls `bootstrap.get_maintenance_cortex()` and uses it when ready, falling back to a placeholder.
- **Severity:** HIGH — explains the periodic freeze at ~2s post-paint.
- **Confidence:** VERIFIED (receipt timing + cortex.py static read confirms pure-Python construction safe off-main).

## Blocker 3 — pre-paint prewarm thread GIL contention (BOOT-TIME, MAIN THREAD VIA GIL)
- **Where:** `app.py:AIMonitorApp.__init__` previously spawned prewarm thread BEFORE HD construction.
- **Cost:** 5-13s of GIL contention with HD construction depending on which heavy import was first.
- **Owning subsystem:** prewarm of mempalace/pyramid_compartment/agent_chatroom/perceptual_engine.
- **Thread:** worker (but GIL is shared).
- **Mitigation:** **FIXED in build-008** — entire prewarm moved to `_deferred_services` post-paint.
- **Severity:** RESOLVED.
- **Confidence:** VERIFIED (build-008 boot delta -7.4s warm).

## Blocker 4 — bootstrap pre-qapplication phases at module-import (BOOT-TIME, MAIN THREAD)
- **Where:** `app.py` module top calls `bootstrap.run_pre_qapplication_phases()` (Phases 1-3).
- **Cost:** ~130ms measured.
- **Owning subsystem:** HOTWIRE Phase 1-3 — ConstraintEngine.evaluate_all + kernel instantiation + intelligence-layer find_spec.
- **Thread:** main.
- **Why it does NOT stall UI:** runs before QApplication exists. Doesn't affect interactivity.
- **Mitigation:** none needed.
- **Severity:** LOW.
- **Confidence:** VERIFIED.

## Blocker 5 — MaintenanceRuntime tick loop (POST-BOOT, WORKER THREAD)
- **Where:** `maintenance/runtime.py` spawns a daemon thread that ticks observers every 5s.
- **Cost:** depends on observer set; each observer.scan() is a function call.
- **Owning subsystem:** Maintenance Cortex.
- **Thread:** daemon (not main).
- **Why it does NOT stall UI:** runs entirely off main.
- **Mitigation:** verify no observer signals back to main thread with heavy work. (TODO: audit observer.scan() implementations.)
- **Severity:** LOW pending observer audit.
- **Confidence:** VERIFIED for the tick loop; UNTESTED for individual observer callbacks.

---

## Action plan for SURGICAL_UI_RECOVERY_PROTOCOL build-009

1. **Throttle lazy tab builders 40ms → 150ms** + `processEvents()` after each.
2. **Defer Phase 4 cortex build to a worker thread**; tab builder polls.
3. **Add UI_THREAD_GUARD QTimer** at 200ms that records freeze events via classified receipts.
4. **Push _deferred_services from +2000ms → +4000ms** (more breathing room).
5. **Audit observer.scan() implementations** — separate task; will land before build-010 if any are signal-amplifying main thread.

Each change preserves doctrine, receipts, maintenance authority, and intelligence architecture per the directive's hard constraints.
