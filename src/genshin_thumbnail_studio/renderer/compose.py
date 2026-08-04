from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image

from ..models import Asset, Placement, Project
from . import panels
from .badges import add_badges
from .cache import PANEL_CACHE_MAX, cache_get, cache_put, clear_render_cache, panel_cache
from .colors import card_color
from .geometry import BACKGROUND_COLOR, BASE_H, BASE_W, panel_metrics, panel_origin
from .panels import add_card_borders


def safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" ._")
    return cleaned or "thumbnail"


def render_image(
    teams: list[list[Placement]],
    assets: dict[str, Asset],
    compact: bool,
    scale: int = 1,
    output_size: tuple[int, int] = (BASE_W, BASE_H),
    require_complete: bool = True,
) -> Image.Image:
    if scale < 1 or scale > 4:
        raise ValueError("Scale must be between 1 and 4.")
    width = BASE_W * scale
    height = BASE_H * scale
    row_height, _, slant = panel_metrics(compact, scale)
    step = width / 4
    canvas = Image.new("RGBA", (width, height), BACKGROUND_COLOR)
    num_rows = len(teams)
    for row, team in enumerate(teams):
        for index, member in enumerate(team):
            has_asset = bool(member.name) and member.name.casefold() in assets
            if not has_asset and require_complete:
                raise ValueError(f"No downloaded Akasha asset for slot {row + 1}-{index + 1}.")
            asset = assets[member.name.casefold()] if has_asset else None
            cache_key = (
                index,
                row,
                num_rows,
                member.name.casefold(),
                round(member.offset_x, 4),
                round(member.offset_y, 4),
                round(member.zoom, 4),
                member.flip,
                # Must track what make_panel() actually paints with
                # (card_color(member, asset)), not the raw placement color,
                # or a stale panel can survive an element change.
                card_color(member, asset) if asset else member.color,
                str(asset.art_path) if asset else None,
                row_height,
                step,
                slant,
                scale,
                compact,
            )
            panel = cache_get(panel_cache, cache_key)
            if panel is None:
                # The two builders are reached through the `panels` module object
                # rather than bound into this module's globals, so a test (and any
                # future instrumentation) can patch them on `renderer.panels` and
                # still intercept a render that is already in flight.
                if asset is not None:
                    panel = panels.make_panel(
                        width,
                        member,
                        asset,
                        index,
                        row,
                        num_rows,
                        row_height,
                        step,
                        slant,
                        scale,
                        compact,
                    )
                else:
                    panel = panels.placeholder_panel(
                        width,
                        member,
                        index,
                        row,
                        num_rows,
                        row_height,
                        step,
                        slant,
                        scale,
                        compact,
                    )
                cache_put(panel_cache, cache_key, panel, PANEL_CACHE_MAX)
            # The panel overhangs the canvas on the left for slot 0 and on the
            # right for slot 3; clipping the left overhang needs a source
            # offset, while the in-place composite clips the right one itself.
            origin_x, origin_y = panel_origin(index, row, row_height, step, slant)
            canvas.alpha_composite(panel, (max(0, origin_x), origin_y), (max(0, -origin_x), 0))
    add_card_borders(canvas, teams, assets, row_height, step, slant, scale)
    add_badges(canvas, teams, assets, row_height, step, scale, compact)
    # Pillow's Image.resize() stub leaves its overload partially unknown.
    return canvas.convert("RGB").resize(output_size, Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType]


def render_preview(project: Project, assets: dict[str, Asset]) -> Image.Image:
    project.ensure_shape()
    if project.mode == "abyss":
        return render_image(project.teams, assets, compact=True, scale=1, require_complete=False)
    return render_image(
        [project.teams[project.active_team]], assets, compact=False, scale=1, require_complete=False
    )


def export_project(project: Project, assets: dict[str, Asset], directory: Path) -> list[Path]:
    project.ensure_shape()
    directory.mkdir(parents=True, exist_ok=True)
    scale = min(4, max(2, math.ceil(2 * project.output_height / BASE_H)))
    output_size = project.output_size
    written: list[Path] = []
    try:
        if project.mode == "abyss":
            target = directory / f"{safe_name(project.output_name)}.png"
            render_image(project.teams, assets, compact=True, scale=scale, output_size=output_size).save(
                target, optimize=True
            )
            written.append(target)
        else:
            for index, team in enumerate(project.teams, start=1):
                target = directory / f"{safe_name(project.output_name)}_boss{index}.png"
                render_image([team], assets, compact=False, scale=scale, output_size=output_size).save(
                    target, optimize=True
                )
                written.append(target)
    finally:
        clear_render_cache()
    return written
