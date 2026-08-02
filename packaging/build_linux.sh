#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE="$ROOT/release"

uv sync --directory "$ROOT" --extra dev
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox uv run --directory "$ROOT" pytest

rm -rf "$ROOT/build" "$ROOT/dist"
uv run --directory "$ROOT" pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name GenshinThumbnailStudio \
  --paths "$ROOT/src" \
  "$ROOT/launch.py"

mkdir -p "$RELEASE"
tar -C "$ROOT/dist" -czf "$RELEASE/GenshinThumbnailStudio-linux-x64.tar.gz" GenshinThumbnailStudio
printf 'Created %s\n' "$RELEASE/GenshinThumbnailStudio-linux-x64.tar.gz"
