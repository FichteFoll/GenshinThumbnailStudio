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
    name: str = ""
    fx: float = 0.50
    fy: float = 0.52
    zoom: float = 1.06
    color: str = "#78d7ff"


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
        zoom = 1.06 if mode == "abyss" else 1.18
        teams = []
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
            "schemaVersion": 2,
            "mode": self.mode,
            "uid": self.uid,
            "outputName": self.output_name,
            "outputHeight": self.output_height,
            "activeTeam": self.active_team,
            "teams": [[asdict(member) for member in team] for team in self.teams],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Project":
        mode = str(value.get("mode", "abyss")).casefold()
        if mode not in {"abyss", "stygian"}:
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
                [Placement(**member) for member in team]
                for team in value.get("teams", [])
            ],
        )
        project.ensure_shape()
        return project
