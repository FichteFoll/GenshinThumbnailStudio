# Genshin Thumbnail Studio

Standalone desktop application for creating Genshin Impact team thumbnails.

## Features

- Loads character builds from Enka Network,
  by Genshin UID or by Enka profile username.
- Lets the user pick, per character, which of that profile's saved builds to use,
  the live showcase build being the default.
  The live build shows up for a username load as well as a UID load,
  and a build restored from the project file is marked `(project)` in the menu
  wherever it differs from what the profile currently offers.
- Remembers each character's build details
  (skin, weapon, constellation, refinement) in the project file,
  so a project still opens correctly after the Enka profile has changed.
- Lets the user edit a character's build directly, through an "Edit ..." item
  at the bottom of that slot's build menu.
  The popup it opens configures the skin, the weapon,
  the constellation count and the weapon refinement count,
  plus the element for the Traveler, whose element the source data cannot pin down.
  Accepting it frames that slot with a "Custom" build,
  saved in the project file the way any other build it is framed with is,
  while the build it was based on stays available in the menu.
  The skin and weapon choices offered come from Enka's own costume
  and weapon data, not from the profile.
- Supports one two-team Spiral Abyss thumbnail
  or three four-character Stygian Onslaught thumbnails.
- Character art, skins and weapon icons come from Enka's own asset URLs.
- Downloads original character artwork and weapon icons into a local cache.
- Shows C/R labels and weapon icons without additional thumbnail text.
- Renders the preview continuously,
  showing placeholder panels for slots that have no character yet,
  and swapping in portraits as soon as their art has finished downloading in the background.
- Lets users select and drag every character that has art directly in the preview.
  The mouse wheel, the X/Y/zoom sliders,
  and a "Flip" toggle that mirrors a character horizontally,
  so one facing out of the thumbnail can face into it,
  all apply to those slots as well.
- Saves reusable placement presets and JSON project files.
  A "New project" button, also bound to `Ctrl+N`,
  resets to a blank project while keeping the profile field.
  Projects are opened with `Ctrl+O`
  and saved with `Ctrl+S`,
  which overwrites the project's own file once it has one
  and otherwise asks where to put it,
  remembering the answer.
  `Ctrl+Shift+S` saves under a new name,
  as does the dropdown on the save button,
  which appears once the project has a file.
  The profile field itself is restored from the last session,
  so it is ready to use as soon as the application opens.
- Exports supersampled PNG files at the configured resolution,
  on `Ctrl+E` or the export button.

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

Each script runs the tests and creates a platform-specific package in `release/`.
The Windows and Linux packages are separate
because native Qt binaries cannot be shared across operating systems.
End users do not need Python, Node.js, or Codex.

## Data source

Enka's showcase is what the game last published,
so a profile is refreshed by opening the character showcase in game,
rather than by any control in this application.
Saved builds come from a verified, public Enka account
and are reached by entering that account's username.
Enka is an external service,
so its rate limits or changes may require a future application update.
