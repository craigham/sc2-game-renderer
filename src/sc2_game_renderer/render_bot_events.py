"""Draws the bot's own logged positioned events onto the map pane: builds/trains at
their coordinates, pathing failures at the failed route's endpoints.

Draws whatever events are already joined to the current frame (bot_state_overlay.py)
— each event attaches to exactly the one frame it was joined to, so these are
inherently momentary "flash" markers; no fade tracking needed (the HUD's event
ticker, event_ticker.py, is what keeps them visible for longer than one frame).
"""

from PIL import Image, ImageDraw

from sc2_game_renderer.bot_log import BotEvent
from sc2_game_renderer.coords import WorldToPixel

BUILD_EVENT_KINDS = {"unit_trained", "build_addon", "build_gas"}
PROBLEM_EVENT_KINDS = {"cancel_building", "unreachable"}

BUILD_COLOR = (245, 200, 60)
PROBLEM_COLOR = (255, 140, 30)


def render_bot_events(image: Image.Image, transform: WorldToPixel, events: tuple[BotEvent, ...]) -> Image.Image:
    if not events:
        return image

    img = image.convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    r = max(3.0, transform.scale * 0.8)

    for e in events:
        if e.kind in BUILD_EVENT_KINDS and e.pos is not None:
            _diamond(draw, transform, e.pos, r, BUILD_COLOR)
        elif e.kind == "no_path" and e.pos is not None and e.pos2 is not None:
            _cross(draw, transform, e.pos, r, PROBLEM_COLOR)
            p0 = transform.to_pixel(*e.pos)
            p1 = transform.to_pixel(*e.pos2)
            draw.line([p0, p1], fill=(*PROBLEM_COLOR, 160), width=1)
        elif e.kind in PROBLEM_EVENT_KINDS and e.pos is not None:
            _cross(draw, transform, e.pos, r, PROBLEM_COLOR)

    return img.convert("RGB")


def _diamond(draw, transform, world_pos, r, color):
    px, py = transform.to_pixel(*world_pos)
    draw.polygon([(px, py - r), (px + r, py), (px, py + r), (px - r, py)], outline=(*color, 255), width=2)


def _cross(draw, transform, world_pos, r, color):
    px, py = transform.to_pixel(*world_pos)
    draw.line([(px - r, py - r), (px + r, py + r)], fill=(*color, 255), width=2)
    draw.line([(px - r, py + r), (px + r, py - r)], fill=(*color, 255), width=2)
