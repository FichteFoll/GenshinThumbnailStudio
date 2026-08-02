param(
    [string]$Python = "py"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path ([System.IO.Path]::GetTempPath()) "gts-build-venv"
$Release = Join-Path $Root "release"

if (-not (Test-Path $Venv)) {
    & $Python -m venv $Venv
}

$Py = Join-Path $Venv "Scripts\python.exe"
& $Py -m pip install --upgrade pip
& $Py -m pip install -r (Join-Path $Root "requirements-dev.txt")
& $Py -m pip install -e $Root
& $Py -m pytest $Root

Remove-Item -Recurse -Force (Join-Path $Root "build") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $Root "dist") -ErrorAction SilentlyContinue
& $Py -m PyInstaller `
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
