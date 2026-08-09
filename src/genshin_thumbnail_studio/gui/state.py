"""The editor state the Qt-free GUI collaborators read through.

`MainWindow` satisfies this Protocol structurally; nothing has to declare it.

The attribute types deliberately match `MainWindow`'s own annotations, because a
Protocol's mutable attributes are invariant: declaring `Mapping[str, Asset]`
here would reject the window's `dict[str, Asset]`.

Every collaborator (`PlacementController`, `PresetStore`, `AssetLoader`,
`HistoryController`, `TeamFieldsController`, `RenderPipeline`, `ProjectFiles`
and `ProfileLoader`) reads these attributes through the Protocol on *every* call
instead of capturing them at construction time, because `_mode_changed`,
`ProjectFiles.open`, `load_profile` and `member_changed` all replace `project`,
`builds` or `assets` wholesale. A captured `assets` would silently fall back to
`STANDARD_ART_SIZE` and compute the wrong offset bounds.
"""

from __future__ import annotations

from typing import Protocol

from ..models import Asset, Build, Project


class EditorState(Protocol):
    project: Project
    builds: dict[str, Build]
    assets: dict[str, Asset]
