"""Plain dataclasses for a build, a downloaded asset, a placement and a project.

No dependency on the rest of the package or on Qt, so every other module can
import these without pulling in the network or GUI stack.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

Mode = Literal["abyss", "stygian"]

TEAM_COLORS = [
    ["#ff7b66", "#78d7ff", "#d7c7ff", "#8de2d0"],
    ["#6cc6ff", "#f0b07a", "#ff7382", "#ff726d"],
    ["#1fc7a8", "#83caff", "#ffc95d", "#ff726d"],
]

# The starting zoom per mode, read by both Project.blank() and the GUI's
# Reset button so the two cannot drift apart.
DEFAULT_ZOOM: dict[Mode, float] = {"abyss": 1.0, "stygian": 1.18}

# The name of the build taken from the player's current showcase, as opposed to
# one of the builds they saved on Enka.
LIVE_BUILD_NAME = "Live"

_UNSAFE_NAME_RUN = re.compile(r"[^A-Za-z0-9._-]+")
_CACHED_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def _cached_path(root: Path, kind: str, name: str, url: str) -> Path:
    """Where a downloaded file for `name` at `url` belongs under `root`.

    The scheme is `root/kind/{safe name}-{sha256(url)[:16]}{extension}` and is
    deliberately unchanged from the one the downloader used to compute for
    itself: changing it would orphan every user's cache and cost a full
    re-download for no gain. The character name is there for legibility only;
    it is the digest of the URL that keeps two builds of one character apart,
    which is exactly the identity the renderer needs.

    Pure: it creates no directories, so a caller that only asks whether a file
    exists leaves nothing behind.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    extension = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if extension not in _CACHED_EXTENSIONS:
        extension = ".png"
    safe = _UNSAFE_NAME_RUN.sub("_", name).strip("._") or "asset"
    return root / kind / f"{safe}-{digest}{extension}"


@dataclass
class Build:
    name: str
    constellation: int
    refinement: int
    weapon_name: str
    costume_id: str | None
    art_url: str
    weapon_url: str
    build_name: str = LIVE_BUILD_NAME
    build_id: str = ""
    element: str | None = None
    rarity: int | None = None
    weapon_rarity: int | None = None

    @property
    def key(self) -> str:
        """Identify character *and* build, the key of the downloaded-art dict.

        Two slots holding different builds of one character must not share a
        weapon icon or a skin, which a key of the character name alone would
        force them to.
        """
        return f"{self.name.casefold()}|{self.build_name.casefold()}"

    def art_path(self, root: Path) -> Path:
        """This build's character art inside the cache rooted at `root`."""
        return _cached_path(root, "characters", self.name, self.art_url)

    def weapon_path(self, root: Path) -> Path:
        """This build's weapon icon inside the cache rooted at `root`."""
        return _cached_path(root, "weapons", self.name, self.weapon_url)

    def details(self) -> tuple[str | None, str, int, int]:
        """The user-visible part of a build, which a project's snapshot is
        compared against the live build by."""
        return (self.costume_id, self.weapon_name, self.constellation, self.refinement)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Build:
        """Read the known keys, ignoring unknown ones, so that a build written
        by an older version loads with defaults instead of raising."""
        known = {field_.name for field_ in fields(cls)}
        return cls(**{key: item for key, item in value.items() if key in known})


@dataclass
class Profile:
    """Everything one fetch from Enka yielded, keyed by casefolded character name.

    It lives here rather than in the `enka` package because `storage` caches it
    on disk and must not import the network layer to do so.
    """

    identifier: str
    uid: str
    username: str
    builds: dict[str, list[Build]]
    fetched_at: datetime


@dataclass
class Asset:
    build: Build
    art_path: Path
    weapon_path: Path


