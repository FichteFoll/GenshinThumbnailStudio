"""The editor state the Qt-free GUI collaborators read through.

`MainWindow` satisfies this Protocol structurally; nothing has to declare it.

The attribute types deliberately match `MainWindow`'s own annotations, because a
Protocol's mutable attributes are invariant: declaring
`Mapping[str, list[Build]]` here would reject the window's
`dict[str, list[Build]]`.

Every collaborator (`PlacementController`, `PresetStore`, `AssetLoader`,
`HistoryController`, `TeamFieldsController`, `RenderPipeline`, `ProjectFiles`
and `ProfileLoader`) reads these attributes through the Protocol on *every* call
instead of capturing them at construction time, because `_mode_changed`,
`ProjectFiles.open`, `load_profile` and `member_changed` all replace `project`
or `builds` wholesale. A captured `builds` would resolve a slot's build against
a profile that is no longer loaded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..models import Build, Project


class EditorState(Protocol):
    project: Project
    # One list per casefolded character name, the live build first. This is the
    # profile's own offering; which of them a slot is framed with is
    # `Placement.build`, and that build resolves its own files under `art_root`.
    builds: dict[str, list[Build]]
    # The cache root a build resolves its own art and weapon icon under, which
    # is all the renderer needs beside the project.
    art_root: Path
