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
from sc2_game_renderer.frame import UnitSnapshot
from sc2_game_renderer.frame_file import ExtractedFrame

OWN_UNIT_COLOR = (70, 150, 235)
OWN_STRUCTURE_COLOR = (40, 90, 150)  # darker/more muted — same hue, distinct shade
ENEMY_UNIT_COLOR = (230, 70, 70)
ENEMY_STRUCTURE_COLOR = (150, 40, 40)
TRAIL_COLOR = (70, 150, 235)

MIN_RADIUS_PX = 2.0  # floor so a small-footprint unit (e.g. a Zergling) stays visible
TRAIL_ALPHA_MIN = 60  # oldest segment
TRAIL_ALPHA_MAX = 220  # newest segment
DASH_DEGREES = 18
GAP_DEGREES = 14


def _radius_px(u: UnitSnapshot, transform: WorldToPixel) -> float:
    """Real per-unit radius (u.radius, from the observation) scaled to pixels —
    proportional to each unit's actual in-game footprint rather than one fixed size
    for everything. Structures (radius ~2-3) end up visibly larger than mobile units
    (radius ~0.375-0.75), which is also what makes them recognizable without a
    separate marker shape."""
    return max(MIN_RADIUS_PX, u.radius * transform.scale)


def render_units(
    background: Image.Image,
    transform: WorldToPixel,
    extracted: ExtractedFrame,
    trails: dict[int, list[tuple[float, float]]],
) -> Image.Image:
    img = background.convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    frame = extracted.frame

    _draw_trails(draw, transform, trails, MIN_RADIUS_PX)

    for u in frame.own_units:
        color = OWN_STRUCTURE_COLOR if u.is_structure else OWN_UNIT_COLOR
        _filled_circle(draw, transform, u, _radius_px(u, transform), color)

    for u in frame.enemy_visible:
        color = ENEMY_STRUCTURE_COLOR if u.is_structure else ENEMY_UNIT_COLOR
        _filled_circle(draw, transform, u, _radius_px(u, transform), color)

    for u in frame.enemy_snapshot:
        # Always a structure in practice — SC2 only ever snapshots buildings
        # through fog, never mobile units — but read is_structure anyway rather
        # than assuming, in case that ever isn't true for some unit.
        color = ENEMY_STRUCTURE_COLOR if u.is_structure else ENEMY_UNIT_COLOR
        _hollow_circle(draw, transform, u, _radius_px(u, transform), color)

    for remembered in extracted.remembered_enemies:
        age = remembered.age_seconds(frame.game_loop)
        u = remembered.unit
        color = ENEMY_STRUCTURE_COLOR if u.is_structure else ENEMY_UNIT_COLOR
        r = _radius_px(u, transform)
        _dashed_circle(draw, transform, u, r, color)
        _label(draw, transform, u, r, f"{age:.0f}s ago", color)

    return img.convert("RGB")


def _filled_circle(draw, transform, u, r, color):
    px, py = transform.to_pixel(u.x, u.y)
    draw.ellipse([px - r, py - r, px + r, py + r], fill=(*color, 255))


def _hollow_circle(draw, transform, u, r, color):
    px, py = transform.to_pixel(u.x, u.y)
    draw.ellipse([px - r, py - r, px + r, py + r], outline=(*color, 255), width=2)


def _dashed_circle(draw, transform, u, r, color):
    px, py = transform.to_pixel(u.x, u.y)
    bbox = [px - r, py - r, px + r, py + r]
    angle = 0.0
    while angle < 360.0:
        end = min(angle + DASH_DEGREES, 360.0)
        draw.arc(bbox, angle, end, fill=(*color, 220), width=2)
        angle += DASH_DEGREES + GAP_DEGREES


def _label(draw, transform, u, r, text, color):
    px, py = transform.to_pixel(u.x, u.y)
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
