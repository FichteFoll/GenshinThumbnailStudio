# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the onedir, windowed bundle; run through packaging/build.py.
# Every path derives from SPECPATH (this file's directory), so the build works from any CWD.

from pathlib import Path

PACKAGING = Path(SPECPATH)
ROOT = PACKAGING.parent

a = Analysis(
    [str(PACKAGING / "launch.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GenshinThumbnailStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GenshinThumbnailStudio",
)
