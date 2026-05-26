# -*- mode: python ; coding: utf-8 -*-
# Single-file EXE (double-click to run). Build from project root: build_app.bat

import os

from PyInstaller.utils.hooks import collect_all

_root = os.getcwd()
_rthook = os.path.join(_root, "rthook_ai_monitor.py")
_ic_stratum_assets = os.path.join(_root, "assets", "stratum_icon.ico")
_ic_stratum_root   = os.path.join(_root, "stratum_icon.ico")
_ic_legacy_assets  = os.path.join(_root, "assets", "app_icon.ico")
_ic_legacy_root    = os.path.join(_root, "app_icon.ico")
# Prefer stratum_icon.ico (rename to DBOMBLOCAL — 2026-05-17). Fall back to
# the legacy app_icon.ico if stratum_icon.ico is missing from this checkout.
_icon_arg = next(
    (p for p in (_ic_stratum_assets, _ic_stratum_root,
                  _ic_legacy_assets, _ic_legacy_root)
     if os.path.isfile(p)),
    None,
)

qdatas, qbins, qhidden = collect_all("PyQt6")

datas = list(qdatas)
binaries = list(qbins)
hiddenimports = list(qhidden)

for fname in ("pipeline.py", "note_builder.py", "perception.py",
              "mempalace_bridge.py"):
    p = os.path.join(_root, fname)
    if os.path.isfile(p):
        datas.append((p, "."))

# Stage-2: core/ package — Service contract + ServiceRegistry + Operational Stability layer.
_core_dir = os.path.join(_root, "core")
if os.path.isdir(_core_dir):
    for fname in os.listdir(_core_dir):
        if not fname.endswith(".py"):
            continue
        p = os.path.join(_core_dir, fname)
        if os.path.isfile(p):
            datas.append((p, "core"))

# Stage-2b: kernel/ package — HOTWIRE Phase 2 subsystems (Constitution,
# EventBus, AuthorityLayer, MemoryCore=TruthEngine, ExecutionDAG=RuntimeGraph,
# ConstraintEngine, ConvergenceEngine). Lives one directory ABOVE the project
# root (AI_STACK/kernel/) — copy it into the frozen exe as a top-level pkg.
_kernel_dir = os.path.join(os.path.dirname(_root), "kernel")
if os.path.isdir(_kernel_dir):
    for fname in os.listdir(_kernel_dir):
        if not fname.endswith(".py"):
            continue
        p = os.path.join(_kernel_dir, fname)
        if os.path.isfile(p):
            datas.append((p, "kernel"))

# Stage-3: truth/ package — Execution Receipt envelope + failure classifier.
_truth_dir = os.path.join(_root, "truth")
if os.path.isdir(_truth_dir):
    for fname in os.listdir(_truth_dir):
        if not fname.endswith(".py"):
            continue
        p = os.path.join(_truth_dir, fname)
        if os.path.isfile(p):
            datas.append((p, "truth"))

# Stage-4: maintenance/ package — Cortex + observers + tests.
_maint_dir = os.path.join(_root, "maintenance")
if os.path.isdir(_maint_dir):
    for sub_rel in ("",  "observers", "schema", "tests"):
        sub = os.path.join(_maint_dir, sub_rel) if sub_rel else _maint_dir
        if not os.path.isdir(sub):
            continue
        target_subdir = "maintenance" + ("/" + sub_rel if sub_rel else "")
        for fname in os.listdir(sub):
            if not fname.endswith((".py", ".json")):
                continue
            p = os.path.join(sub, fname)
            if os.path.isfile(p):
                datas.append((p, target_subdir.replace("/", os.sep)))

# Stage-4b: runtime/ package — BUILD-018 Runtime Separation Substrate.
# RuntimeSingletonRegistry, RuntimeServiceLocator, RuntimeViewModel,
# WorkspaceCapabilityContract, DynamicWorkspaceSpawner, DeferredWorkspaceLoader.
_runtime_dir = os.path.join(_root, "runtime")
if os.path.isdir(_runtime_dir):
    for fname in os.listdir(_runtime_dir):
        if not fname.endswith(".py"):
            continue
        p = os.path.join(_runtime_dir, fname)
        if os.path.isfile(p):
            datas.append((p, "runtime"))