@dataclass
class Placement:
    """One character's framing inside its panel.

    `offset_x`/`offset_y` are signed fractions of the panel size, measured from
    the centered position: positive values move the portrait right/down.
    `flip` mirrors the character art horizontally.
    `build` is the snapshot of the build the character was framed with, so that
    the framing survives the profile changing on Enka.
    """

    name: str = ""
    offset_x: float = 0.0
    offset_y: float = -0.02
    zoom: float = 1.0
    color: str = "#78d7ff"
    flip: bool = False
    build: Build | None = None

    @property
    def asset_key(self) -> str:
        """The key this slot's art is stored under, or `""` while unresolved.

        The renderer receives only a `Project` and the `Asset` dict, never the
        editor's build map, so the key has to travel on the placement itself.
        An empty key matches no asset, which is the right outcome for a slot
        whose build is not resolved yet.
        """
        return self.build.key if self.build else ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Placement:
        """Read the known keys, ignoring unknown ones, so that a legacy payload
        loads with default framing instead of raising."""
        defaults = cls()
        raw_build = value.get("build")
        return cls(
            name=str(value.get("name", defaults.name)),
            offset_x=float(value.get("offset_x", defaults.offset_x)),
            offset_y=float(value.get("offset_y", defaults.offset_y)),
            zoom=float(value.get("zoom", defaults.zoom)),
            color=str(value.get("color", defaults.color)),
            flip=bool(value.get("flip", defaults.flip)),
            build=Build.from_dict(cast("dict[str, Any]", raw_build)) if isinstance(raw_build, dict) else None,
        )


@dataclass
class Project:
    mode: Mode = "abyss"
    uid: str = ""
    profile_name: str = ""
    output_name: str = "genshin_thumbnail"
    output_height: int = 1080
    teams: list[list[Placement]] = field(default_factory=list)
    active_team: int = 0

    @property
    def output_size(self) -> tuple[int, int]:
        return (self.output_height * 16 // 9, self.output_height)

    @property
    def identifier(self) -> str:
        """What the profile is loaded by: the Enka username when there is one,
        the UID otherwise."""
        return self.profile_name or self.uid

    @classmethod
    def blank(cls, mode: Mode = "abyss", uid: str = "") -> Project:
        team_count = 2 if mode == "abyss" else 3
        zoom = DEFAULT_ZOOM[mode]
        teams: list[list[Placement]] = []
        for team_index in range(team_count):
            colors = TEAM_COLORS[team_index]
            teams.append(
                [Placement(zoom=zoom, color=colors[index]) for index in range(4)]
            )
        return cls(mode=mode, uid=uid, teams=teams)

    def ensure_shape(self) -> None:
        expected = 2 if self.mode == "abyss" else 3
        if len(self.teams) != expected or any(len(team) != 4 for team in self.teams):
            raise ValueError(f"{self.mode} projects require {expected} teams with four members each.")
        self.active_team = max(0, min(self.active_team, expected - 1))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 4,
            "mode": self.mode,
            "uid": self.uid,
            "profileName": self.profile_name,
            "outputName": self.output_name,
            "outputHeight": self.output_height,
            "activeTeam": self.active_team,
            "teams": [[asdict(member) for member in team] for team in self.teams],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Project:
        raw_mode = str(value.get("mode", "abyss")).casefold()
        mode: Mode
        if raw_mode == "abyss":
            mode = "abyss"
        elif raw_mode == "stygian":
            mode = "stygian"
        else:
            raise ValueError("Project mode must be abyss or stygian.")
        schema_version = int(value.get("schemaVersion", 1))
        # Version 1 files predate the setting and were rendered at the
        # then-hardcoded 720p, so keep their output size unchanged.
        output_height = 720 if schema_version <= 1 else int(value.get("outputHeight", 1080))
        project = cls(
            mode=mode,
            uid=str(value.get("uid", "")),
            profile_name=str(value.get("profileName", "")),
            output_name=str(value.get("outputName", "genshin_thumbnail")),
            output_height=output_height,
            active_team=int(value.get("activeTeam", 0)),
            teams=[
                [Placement.from_dict(member) for member in team]
                for team in value.get("teams", [])
            ],
        )
        project.ensure_shape()
        return project
