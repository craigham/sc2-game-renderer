"""HUD sidebar: resources, income, supply (+ block duration), workers, idle workers,
army value, game clock — everything free or cheaply derived from a single Frame plus
the render-time supply-block duration (supply_block_tracker.py).

`compose_frame` puts the HUD beside a rendered map pane (render_terrain.py +
render_units.py) at their natural sizes. Fitting the combined image to a final output
resolution is a slice 9 (`render` CLI) concern, not this one.
"""

from PIL import Image, ImageDraw, ImageFont

from sc2_game_renderer.frame import Frame

BACKGROUND_COLOR = (18, 18, 24)
TEXT_COLOR = (225, 225, 230)
LABEL_COLOR = (140, 140, 150)
WARNING_COLOR = (235, 90, 60)
LOOPS_PER_SECOND = 22.4

DEFAULT_SIDEBAR_WIDTH = 280
PADDING = 16
LINE_HEIGHT = 26
FONT_SIZE = 16


def _font() -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=FONT_SIZE)


def _format_clock(game_loop: int) -> str:
    total_seconds = int(game_loop / LOOPS_PER_SECOND)
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def render_hud_panel(frame: Frame, supply_blocked_seconds: float, width: int = DEFAULT_SIDEBAR_WIDTH, height: int = 720) -> Image.Image:
    img = Image.new("RGB", (width, height), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)
    font = _font()

    x = PADDING
    y = PADDING

    def line(text: str, color=TEXT_COLOR):
        nonlocal y
        draw.text((x, y), text, font=font, fill=color)
        y += LINE_HEIGHT

    line(_format_clock(frame.game_loop), color=TEXT_COLOR)
    y += LINE_HEIGHT // 2

    line("Resources", color=LABEL_COLOR)
    line(f"Minerals  {frame.minerals:>5}  ({frame.minerals_rate:.0f}/min)")
    line(f"Vespene   {frame.vespene:>5}  ({frame.vespene_rate:.0f}/min)")
    y += LINE_HEIGHT // 2

    line("Supply", color=LABEL_COLOR)
    line(f"{frame.supply_used}/{frame.supply_cap}")
    if supply_blocked_seconds > 0:
        line(f"BLOCKED {supply_blocked_seconds:.0f}s", color=WARNING_COLOR)
    y += LINE_HEIGHT // 2

    line("Workers", color=LABEL_COLOR)
    idle_color = WARNING_COLOR if frame.idle_worker_count > 0 else TEXT_COLOR
    line(f"{frame.supply_workers}  (idle: {frame.idle_worker_count})", color=idle_color)
    y += LINE_HEIGHT // 2

    line("Army value", color=LABEL_COLOR)
    line(f"{frame.army_value_minerals}m / {frame.army_value_vespene}g")

    return img


def compose_frame(map_image: Image.Image, hud_panel: Image.Image) -> Image.Image:
    """Side by side, matched to the map pane's height — no resizing here."""
    height = map_image.height
    if hud_panel.height != height:
        hud_panel = hud_panel.resize((hud_panel.width, height))

    combined = Image.new("RGB", (map_image.width + hud_panel.width, height), BACKGROUND_COLOR)
    combined.paste(map_image, (0, 0))
    combined.paste(hud_panel, (map_image.width, 0))
    return combined
