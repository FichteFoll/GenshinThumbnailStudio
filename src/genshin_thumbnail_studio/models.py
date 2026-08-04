from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


Mode = Literal["abyss", "stygian"]

TEAM_COLORS = [
    ["#ff7b66", "#78d7ff", "#d7c7ff", "#8de2d0"],
    ["#6cc6ff", "#f0b07a", "#ff7382", "#ff726d"],
    ["#1fc7a8", "#83caff", "#ffc95d", "#ff726d"],
]

# The starting zoom per mode, read by both Project.blank() and the GUI's
# Reset button so the two cannot drift apart.
DEFAULT_ZOOM: dict[Mode, float] = {"abyss": 1.0, "stygian": 1.18}


@dataclass
class Build:
    name: str
    constellation: int
    refinement: int
    weapon_name: str
    costume_id: str | None
    build_id: str
    build_md5: str
    last_build_update: str | None
    art_url: str
    weapon_url: str
    element: str | None = None
    rarity: int | None = None
    weapon_rarity: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Build":
        return cls(**value)


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
    """

    name: str = ""
    offset_x: float = 0.0
    offset_y: float = -0.02
    zoom: float = 1.0
    color: str = "#78d7ff"
    flip: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Placement":
        """Read the known keys, ignoring unknown ones, so that a legacy payload
        loads with default framing instead of raising."""
        defaults = cls()
        return cls(
            name=str(value.get("name", defaults.name)),
            offset_x=float(value.get("offset_x", defaults.offset_x)),
            offset_y=float(value.get("offset_y", defaults.offset_y)),
            zoom=float(value.get("zoom", defaults.zoom)),
            color=str(value.get("color", defaults.color)),
            flip=bool(value.get("flip", defaults.flip)),
        )


@dataclass
class Project:
    mode: Mode = "abyss"
    uid: str = ""
    output_name: str = "genshin_thumbnail"
    output_height: int = 1080
    teams: list[list[Placement]] = field(default_factory=list)
    active_team: int = 0

    @property
    def output_size(self) -> tuple[int, int]:
        return (self.output_height * 16 // 9, self.output_height)

    @classmethod
    def blank(cls, mode: Mode = "abyss", uid: str = "") -> "Project":
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
            "schemaVersion": 3,
            "mode": self.mode,
            "uid": self.uid,
            "outputName": self.output_name,
            "outputHeight": self.output_height,
            "activeTeam": self.active_team,
            "teams": [[asdict(member) for member in team] for team in self.teams],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Project":
        raw_mode = str(value.get("mode", "abyss")).casefold()
        mode: Mode
        if raw_mode == "abyss":
            mode = "abyss"
        elif raw_mode == "stygian":
            mode = "stygian"
        else:
            raise ValueError("Project mode must be abyss or stygian.")
        schema_version = int(value.get("schemaVersion", 1))
        if schema_version <= 1:
            # Version 1 files predate the setting and were rendered at the
            # then-hardcoded 720p, so keep their output size unchanged.
            output_height = 720
        else:
            output_height = int(value.get("outputHeight", 1080))
        project = cls(
            mode=mode,
            uid=str(value.get("uid", "")),
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
