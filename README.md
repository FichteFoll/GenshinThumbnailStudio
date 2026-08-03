# Genshin Thumbnail Studio

Standalone desktop application for creating the established 1280x720 Genshin team thumbnails without Codex or another AI tool.

## Features

- Loads public character builds from Akasha using a Genshin UID.
- Checks whether the Akasha profile was refreshed within the last hour.
- Supports one two-team Spiral Abyss thumbnail or three four-character Stygian Onslaught thumbnails.
- Uses the exact Enka asset stem and costume ID returned by Akasha, including equipped skins.
- Downloads original character artwork and weapon icons into a local cache.
- Shows C/R labels and weapon icons without additional thumbnail text.
- Lets users select and drag every character directly in the preview. The mouse wheel and X/Y/zoom sliders provide fine control.
- Saves reusable placement presets and JSON project files.
- Exports supersampled PNG files at 1280x720.

## Run from source

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
uv run genshin-thumbnail-studio
```

`uv run` creates the virtual environment and installs dependencies automatically on first use.
For development, install the `dev` extra as well:

```bash
uv sync --extra dev
uv run pytest
```

## Build standalone packages

- Windows: run `packaging/build_windows.ps1`
- Linux: run `packaging/build_linux.sh`
- Clean source ZIP: run `powershell -ExecutionPolicy Bypass -File packaging/create_source_package.ps1`

Each script runs the tests and creates a platform-specific package in `release/`. The Windows and Linux packages are separate because native Qt binaries cannot be shared across operating systems. End users do not need Python, Node.js, Codex, or a separate Chromium installation.

## Akasha refresh behavior

If the profile is older than one hour, the application offers to press Akasha's public `Refresh builds` control automatically. It can also continue with the stale profile or cancel. Akasha and Enka are external services, so changes to their website or rate limits may require a future application update.