# Stage-4c: engine/ package — BUILD-019/020/021/022 organism + production + workers.
_engine_dir = os.path.join(_root, "engine")
if os.path.isdir(_engine_dir):
    for fname in os.listdir(_engine_dir):
        if not fname.endswith(".py"):
            continue
        p = os.path.join(_engine_dir, fname)
        if os.path.isfile(p):
            datas.append((p, "engine"))

# Stage-4c2: engine/workers/ package — BUILD-022 hard worker substrate.
_workers_dir = os.path.join(_root, "engine", "workers")
if os.path.isdir(_workers_dir):
    for fname in os.listdir(_workers_dir):
        if not fname.endswith(".py"):
            continue
        p = os.path.join(_workers_dir, fname)
        if os.path.isfile(p):
            datas.append((p, os.path.join("engine", "workers")))

# Stage-4c3: engine/creative_composition/ — BUILD-026.
_compose_dir = os.path.join(_root, "engine", "creative_composition")
if os.path.isdir(_compose_dir):
    for fname in os.listdir(_compose_dir):
        if fname.endswith(".py"):
            p = os.path.join(_compose_dir, fname)
            if os.path.isfile(p):
                datas.append((p, os.path.join("engine", "creative_composition")))

# Stage-4c4: engine/calibration/ — BUILD-026.
_calib_dir = os.path.join(_root, "engine", "calibration")
if os.path.isdir(_calib_dir):
    for fname in os.listdir(_calib_dir):
        if fname.endswith(".py"):
            p = os.path.join(_calib_dir, fname)
            if os.path.isfile(p):
                datas.append((p, os.path.join("engine", "calibration")))

# Stage-4c5..9: BUILD-027A Creative Intelligence packages.
# Stage-4c10:  BUILD-029 closed_loop.
for _sub in ("aesthetic_intelligence", "refinement", "coherence",
              "semantic_memory", "cinematic_director", "oracle",
              "closed_loop"):
    _d = os.path.join(_root, "engine", _sub)
    if os.path.isdir(_d):
        for fname in os.listdir(_d):
            if fname.endswith(".py"):
                p = os.path.join(_d, fname)
                if os.path.isfile(p):
                    datas.append((p, os.path.join("engine", _sub)))

# Stage-4d: realms/ package — BUILD-021 ASCENSION PHASE production pipelines.
# image_generation / audio_engine / video_production / game_creation / simulation
_realms_dir = os.path.join(_root, "realms")
if os.path.isdir(_realms_dir):
    for sub in os.listdir(_realms_dir):
        sub_path = os.path.join(_realms_dir, sub)
        if os.path.isfile(sub_path) and sub.endswith(".py"):
            datas.append((sub_path, "realms"))
        elif os.path.isdir(sub_path) and not sub.startswith(("_", ".")):
            target = "realms/" + sub
            for f in os.listdir(sub_path):
                fp = os.path.join(sub_path, f)
                if os.path.isfile(fp) and f.endswith(".py"):
                    datas.append((fp, target.replace("/", os.sep)))

# Stage-5: ui/ package — extracted Qt view classes (Phase A decomp + Maintenance panel).
# Includes subdirectories (pyramid_chamber, etc).
_ui_dir = os.path.join(_root, "ui")
if os.path.isdir(_ui_dir):
    for fname in os.listdir(_ui_dir):
        full = os.path.join(_ui_dir, fname)
        if os.path.isfile(full) and fname.endswith(".py"):
            datas.append((full, "ui"))
        elif os.path.isdir(full) and not fname.startswith(("_", ".")):
            target = "ui/" + fname
            for sub in os.listdir(full):
                if sub.endswith(".py"):
                    sp = os.path.join(full, sub)
                    if os.path.isfile(sp):
                        datas.append((sp, target.replace("/", os.sep)))

# Stage-6: omega/ package — TASKMASTER Ω execution/orchestration/verification
# layer (BUILD-034). Includes subpackages tracing/, rooms/, evolution/.
_omega_dir = os.path.join(_root, "omega")
if os.path.isdir(_omega_dir):
    for sub_rel in ("", "tracing", "rooms", "evolution"):
        sub = os.path.join(_omega_dir, sub_rel) if sub_rel else _omega_dir
        if not os.path.isdir(sub):
            continue
        target_subdir = "omega" + (os.sep + sub_rel if sub_rel else "")
        for fname in os.listdir(sub):
            if fname.endswith(".py"):
                p = os.path.join(sub, fname)
                if os.path.isfile(p):
                    datas.append((p, target_subdir))

