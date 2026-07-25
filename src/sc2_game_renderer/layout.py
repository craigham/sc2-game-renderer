"""Fits the map pane into a fixed output resolution, beside a fixed-width HUD
sidebar, preserving the map's aspect ratio via letterboxing rather than stretching
it (stretching would silently break every world->pixel position on screen).

Pure geometry — testable directly, same reasoning as coords.py's WorldToPixel.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Layout:
    output_width: int
    output_height: int
    sidebar_width: int
    map_pane_width: int  # output_width - sidebar_width
    map_scale: float  # world units -> pixels, passed straight to WorldToPixel
    rendered_width: int  # actual map image size at map_scale (matches WorldToPixel's
    rendered_height: int  # own rounding, so pasting it never needs a resize)
    map_offset_x: int  # centering offset within the pane (letterbox)
    map_offset_y: int


def compute_layout(
    output_width: int,
    output_height: int,
    sidebar_width: int,
    extent_width: float,
    extent_height: float,
) -> Layout:
    map_pane_width = output_width - sidebar_width
    scale = min(map_pane_width / extent_width, output_height / extent_height)
    rendered_width = round(extent_width * scale)
    rendered_height = round(extent_height * scale)
    return Layout(
        output_width=output_width,
        output_height=output_height,
        sidebar_width=sidebar_width,
        map_pane_width=map_pane_width,
        map_scale=scale,
        rendered_width=rendered_width,
        rendered_height=rendered_height,
        map_offset_x=(map_pane_width - rendered_width) // 2,
        map_offset_y=(output_height - rendered_height) // 2,
    )
