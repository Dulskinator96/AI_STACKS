# -*- mode: python ; coding: utf-8 -*-
# Single-file EXE (double-click to run). Build from project root: build_app.bat

import os

from PyInstaller.utils.hooks import collect_all

_root = os.getcwd()
_rthook = os.path.join(_root, "rthook_ai_monitor.py")
_ic_assets = os.path.join(_root, "assets", "app_icon.ico")
_ic_root = os.path.join(_root, "app_icon.ico")
_icon_arg = _ic_assets if os.path.isfile(_ic_assets) else (_ic_root if os.path.isfile(_ic_root) else None)

qdatas, qbins, qhidden = collect_all("PyQt6")

datas = list(qdatas)
binaries = list(qbins)
hiddenimports = list(qhidden)

for fname in ("pipeline.py", "note_builder.py", "perception.py"):
    p = os.path.join(_root, fname)
    if os.path.isfile(p):
        datas.append((p, "."))

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
    name="AIMonitor",
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
