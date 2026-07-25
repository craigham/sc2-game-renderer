"""Dev preview for slices 6-8 — no CLI yet (that's slice 9's `render`).

Walks the whole frame file in order (so TrailTracker's history is correct), saving a
PNG at each frame whose game_loop is closest to one of --loops. With --log, also
composes the bot-state overlay: positioned world markers, banners, resource
cross-check, and the recent-events ticker.

    uv run python scripts/preview_frames.py out/4891371.frames.jsonl.gz /tmp/preview \
        --loops 0 3000 8200 12800 14000 15200 --log replays/4891371/stderr.log
"""

import argparse
from pathlib import Path

from sc2_game_renderer.bot_state_overlay import IncomeAdvantageTracker, build_overlay
from sc2_game_renderer.coords import WorldToPixel
from sc2_game_renderer.event_ticker import EventTicker
from sc2_game_renderer.frame_file import FrameFileReader
from sc2_game_renderer.render_bot_events import render_bot_events
from sc2_game_renderer.render_hud import compose_frame, render_hud_panel
from sc2_game_renderer.render_terrain import render_terrain
from sc2_game_renderer.render_units import render_units
from sc2_game_renderer.supply_block_tracker import SupplyBlockTracker
from sc2_game_renderer.trail_tracker import TrailTracker

ap = argparse.ArgumentParser()
ap.add_argument("frame_file", type=Path)
ap.add_argument("out_dir", type=Path)
ap.add_argument("--loops", type=int, nargs="+", required=True)
ap.add_argument("--scale", type=float, default=4.0)
ap.add_argument("--log", type=Path, default=None, help="stderr.log for the bot-state overlay")
args = ap.parse_args()

args.out_dir.mkdir(parents=True, exist_ok=True)
remaining_targets = sorted(args.loops)

with FrameFileReader(args.frame_file) as reader:
    header = reader.header
    all_loops = [ef.frame.game_loop for ef in reader]

overlay = None
if args.log is not None:
    overlay = build_overlay(args.log.read_text(errors="replace"), all_loops, header.sample_loops)
    print(
        f"overlay: {overlay.total_event_count} events, {overlay.dropped_event_count} dropped, "
        f"log parse rate {overlay.parse_stats.parse_rate:.3f}"
    )

with FrameFileReader(args.frame_file) as reader:
    transform = WorldToPixel.for_playable_area(header.playable_area, args.scale)
    background = render_terrain(header, args.scale)
    trail_tracker = TrailTracker()
    supply_tracker = SupplyBlockTracker()
    income_tracker = IncomeAdvantageTracker()
    ticker = EventTicker()

    for extracted in reader:
        frame = extracted.frame
        trail_tracker.update(frame)
        blocked_seconds = supply_tracker.update(frame)
        loop = frame.game_loop

        events_here = overlay.events_at(loop) if overlay is not None else ()
        income_tracker.update(events_here)
        ticker.update(events_here)

        if remaining_targets and loop >= remaining_targets[0]:
            target = remaining_targets.pop(0)
            map_img = render_units(background, transform, extracted, trail_tracker.trails())
            map_img = render_bot_events(map_img, transform, events_here)
            hud_panel = render_hud_panel(
                frame, blocked_seconds, height=map_img.height,
                resource_belief=overlay.resource_belief_at(loop) if overlay is not None else None,
                income_advantage=income_tracker.state,
                events_this_frame=events_here,
                ticker_entries=ticker.entries(),
            )
            combined = compose_frame(map_img, hud_panel)
            out_path = args.out_dir / f"loop_{loop:06d}_target_{target:06d}.png"
            combined.save(out_path)
            print(
                f"target {target:>6} -> loop {loop:>6} ({loop/22.4:>5.0f}s)  "
                f"own={len(frame.own_units):>3} "
                f"enemy_vis={len(frame.enemy_visible):>3} "
                f"enemy_snap={len(frame.enemy_snapshot):>3} "
                f"remembered={len(extracted.remembered_enemies):>3}  "
                f"minerals={frame.minerals} supply={frame.supply_used}/{frame.supply_cap} "
                f"events_here={[e.kind for e in events_here]}  -> {out_path}"
            )

        if not remaining_targets:
            break

for target in remaining_targets:
    print(f"target {target} not reached (past end of game)")