# Stage-7: service/ package — FastAPI transport layer (hosted in-process by
# omega.embedded_server inside the frozen runtime).
_service_dir = os.path.join(_root, "service")
if os.path.isdir(_service_dir):
    for fname in os.listdir(_service_dir):
        if fname.endswith(".py"):
            p = os.path.join(_service_dir, fname)
            if os.path.isfile(p):
                datas.append((p, "service"))

# Stage-7b: FastAPI + uvicorn + starlette + pydantic stack. Uvicorn imports its
# protocol/loop/lifespan impls dynamically by string — collect_all + explicit
# hiddenimports are required for the in-process server to start when frozen.
for _web_pkg in ("fastapi", "starlette", "uvicorn", "pydantic", "pydantic_core",
                 "anyio", "sniffio", "h11", "click", "annotated_types"):
    try:
        _d, _b, _h = collect_all(_web_pkg)
        datas       += list(_d)
        binaries    += list(_b)
        hiddenimports = list(hiddenimports) + list(_h)
    except Exception:
        pass

# MemPalace is a heavy external package — collect it fully so the
# searcher/miner submodules ride along in the frozen exe.
try:
    mp_datas, mp_bins, mp_hidden = collect_all("mempalace")
    datas       += list(mp_datas)
    binaries    += list(mp_bins)
    hiddenimports = list(hiddenimports) + list(mp_hidden)
except Exception:
    pass

# ChromaDB (mempalace's backend) loads several submodules dynamically via
# importlib — PyInstaller can't discover those statically. collect_all is
# required, AND explicit hiddenimports for the dynamic ones observed failing
# in build #12 logs (chromadb.telemetry.product.posthog, chromadb.api.rust).
try:
    cd_datas, cd_bins, cd_hidden = collect_all("chromadb")
    datas       += list(cd_datas)
    binaries    += list(cd_bins)
    hiddenimports = list(hiddenimports) + list(cd_hidden) + [
        "chromadb.telemetry.product.posthog",
        "chromadb.api.rust",
        "chromadb.api.fastapi",
        "chromadb.api.segment",
        "chromadb.db.impl.sqlite",
        "chromadb.segment.impl.metadata.sqlite",
        "chromadb.segment.impl.vector.local_hnsw",
        "chromadb.segment.impl.vector.local_persistent_hnsw",
        "posthog",
        "posthog.client",
        "opentelemetry",
        "opentelemetry.sdk",
        "opentelemetry.sdk.trace",
    ]
except Exception:
    pass

# Sentence-transformers / onnxruntime are mempalace's default embedding stack.
for _opt_pkg in ("sentence_transformers", "onnxruntime", "tokenizers", "huggingface_hub"):
    try:
        _d, _b, _h = collect_all(_opt_pkg)
        datas       += list(_d)
        binaries    += list(_b)
        hiddenimports = list(hiddenimports) + list(_h)
    except Exception:
        pass

if _icon_arg:
    datas.append((_icon_arg, "."))

block_cipher = None

