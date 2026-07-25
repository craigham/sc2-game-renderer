"""Draws units onto a rendered terrain background: own units, the two SC2-native
enemy visibility categories, the memory tracker's 'remembered' category, and
own-unit movement trails.

Consumes a single ExtractedFrame — which already carries `remembered_enemies`,
computed once during extraction (see enemy_memory.py) — and the current trail state
from a render-time TrailTracker (trail_tracker.py). Draws onto a *copy* of whatever
background render_terrain.py produced, using the same WorldToPixel the caller used
to build that background.
"""

from PIL import Image, ImageDraw

from sc2_game_renderer.coords import WorldToPixel
from sc2_game_renderer.frame_file import ExtractedFrame

OWN_COLOR = (70, 150, 235)
ENEMY_COLOR = (230, 70, 70)
TRAIL_COLOR = (70, 150, 235)

UNIT_RADIUS_SCALE = 0.9  # relative to WorldToPixel.scale
TRAIL_ALPHA_MIN = 60  # oldest segment
TRAIL_ALPHA_MAX = 220  # newest segment
DASH_DEGREES = 18
GAP_DEGREES = 14


def render_units(
    background: Image.Image,
    transform: WorldToPixel,
    extracted: ExtractedFrame,
    trails: dict[int, list[tuple[float, float]]],
) -> Image.Image:
    img = background.convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    frame = extracted.frame
    r = max(2.0, transform.scale * UNIT_RADIUS_SCALE)

    _draw_trails(draw, transform, trails, r)

    for u in frame.own_units:
        _filled_circle(draw, transform, (u.x, u.y), r, OWN_COLOR)

    for u in frame.enemy_visible:
        _filled_circle(draw, transform, (u.x, u.y), r, ENEMY_COLOR)

    for u in frame.enemy_snapshot:
        _hollow_circle(draw, transform, (u.x, u.y), r, ENEMY_COLOR)

    for remembered in extracted.remembered_enemies:
        age = remembered.age_seconds(frame.game_loop)
        pos = (remembered.unit.x, remembered.unit.y)
        _dashed_circle(draw, transform, pos, r, ENEMY_COLOR)
        _label(draw, transform, pos, r, f"{age:.0f}s ago", ENEMY_COLOR)

    return img.convert("RGB")


def _filled_circle(draw, transform, world_pos, r, color):
    px, py = transform.to_pixel(*world_pos)
    draw.ellipse([px - r, py - r, px + r, py + r], fill=(*color, 255))


def _hollow_circle(draw, transform, world_pos, r, color):
    px, py = transform.to_pixel(*world_pos)
    draw.ellipse([px - r, py - r, px + r, py + r], outline=(*color, 255), width=2)


def _dashed_circle(draw, transform, world_pos, r, color):
    px, py = transform.to_pixel(*world_pos)
    bbox = [px - r, py - r, px + r, py + r]
    angle = 0.0
    while angle < 360.0:
        end = min(angle + DASH_DEGREES, 360.0)
        draw.arc(bbox, angle, end, fill=(*color, 220), width=2)
        angle += DASH_DEGREES + GAP_DEGREES


def _label(draw, transform, world_pos, r, text, color):
    px, py = transform.to_pixel(*world_pos)
    draw.text((px + r + 2, py - r), text, fill=(*color, 230))


def _draw_trails(draw, transform, trails, r):
    width = max(1, int(r * 0.4))
    for points in trails.values():
        n = len(points)
        if n < 2:
            continue
        for i in range(n - 1):
            age_fraction = i / max(n - 2, 1)  # 0 = oldest segment, 1 = newest
            alpha = int(TRAIL_ALPHA_MIN + age_fraction * (TRAIL_ALPHA_MAX - TRAIL_ALPHA_MIN))
            p0 = transform.to_pixel(*points[i])
            p1 = transform.to_pixel(*points[i + 1])
            draw.line([p0, p1], fill=(*TRAIL_COLOR, alpha), width=width)
