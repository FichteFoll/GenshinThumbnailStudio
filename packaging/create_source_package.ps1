param(
    [string]$Output
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Output) {
    $Output = Join-Path $Root "release\GenshinThumbnailStudio-source.zip"
}
$Output = [System.IO.Path]::GetFullPath($Output)
$Stage = Join-Path ([System.IO.Path]::GetTempPath()) "GenshinThumbnailStudio-source-$PID"

function Copy-SourceFile {
    param([System.IO.FileInfo]$File)

    $RootPrefix = $Root.TrimEnd("\", "/") + [System.IO.Path]::DirectorySeparatorChar
    if (-not $File.FullName.StartsWith($RootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Source file is outside the project root: $($File.FullName)"
    }
    $Relative = $File.FullName.Substring($RootPrefix.Length)
    $Destination = Join-Path $Stage $Relative
    New-Item -ItemType Directory -Force (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -LiteralPath $File.FullName -Destination $Destination
}

try {
    New-Item -ItemType Directory -Force $Stage | Out-Null

    Get-ChildItem (Join-Path $Root "src") -Recurse -File -Filter "*.py" | ForEach-Object { Copy-SourceFile $_ }
    Get-ChildItem (Join-Path $Root "tests") -File -Filter "*.py" | ForEach-Object { Copy-SourceFile $_ }
    Get-ChildItem (Join-Path $Root "packaging") -File | ForEach-Object { Copy-SourceFile $_ }
    Get-ChildItem (Join-Path $Root ".github") -Recurse -File | ForEach-Object { Copy-SourceFile $_ }

    foreach ($Name in @(
        "launch.py",
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "README.md",
        ".gitignore"
    )) {
        Copy-SourceFile (Get-Item (Join-Path $Root $Name))
    }

    New-Item -ItemType Directory -Force (Split-Path -Parent $Output) | Out-Null
    Remove-Item -LiteralPath $Output -Force -ErrorAction SilentlyContinue
    Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Output -CompressionLevel Optimal
    Write-Host "Created $Output"
}
finally {
    $TempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    $ResolvedStage = [System.IO.Path]::GetFullPath($Stage)
    if ($ResolvedStage.StartsWith($TempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $ResolvedStage -Recurse -Force -ErrorAction SilentlyContinue
    }
}
