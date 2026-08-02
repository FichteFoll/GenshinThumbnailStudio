#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv-build"
RELEASE="$ROOT/release"

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$ROOT/requirements-dev.txt"
"$VENV/bin/python" -m pip install -e "$ROOT"
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox "$VENV/bin/python" -m pytest "$ROOT"

rm -rf "$ROOT/build" "$ROOT/dist"
"$VENV/bin/python" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name GenshinThumbnailStudio \
  --paths "$ROOT/src" \
  "$ROOT/launch.py"

mkdir -p "$RELEASE"
tar -C "$ROOT/dist" -czf "$RELEASE/GenshinThumbnailStudio-linux-x64.tar.gz" GenshinThumbnailStudio
printf 'Created %s\n' "$RELEASE/GenshinThumbnailStudio-linux-x64.tar.gz"
