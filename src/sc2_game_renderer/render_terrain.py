"""Static terrain background: pathing/placement/height grids, cropped to the
playable area, rendered once per game (the world doesn't change frame to frame).

Establishes the world->pixel transform (coords.py) that every later rendering slice
reuses for units, trails, and overlays.
"""

import numpy as np
from PIL import Image, ImageDraw

from sc2_game_renderer.coords import WorldToPixel
from sc2_game_renderer.frame_file import GameHeader

UNPATHABLE_COLOR = (18, 18, 34)  # cliffs, water, destructibles — cannot walk here
UNBUILDABLE_TINT = (60, 70, 110)  # pathable but not placeable — ramps, narrow terrain
START_LOCATION_COLOR = (235, 60, 60)

DEFAULT_SCALE = 4.0  # pixels per world unit


def render_terrain(header: GameHeader, scale: float = DEFAULT_SCALE) -> Image.Image:
    transform = WorldToPixel.for_playable_area(header.playable_area, scale)
    x0, y0, x1, y1 = header.playable_area

    height = header.terrain_height.to_numpy()[y0:y1, x0:x1].astype(np.float32)
    pathing = header.pathing_grid.to_numpy()[y0:y1, x0:x1]
    placement = header.placement_grid.to_numpy()[y0:y1, x0:x1]

    h_min, h_max = float(height.min()), float(height.max())
    span = max(h_max - h_min, 1.0)
    gray = ((height - h_min) / span * 150 + 60).astype(np.uint8)
    rgb = np.stack([gray, gray, gray], axis=-1)

    unpathable = pathing == 0
    rgb[unpathable] = UNPATHABLE_COLOR

    unbuildable_pathable = (placement == 0) & ~unpathable
    tint = np.array(UNBUILDABLE_TINT, dtype=np.float32)
    rgb[unbuildable_pathable] = (rgb[unbuildable_pathable].astype(np.float32) * 0.4 + tint * 0.6).astype(np.uint8)

    rgb = np.flipud(rgb)  # raw grid row 0 is y=0 (south); image row 0 must be north

    img = Image.fromarray(rgb, mode="RGB").resize(
        (transform.pixel_width, transform.pixel_height), Image.NEAREST
    )

    draw = ImageDraw.Draw(img)
    marker_r = max(4.0, scale)
    for x, y in header.start_locations:
        px, py = transform.to_pixel(x, y)
        draw.ellipse([px - marker_r, py - marker_r, px + marker_r, py + marker_r], outline=START_LOCATION_COLOR, width=2)

    return img
