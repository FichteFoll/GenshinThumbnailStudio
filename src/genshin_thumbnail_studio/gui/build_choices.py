"""Which of a character's builds a team slot is framed with.

Qt-free: it reads the editor state through `EditorState` on every call, see
`state.py` for why.

`Placement.build` is the single source of truth for which art a slot uses. The
renderer receives only a `Project` and the `Asset` dict, never the editor's
`builds` map, so it cannot resolve a live build from a bare character name; it
reads `Placement.asset_key` and nothing else. `resolve_build()` is therefore
called wherever a slot's character changes or a profile arrives, so that the
snapshot is on the placement before anything renders.
"""

from __future__ import annotations

from ..models import Build, Placement
from .state import EditorState


def selected_build(state: EditorState, member: Placement) -> Build | None:
    """The build the slot is framed with: the project's snapshot when it has
    one, otherwise the character's live build from the loaded profile."""
    if member.build is not None:
        return member.build
    # The profile lists the live build first, so the first entry is the default.
    profile_builds = state.builds.get(member.name.casefold(), [])
    return profile_builds[0] if profile_builds else None


def resolve_build(state: EditorState, member: Placement) -> Build | None:
    """`selected_build()`, written back onto the placement.

    A member whose character is not in the loaded profile keeps `build = None`
    and renders as a placeholder.
    """
    member.build = selected_build(state, member)
    return member.build
