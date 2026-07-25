"""Slice 0 spike: can we step a replay headlessly on this Mac and pull observations?

Throwaway. Answers one question and produces the test fixture; the real extractor
replaces it.

    uv run python scripts/spike_step_replay.py replays/4891371/*.SC2Replay --player 2

Launches SC2 pinned to the replay's own base build (the version the ladder used),
starts the replay observed as the bot's player id with fog left ON, and pulls a full
observation every N game loops.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

from s2clientprotocol import sc2api_pb2 as sc_pb
from sc2.client import Client
from sc2.main import get_replay_version
from sc2.sc2process import SC2Process


async def start_replay_raw(server, replay: Path, observed_id: int):
    """Start the replay without python-sc2's Linux basename rewriting.

    On Linux, controller.start_replay() strips the path to a basename, which the
    client then fails to resolve ("Unable to open replay"). We issue the request
    ourselves: absolute path first, then the raw bytes, which sidestep paths
    entirely.

    Fog stays enabled — disable_fog is never set, so we observe only what this
    player could see.
    """
    ifopts = sc_pb.InterfaceOptions(
        raw=True, score=True, show_cloaked=True, raw_affects_selection=True, raw_crop_to_playable_area=False
    )

    for label, kwargs in (
        ("absolute path", {"replay_path": str(replay)}),
        ("replay_data", {"replay_data": replay.read_bytes()}),
    ):
        result = await server._execute(
            start_replay=sc_pb.RequestStartReplay(observed_player_id=observed_id, realtime=False, options=ifopts, **kwargs)
        )
        if result.status == 4:
            print(f"  started via {label}")
            return
        print(f"  {label} failed: {result.start_replay.error} {result.start_replay.error_details}")

    raise RuntimeError("could not start replay by any method")


def write_records(path: Path, records: list[bytes]):
    """Length-delimited, gzipped: one file instead of dozens, and git-friendly."""
    import gzip
    import struct

    with gzip.open(path, "wb") as f:
        for r in records:
            f.write(struct.pack("<I", len(r)))
            f.write(r)


async def step_replay(replay: Path, observed_id: int, sample_loops: int, max_frames: int, pin_version: bool,
                      dump_dir: Path | None = None, dump_every: int = 76):
    base_build, data_hash = get_replay_version(replay)
    print(f"replay build: {base_build} / {data_hash}")

    # Pinning matters only where several builds are installed (the Mac). The Linux
    # container ships exactly one, and pinning there just risks the data-path
    # selection that crashes under translation.
    kwargs = {"base_build": base_build, "data_hash": data_hash} if pin_version else {}
    async with SC2Process(fullscreen=False, **kwargs) as server:
        await server.ping()
        print("SC2 up, starting replay...")
        await start_replay_raw(server, replay, observed_id)

        client = Client(server._ws)
        game_info = await client.get_game_info()
        print(f"map: {game_info.map_name}  playable: {game_info.playable_area}")
        print(f"pathing grid: {game_info.pathing_grid.width}x{game_info.pathing_grid.height}")
        print(f"start locations: {game_info.start_locations}")
        print()
        print(f"{'loop':>7} {'time':>7} {'own':>5} {'vis':>5} {'snap':>5} {'min':>6} {'gas':>6} {'supply':>8}")

        frames = 0
        captured: list[bytes] = []
        peak_enemy = 0
        started = time.monotonic()
        while frames < max_frames:
            result = await client.observation()
            obs = result.observation.observation
            loop = obs.game_loop

            if dump_dir is not None and frames % dump_every == 0:
                # result is the Response envelope; store the ResponseObservation itself
                # so the fixture loader doesn't need to know about the wrapper.
                captured.append(result.observation.SerializeToString())

            own = vis = snap = 0
            for u in obs.raw_data.units:
                if u.alliance == 1:  # Self
                    own += 1
                elif u.alliance == 4:  # Enemy
                    # display_type: 1 Visible, 2 Snapshot, 3 Hidden
                    if u.display_type == 1:
                        vis += 1
                    elif u.display_type == 2:
                        snap += 1

            peak_enemy = max(peak_enemy, vis + snap)
            c = obs.player_common
            if frames % 100 == 0:
                print(
                    f"{loop:>7} {loop / 22.4:>6.0f}s {own:>5} {vis:>5} {snap:>5} "
                    f"{c.minerals:>6} {c.vespene:>6} {c.food_used:>3}/{c.food_cap:<4}"
                )

            frames += 1
            if result.observation.player_result:
                print(f"\ngame over at loop {loop}: {result.observation.player_result}")
                break

            await client.step(sample_loops)

        elapsed = time.monotonic() - started
        print(f"\n{frames} frames in {elapsed:.1f}s  ({frames / elapsed:.1f} frames/sec)")
        print(f"peak enemy units seen in one frame: {peak_enemy}")

        if dump_dir is not None:
            dump_dir.mkdir(parents=True, exist_ok=True)
            write_records(dump_dir / "observations.pb.gz", captured)
            write_records(dump_dir / "game_info.pb.gz", [game_info._proto.SerializeToString()])
            print(f"fixture: {len(captured)} observations -> {dump_dir}")
        return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("replay", type=Path)
    ap.add_argument("--player", type=int, default=2, help="observed player id (bot)")
    ap.add_argument("--sample-loops", type=int, default=4)
    ap.add_argument("--max-frames", type=int, default=100, help="stop early; spike only")
    ap.add_argument("--pin-version", action="store_true", help="pin SC2 to the replay's build")
    ap.add_argument("--dump-fixture", type=Path, default=None, help="write captured observations here")
    ap.add_argument("--dump-every", type=int, default=76, help="capture 1 in N frames")
    args = ap.parse_args()

    replay = args.replay.resolve()
    if not replay.exists():
        sys.exit(f"not found: {replay}")

    asyncio.run(step_replay(replay, args.player, args.sample_loops, args.max_frames, args.pin_version,
                            args.dump_fixture, args.dump_every))


if __name__ == "__main__":
    main()
