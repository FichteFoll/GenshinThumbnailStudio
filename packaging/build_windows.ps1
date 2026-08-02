$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Release = Join-Path $Root "release"

uv sync --directory $Root --extra dev
uv run --directory $Root pytest $Root

Remove-Item -Recurse -Force (Join-Path $Root "build") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $Root "dist") -ErrorAction SilentlyContinue
uv run --directory $Root pyinstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name GenshinThumbnailStudio `
    --paths (Join-Path $Root "src") `
    (Join-Path $Root "launch.py")

New-Item -ItemType Directory -Force $Release | Out-Null
$Archive = Join-Path $Release "GenshinThumbnailStudio-windows-x64.zip"
Remove-Item -Force $Archive -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $Root "dist\GenshinThumbnailStudio\*") -DestinationPath $Archive
Write-Host "Created $Archive"
