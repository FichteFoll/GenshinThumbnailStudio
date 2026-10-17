# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the onedir, windowed bundle; run through packaging/build.py.
# Every path derives from SPECPATH (this file's directory), so the build works from any CWD.

from pathlib import Path

PACKAGING = Path(SPECPATH)
ROOT = PACKAGING.parent

# The app only uses QtCore, QtGui and QtWidgets, yet PySide6's hooks collect every plugin
# of each plugin directory they pick, together with the Qt libraries those plugins link against.
# These groups are dropped by file name, normalized so that one entry matches both
# `libQt6Quick.so.6` (Linux) and `Qt6Quick.dll` (Windows); nothing that is kept links against them.
UNUSED_QT_PREFIXES = (
    # The virtual keyboard input context is a QML on-screen keyboard for touch devices.
    # It is the only reason Qt Quick and QML are in the bundle at all.
    "qtvirtualkeyboardplugin",
    "qt6virtualkeyboard",
    "qt6quick",
    "qt6qml",
    # The PDF image format plugin lets QImage read PDF files, which the app never loads.
    "qpdf",
    "qt6pdf",
)


def is_unused_qt_file(dest_name):
    stem = Path(dest_name).name.lower().removeprefix("lib").split(".", 1)[0]
    return stem.startswith(UNUSED_QT_PREFIXES)


a = Analysis(
    [str(PACKAGING / "launch.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf"],
    noarchive=False,
    optimize=0,
)
a.binaries = [entry for entry in a.binaries if not is_unused_qt_file(entry[0])]
a.datas = [entry for entry in a.datas if not is_unused_qt_file(entry[0])]

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
