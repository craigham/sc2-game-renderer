"""Dev preview for slice 6 — no CLI yet (that's slice 9's `render`).

Walks the whole frame file in order (so TrailTracker's history is correct), saving a
PNG at each frame whose game_loop is closest to one of --loops.

    uv run python scripts/preview_frames.py out/4891371.frames.jsonl.gz /tmp/preview \
        --loops 0 3000 8200 12800 14000 15200
"""

import argparse
from pathlib import Path

from sc2_game_renderer.coords import WorldToPixel
from sc2_game_renderer.frame_file import FrameFileReader
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
args = ap.parse_args()

args.out_dir.mkdir(parents=True, exist_ok=True)
remaining_targets = sorted(args.loops)

with FrameFileReader(args.frame_file) as reader:
    header = reader.header
    transform = WorldToPixel.for_playable_area(header.playable_area, args.scale)
    background = render_terrain(header, args.scale)
    trail_tracker = TrailTracker()
    supply_tracker = SupplyBlockTracker()

    for extracted in reader:
        frame = extracted.frame
        trail_tracker.update(frame)
        blocked_seconds = supply_tracker.update(frame)
        loop = frame.game_loop

        if remaining_targets and loop >= remaining_targets[0]:
            target = remaining_targets.pop(0)
            map_img = render_units(background, transform, extracted, trail_tracker.trails())
            hud_panel = render_hud_panel(frame, blocked_seconds, height=map_img.height)
            combined = compose_frame(map_img, hud_panel)
            out_path = args.out_dir / f"loop_{loop:06d}_target_{target:06d}.png"
            combined.save(out_path)
            print(
                f"target {target:>6} -> loop {loop:>6} ({loop/22.4:>5.0f}s)  "
                f"own={len(frame.own_units):>3} "
                f"enemy_vis={len(frame.enemy_visible):>3} "
                f"enemy_snap={len(frame.enemy_snapshot):>3} "
                f"remembered={len(extracted.remembered_enemies):>3}  "
                f"minerals={frame.minerals} supply={frame.supply_used}/{frame.supply_cap}  -> {out_path}"
            )

        if not remaining_targets:
            break

for target in remaining_targets:
    print(f"target {target} not reached (past end of game)")
