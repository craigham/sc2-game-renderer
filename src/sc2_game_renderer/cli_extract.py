"""extract: replay + observed player -> frame file. The only stage that needs SC2.

    python -m sc2_game_renderer.cli_extract REPLAY --player ID --out OUT.frames.jsonl.gz

Runs inside the sc2-extract Docker image (see docker/Dockerfile) — SC2 4.10 does not
launch on current macOS (docs/SPEC.md § Chief risk). `render` (slice 9) reads the
output file and never needs SC2 or Docker.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sc2_game_renderer.enemy_memory import EnemyMemory
from sc2_game_renderer.frame import frame_from_observation
from sc2_game_renderer.frame_file import ExtractedFrame, FrameFileWriter, GameHeader
from sc2_game_renderer.sc2_stepper import ReplaySession

DEFAULT_SAMPLE_LOOPS = 4
DEFAULT_MEMORY_TTL_SECONDS = 60.0


async def extract(
    replay: Path,
    observed_id: int,
    out: Path,
    sample_loops: int = DEFAULT_SAMPLE_LOOPS,
    memory_ttl_seconds: float = DEFAULT_MEMORY_TTL_SECONDS,
    max_frames: int | None = None,
) -> int:
    memory = EnemyMemory(ttl_seconds=memory_ttl_seconds)

    async with ReplaySession(replay, observed_id) as session:
        header = GameHeader.from_game_info(
            session.game_info,
            bot_player_id=observed_id,
            sample_loops=sample_loops,
            memory_ttl_seconds=memory_ttl_seconds,
        )

        # Streamed straight to disk frame-by-frame (FrameFileWriter) rather than
        # buffered into a list and written once at the end — lets a consumer (e.g.
        # a web server) show the replay while it's still being extracted instead of
        # only once the whole game has been stepped.
        count = 0
        with FrameFileWriter(out, header) as writer:
            async for obs in session.observations(sample_loops):
                frame = frame_from_observation(obs, session.structure_type_ids)
                memory.update(frame)
                writer.write(
                    ExtractedFrame(frame=frame, remembered_enemies=tuple(memory.remembered(frame.game_loop)))
                )
                count += 1
                if max_frames is not None and count >= max_frames:
                    break

    return count


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("replay", type=Path)
    ap.add_argument("--player", type=int, required=True, help="observed player id (the bot)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sample-loops", type=int, default=DEFAULT_SAMPLE_LOOPS)
    ap.add_argument("--memory-ttl", type=float, default=DEFAULT_MEMORY_TTL_SECONDS)
    ap.add_argument("--max-frames", type=int, default=None, help="stop early (debugging)")
    args = ap.parse_args()

    replay = args.replay.resolve()
    if not replay.exists():
        sys.exit(f"not found: {replay}")

    count = asyncio.run(
        extract(replay, args.player, args.out, args.sample_loops, args.memory_ttl, args.max_frames)
    )
    print(f"wrote {count} frames to {args.out}")


if __name__ == "__main__":
    main()