a = Analysis(
    ["app.py"],
    pathex=[_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports
    + [
        "comtypes",
        "comtypes.client",
        "comtypes.stream",
        "uiautomation",
        "requests",
        "urllib3",
        "certifi",
        "mempalace",
        "mempalace.miner",
        "mempalace.searcher",
        "mempalace_bridge",
        "core",
        "core.services",
        "core.profiler",
        "core.state_manager",
        "core.lifecycle",
        "core.bootstrap",
        "core._won_shims",
        "core.memory",
        "core.brain",
        "core.obsidian",
        "core.project_tracker",
        "kernel",
        "kernel.constitution",
        "kernel.event_bus",
        "kernel.authority",
        "kernel.memory",
        "kernel.dag",
        "kernel.constraint_engine",
        "kernel.convergence_engine",
        "kernel.intent_orchestrator",
        "truth",
        "truth.receipt_engine",
        "truth.failure_classifier",
        "maintenance",
        "maintenance.classifier",
        "maintenance.receipts",
        "maintenance.repair_coordinator",
        "maintenance.runtime",
        "maintenance.calibration",
        "maintenance.stability_engine",
        "maintenance.repair_history",
        "maintenance.cortex",
        "maintenance.ps_advisor",
        "maintenance.observers",
        "maintenance.observers.base",
        "maintenance.observers.runtime_health",
        "maintenance.observers.ui_state",
        "maintenance.observers.queue_watch",
        "maintenance.observers.drift_monitor",
        "maintenance.observers.stratum_health",
        "maintenance.observers.won_health",
        "maintenance.observers.execution_integrity",
        "maintenance.observers.process_watch",
        "maintenance.observers.resource_pressure",
        "maintenance.observers.memory_integrity",
        "maintenance.observers.telemetry_monitor",
        "ui",
        "ui.memory_agent",
        "ui.maintenance_panel",
        "ui.ops_dashboard",
        "ui.perception_panel",
        "ui.knowledge_panel",
        "ui.pyramid_chamber",
        "ui.pyramid_chamber.chamber",
        "ui.workspace_factory",
        "ui.realm_session_tab",
        "ui.pyramid_chamber.reactive_presence",
        "ui.pyramid_chamber.reactive_presence_v2",
        "runtime",
        "runtime.singleton_registry",
        "runtime.service_locator",
        "runtime.view_model",
        "runtime.workspace_contract",
        "runtime.workspace_spawner",
        "runtime.deferred_loader",
        "engine",
        "engine.pyramid_engine",
        "engine.intent_cortex",
        "engine.personality_model",
        "engine.creative_expansion",
        "engine.execution_planner",
        "engine.realm_dispatcher",
        "engine.tool_router",
        "engine.reflection_engine",
        "engine.output_renderer",
        "engine.memory_context_bridge",
        # BUILD-020 FULL ORGANISM
        "engine.cognitive_core",
        "engine.tool_fabric",
        "engine.workspace_fabric",
        "engine.realm_orchestrator",
        "engine.media_generation_layer",
        "engine.simulation_engine",
        "engine.adaptive_learning",
        "engine.diagnostics_layer",
        "engine.personality_matrix",
        # BUILD-021 ASCENSION
        "engine.production_core",
        "engine.artifact_lineage",
        "engine.production_pipeline_engine",
        "engine.production_tool_fabric",
        "realms",
        "realms.image_generation",
        "realms.image_generation.pipeline",
        "realms.audio_engine",
        "realms.audio_engine.pipeline",
        "realms.video_production",
        "realms.video_production.pipeline",
        "realms.game_creation",
        "realms.game_creation.pipeline",
        "realms.simulation",
        "realms.simulation.pipeline",
        # BUILD-022 hard worker substrate
        "engine.workers",
        "engine.workers.base_worker",
        "engine.workers.image_worker",
        "engine.workers.video_worker",
        "engine.workers.audio_worker",
        "engine.workers.game_worker",
        "engine.workers.simulation_worker",
        "engine.workers.code_worker",
        "engine.workers.cast_worker",
        "engine.quality_gate",
        "engine.preview_registry",
        "engine.active_execution_substrate",
        # BUILD-023 STABILIZATION
        "engine.worker_router",
        "engine.artifact_validator",
        # BUILD-024 REACTIVE SURFACE
        "engine.live_stream",
        "ui.production_console.launch_surface",
        # BUILD-025 PRODUCTION GUARANTEE LAYER
        "engine.production_guarantee",
        # BUILD-026 CREATIVE COMPOSITION + CALIBRATION
        "engine.creative_composition",
        "engine.creative_composition.composition_engine",
        "engine.creative_composition.storyboard_planner",
        "engine.creative_composition.cinematic_language",
        "engine.creative_composition.aesthetic_director",
        "engine.creative_composition.refinement_director",
        "engine.creative_composition.export_mastering",
        "engine.backend_registry",
        "engine.system_truth_audit",
        "engine.master_validation",
        "engine.calibration",
        "engine.calibration.performance_calibrator",
        "engine.calibration.latency_calibrator",
        "engine.calibration.memory_calibrator",
        "engine.calibration.render_calibrator",
        "engine.calibration.artifact_consistency",
        # BUILD-027A CREATIVE INTELLIGENCE ASCENSION
        "engine.aesthetic_intelligence",
        "engine.aesthetic_intelligence.aesthetic_reasoner",
        "engine.aesthetic_intelligence.visual_harmony",
        "engine.aesthetic_intelligence.emotional_resonance",
        "engine.aesthetic_intelligence.cinematic_rhythm",
        "engine.refinement",
        "engine.refinement.critique_engine",
        "engine.refinement.iterative_refiner",
        "engine.refinement.comparative_selector",
        "engine.coherence",
        "engine.coherence.modality_synchronizer",
        "engine.semantic_memory",
        "engine.semantic_memory.motif_tracking",
        "engine.semantic_memory.successful_output_memory",
        "engine.semantic_memory.creative_identity",
        "engine.cinematic_director",
        "engine.cinematic_director.pacing_engine",
        "engine.cinematic_director.scene_flow",
        "engine.oracle",
        "engine.oracle.ambition_interpreter",
        "engine.oracle.production_advisor",
        # BUILD-028 CALIBRATION + COMPARATIVE INTELLIGENCE
        "engine.visual_harmony_pixel",
        "engine.preference_memory",
        "engine.unified_creative_profile",
        "engine.comparative_selector_v2",
        "engine.noncanonical_audit",
        "engine.calibration.calibration_console",
        # BUILD-029 CLOSED LOOP
        "engine.closed_loop",
        "engine.closed_loop.feedback_vector",
        "engine.closed_loop.candidate_generator",
        "engine.closed_loop.closed_loop_enforcer",
        "engine.closed_loop.loop_engine",
        "engine.closed_loop_tests",
        # BUILD-029A SYSTEM SYNOPSIS
        "engine.system_synopsis",
        # P0 REALITY-LOCK: boot self-check + MemPalace execution ledger
        "engine.boot_self_check",
        "engine.mem_palace",
        "engine.mem_palace.memory_store",
        "engine.mem_palace.boot_check",
        "ui.production_console",
        "ui.production_console.console",
        # BUILD-034 TASKMASTER Ω execution/orchestration layer
        "omega",
        "omega.paths",
        "omega.contracts",
        "omega.dag",
        "omega.orchestrator",
        "omega.agents",
        "omega.rooms",
        "omega.embedded_server",
        "omega.tracing",
        "omega.tracing.trace_contracts",
        "omega.tracing.trace_engine",
        "omega.tracing.trace_render",
        "omega.tracing.trace_indexer",
        "omega.tracing.anomaly_detector",
        "omega.evolution",
        "omega.evolution.runtime_inspector",
        "omega.evolution.dependency_health",
        "omega.evolution.self_diagnosis",
        "omega.evolution.repair_planner",
        "omega.evolution.patch_engine",
        "omega.evolution.optimization_cycles",
        # FastAPI transport + in-process uvicorn (dynamic string imports)
        "service",
        "service.api",
        "fastapi",
        "starlette",
        "pydantic",
        "pydantic_core",
        "anyio",
        "anyio._backends._asyncio",
        "sniffio",
        "h11",
        "click",
        "annotated_types",
        "uvicorn",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[_rthook] if os.path.isfile(_rthook) else [],
    # Build Acceleration Directive item #3 — exclude packages confirmed
    # unused by the operational code path. Each saves seconds of analysis
    # time per build. All verified by audit agent against warn log + grep
    # of all .py files.
    excludes=[
        "matplotlib",         # only transitive via tqdm.gui; never imported
        "scipy",              # not in dependency tree; never imported
        "pandas",             # only transitive via tqdm.std; never imported
        "torch",              # only transitive via onnxruntime/huggingface; never imported
        "torch_xla",          # only transitive via huggingface serialization
        "tensorflow",         # only transitive via onnxruntime transformers
        "IPython",            # only transitive via rich/tqdm/dotenv
        "jupyter",            # only transitive via ipywidgets
        "notebook",           # only transitive via ipywidgets
        "dask",               # only transitive via fsspec implementations
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="DBOMBLOCAL",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon_arg,
)
