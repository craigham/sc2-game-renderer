"""render: frame file (+ optional stderr.log) -> MP4. Pure Pillow + ffmpeg — never
touches SC2, a replay, or Docker (see docs/SPEC.md § Architecture). This is the stage
that actually gets iterated on, which is why extract and render are split at all.

    python -m sc2_game_renderer.cli_render FRAMES.jsonl.gz --out OUT.mp4 [--log stderr.log]

`--realtime` computes the fps for ~1x playback from the frame file's own
`sample_loops` (fixed at extract time — render can't conjure samples extract didn't
take). A coarser-sampled frame file will look choppier at 1x; that's expected, not a
bug in this stage.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from sc2_game_renderer.bot_state_overlay import IncomeAdvantageTracker, build_overlay
from sc2_game_renderer.coords import WorldToPixel
from sc2_game_renderer.event_ticker import EventTicker
from sc2_game_renderer.frame_file import FrameFileReader
from sc2_game_renderer.layout import compute_layout
from sc2_game_renderer.render_bot_events import render_bot_events
from sc2_game_renderer.render_hud import DEFAULT_SIDEBAR_WIDTH, assemble_frame, render_hud_panel
from sc2_game_renderer.render_terrain import render_terrain
from sc2_game_renderer.render_units import render_units
from sc2_game_renderer.supply_block_tracker import SupplyBlockTracker
from sc2_game_renderer.trail_tracker import TrailTracker

LOOPS_PER_SECOND = 22.4
DEFAULT_FPS = 30
DEFAULT_RESOLUTION = "1280x720"


def _build_ffmpeg_command(out: Path, width: int, height: int, fps: float) -> list[str]:
    # ffmpeg accepts a fractional -r directly; rounding to an integer here would
    # make --realtime drift from true 1x (5.6 rounded to 6fps runs ~7% fast over a
    # full game — confirmed against the fixture: 634.8s rendered vs. 680.0s real).
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", f"{fps!r}",
        "-i", "-",
        "-an", "-vcodec", "libx264", "-pix_fmt", "yuv420p",
        str(out),
    ]


def render(
    frame_file: Path,
    out: Path,
    log: Path | None = None,
    fps: float = DEFAULT_FPS,
    width: int = 1280,
    height: int = 720,
    sidebar_width: int = DEFAULT_SIDEBAR_WIDTH,
) -> int:
    # Frame loops are needed up front for the bot-log join (nearest-at-or-after needs
    # the whole sorted sequence, not a running window) — one cheap first pass.
    with FrameFileReader(frame_file) as reader:
        header = reader.header
        all_loops = [ef.frame.game_loop for ef in reader]

    overlay = None
    if log is not None:
        overlay = build_overlay(log.read_text(errors="replace"), all_loops, header.sample_loops)
        print(
            f"bot-state overlay: {overlay.total_event_count} events, "
            f"{overlay.dropped_event_count} dropped, log parse rate {overlay.parse_stats.parse_rate:.3f}"
        )
        if overlay.total_event_count and overlay.dropped_event_count == overlay.total_event_count:
            print("warning: every event was dropped — replay and log likely don't match", file=sys.stderr)

    x0, y0, x1, y1 = header.playable_area
    layout = compute_layout(width, height, sidebar_width, x1 - x0, y1 - y0)
    background = render_terrain(header, layout.map_scale)
    transform = WorldToPixel.for_playable_area(header.playable_area, layout.map_scale)

    ffmpeg_cmd = _build_ffmpeg_command(out, width, height, fps)
    try:
        proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        sys.exit("ffmpeg not found on PATH — install it first (e.g. `brew install ffmpeg`)")

    trail_tracker = TrailTracker()
    supply_tracker = SupplyBlockTracker()
    income_tracker = IncomeAdvantageTracker()
    ticker = EventTicker()

    written = 0
    with FrameFileReader(frame_file) as reader:
        for extracted in reader:
            frame = extracted.frame
            trail_tracker.update(frame)
            blocked_seconds = supply_tracker.update(frame)

            events_here = overlay.events_at(frame.game_loop) if overlay is not None else ()
            income_tracker.update(events_here)
            ticker.update(events_here)

            map_img = render_units(background, transform, extracted, trail_tracker.trails())
            map_img = render_bot_events(map_img, transform, events_here)
            hud_panel = render_hud_panel(
                frame, blocked_seconds, width=sidebar_width, height=height,
                resource_belief=overlay.resource_belief_at(frame.game_loop) if overlay is not None else None,
                income_advantage=income_tracker.state,
                events_this_frame=events_here,
                ticker_entries=ticker.entries(),
            )
            final = assemble_frame(layout, map_img, hud_panel)
            assert final.size == (width, height), f"frame {written} size {final.size} != ({width}, {height})"

            proc.stdin.write(final.tobytes())
            written += 1
            if written % 200 == 0:
                print(f"... {written}/{len(all_loops)} frames")

    # communicate() would try to close stdin itself, which raises if it's already
    # closed — since we wrote to it manually above, close it ourselves and just
    # wait(); with -loglevel error, stderr has negligible volume by the time the
    # process exits, so reading it after wait() (not concurrently) is safe here.
    proc.stdin.close()
    proc.wait()
    stderr = proc.stderr.read()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}):\n{stderr.decode(errors='replace')}")

    assert written == len(all_loops), f"wrote {written} frames but frame file has {len(all_loops)}"
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("frame_file", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--log", type=Path, default=None, help="stderr.log for the bot-state overlay (optional)")
    ap.add_argument("--fps", type=float, default=DEFAULT_FPS)
    ap.add_argument("--resolution", type=str, default=DEFAULT_RESOLUTION, help="WxH, e.g. 1280x720")
    ap.add_argument("--realtime", action="store_true", help="~1x playback fps, derived from the frame file's own sampling rate; overrides --fps")
    args = ap.parse_args()

    frame_file = args.frame_file.resolve()
    if not frame_file.exists():
        sys.exit(f"not found: {frame_file}")
    if args.log is not None and not args.log.exists():
        sys.exit(f"not found: {args.log}")

    try:
        width, height = (int(v) for v in args.resolution.lower().split("x"))
    except ValueError:
        sys.exit(f"--resolution must be WxH, e.g. 1280x720 (got {args.resolution!r})")

    fps = args.fps
    if args.realtime:
        with FrameFileReader(frame_file) as reader:
            sample_loops = reader.header.sample_loops
        fps = LOOPS_PER_SECOND / sample_loops
        print(f"--realtime: sample_loops={sample_loops} -> {fps:.3f}fps for ~1x playback (ignoring --fps)")

    count = render(frame_file, args.out, args.log, fps, width, height)
    print(f"wrote {count} frames to {args.out}")


if __name__ == "__main__":
    main()
