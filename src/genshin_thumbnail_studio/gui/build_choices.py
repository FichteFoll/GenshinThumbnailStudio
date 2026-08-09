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

from dataclasses import dataclass

from ..models import Build, Placement
from .state import EditorState


@dataclass(frozen=True)
class BuildChoice:
    """One entry of a character's build list, as the dropdown renders it."""

    label: str
    build: Build
    selected: bool


def build_choices(profile_builds: list[Build], stored: Build | None) -> list[BuildChoice]:
    """What a character's build list offers, and which entry is the current one.

    The profile's builds and the project's snapshot are merged by build name,
    which is also what `Build.key` identifies art by. A snapshot whose name the
    profile no longer offers is appended rather than dropped, and one whose
    details drifted away from the live build of the same name is offered beside
    it, so that neither the project's framing nor the current build is lost.
    """
    if stored is None:
        # The profile lists the live build first, so the first entry is the default.
        return [BuildChoice(build.build_name, build, index == 0) for index, build in enumerate(profile_builds)]

    choices: list[BuildChoice] = []
    matched = False
    for build in profile_builds:
        # Only the first build of the stored name is merged with the snapshot.
        # Build names are free text, so a profile can hold two of one name, and
        # merging each of them would mark several entries as the selected one.
        if matched or build.build_name.casefold() != stored.build_name.casefold():
            choices.append(BuildChoice(build.build_name, build, False))
            continue
        matched = True
        if build.details() == stored.details():
            choices.append(BuildChoice(build.build_name, build, True))
            continue
        choices.append(BuildChoice(f"{build.build_name} (project)", stored, True))
        choices.append(BuildChoice(f"{build.build_name} (live)", build, False))
    if not matched:
        choices.append(BuildChoice(stored.build_name, stored, True))
    return choices


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
