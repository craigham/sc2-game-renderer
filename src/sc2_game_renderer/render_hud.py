"""HUD sidebar: resources, income, supply (+ block duration), workers, idle workers,
army value, game clock — everything free or cheaply derived from a single Frame plus
the render-time supply-block duration (supply_block_tracker.py) — plus the bot-state
overlay (bot_state_overlay.py, event_ticker.py): the belief-vs-truth resource
cross-check, the persistent income-advantage banner, momentary danger warnings, and
the recent-events ticker.

`compose_frame` puts the HUD beside a rendered map pane (render_terrain.py +
render_units.py + render_bot_events.py) at their natural sizes. Fitting the combined
image to a final output resolution is a slice 9 (`render` CLI) concern, not this one.
"""

from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from sc2_game_renderer.bot_log import BotEvent
from sc2_game_renderer.bot_state_overlay import ResourceBelief
from sc2_game_renderer.frame import Frame
from sc2_game_renderer.layout import Layout

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


def render_hud_panel(
    frame: Frame,
    supply_blocked_seconds: float,
    width: int = DEFAULT_SIDEBAR_WIDTH,
    height: int = 720,
    *,
    resource_belief: ResourceBelief | None = None,
    income_advantage: str | None = None,
    events_this_frame: tuple[BotEvent, ...] = (),
    ticker_entries: Sequence[str] = (),
) -> Image.Image:
    img = Image.new("RGB", (width, height), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)
    font = _font()

    x = PADDING
    y = PADDING

    def line(text: str, color=TEXT_COLOR):
        nonlocal y
        draw.text((x, y), text, font=font, fill=color)
        y += LINE_HEIGHT

    def belief_line(believed_value, truth_value):
        color = TEXT_COLOR if believed_value == truth_value else WARNING_COLOR
        line(f"  bot believed: {believed_value}", color=color)

    line(_format_clock(frame.game_loop), color=TEXT_COLOR)
    y += LINE_HEIGHT // 2

    line("Resources", color=LABEL_COLOR)
    line(f"Minerals  {frame.minerals:>5}  ({frame.minerals_rate:.0f}/min)")
    if resource_belief is not None:
        belief_line(resource_belief.minerals, frame.minerals)
    line(f"Vespene   {frame.vespene:>5}  ({frame.vespene_rate:.0f}/min)")
    if resource_belief is not None:
        belief_line(resource_belief.vespene, frame.vespene)
    y += LINE_HEIGHT // 2

    line("Supply", color=LABEL_COLOR)
    line(f"{frame.supply_used}/{frame.supply_cap}")
    if resource_belief is not None:
        belief_line(f"{resource_belief.supply_used}/{resource_belief.supply_cap}", f"{frame.supply_used}/{frame.supply_cap}")
    if supply_blocked_seconds > 0:
        line(f"BLOCKED {supply_blocked_seconds:.0f}s", color=WARNING_COLOR)
    y += LINE_HEIGHT // 2

    line("Workers", color=LABEL_COLOR)
    idle_color = WARNING_COLOR if frame.idle_worker_count > 0 else TEXT_COLOR
    line(f"{frame.supply_workers}  (idle: {frame.idle_worker_count})", color=idle_color)
    y += LINE_HEIGHT // 2

    line("Army value", color=LABEL_COLOR)
    line(f"{frame.army_value_minerals}m / {frame.army_value_vespene}g")

    if income_advantage is not None:
        y += LINE_HEIGHT // 2
        line("Bot status", color=LABEL_COLOR)
        line(f"Income advantage: {income_advantage}")

    for event in events_this_frame:
        d = event.data_dict()
        if event.kind == "workers_in_danger":
            line(f"Workers in danger: {d['count']}", color=WARNING_COLOR)
        elif event.kind == "high_working_danger":
            line("High working danger — evacuate!", color=WARNING_COLOR)

    if ticker_entries:
        y += LINE_HEIGHT // 2
        line("Recent events", color=LABEL_COLOR)
        for text in ticker_entries:
            line(text, color=LABEL_COLOR)

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


def assemble_frame(layout: Layout, map_image: Image.Image, hud_panel: Image.Image) -> Image.Image:
    """Letterboxes `map_image` (already rendered at `layout.map_scale`, so its size
    should exactly match `layout.rendered_width/height` — see layout.py) into the
    output-resolution pane, then composes it with the HUD sidebar. Always produces
    exactly (layout.output_width, layout.output_height), which is what makes this
    safe to pipe straight to ffmpeg as fixed-size rawvideo frames.
    """
    pane = Image.new("RGB", (layout.map_pane_width, layout.output_height), BACKGROUND_COLOR)
    pane.paste(map_image, (layout.map_offset_x, layout.map_offset_y))
    return compose_frame(pane, hud_panel)
