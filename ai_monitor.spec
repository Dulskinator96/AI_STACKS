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
    for fname in ("__init__.py", "services.py",
                   "profiler.py", "state_manager.py", "lifecycle.py"):
        p = os.path.join(_core_dir, fname)
        if os.path.isfile(p):
            datas.append((p, "core"))

# Stage-3: truth/ package — Execution Receipt envelope.
_truth_dir = os.path.join(_root, "truth")
if os.path.isdir(_truth_dir):
    for fname in ("__init__.py", "receipt_engine.py"):
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

# Stage-5: ui/ package — extracted Qt view classes (Phase A decomp + Maintenance panel).
_ui_dir = os.path.join(_root, "ui")
if os.path.isdir(_ui_dir):
    for fname in os.listdir(_ui_dir):
        if not fname.endswith(".py"):
            continue
        p = os.path.join(_ui_dir, fname)
        if os.path.isfile(p):
            datas.append((p, "ui"))

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
        "truth",
        "truth.receipt_engine",
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
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[_rthook] if os.path.isfile(_rthook) else [],
    excludes=[],
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
