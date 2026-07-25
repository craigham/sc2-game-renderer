"""On-disk frame file format: extract's output, render's input.

Gzipped JSONL. First line is a header record (map/terrain, once); every line after is
one sampled frame. Everything the render stage needs lives in this file — it never
touches SC2, a replay, or game_info again (see docs/SPEC.md § Architecture).
"""

import base64
import dataclasses
import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np

from sc2_game_renderer.enemy_memory import RememberedEnemy
from sc2_game_renderer.frame import Frame, UnitSnapshot

FORMAT_VERSION = 1


@dataclass(frozen=True, slots=True)
class TerrainGrid:
    width: int
    height: int
    bits_per_pixel: int
    data_base64: str

    @classmethod
    def from_proto(cls, image_data) -> "TerrainGrid":
        return cls(
            width=image_data.size.x,
            height=image_data.size.y,
            bits_per_pixel=image_data.bits_per_pixel,
            data_base64=base64.b64encode(image_data.data).decode("ascii"),
        )

    def to_numpy(self) -> np.ndarray:
        """Row-major, shape (height, width) — row index is world y, same convention
        as the vendored python-sc2 PixelMap this mirrors. 1bpp grids (pathing,
        placement) unpack to 0/1 per cell; 8bpp (terrain height) is already one byte
        per cell.
        """
        buf = np.frombuffer(base64.b64decode(self.data_base64), dtype=np.uint8)
        if self.bits_per_pixel == 1:
            buf = np.unpackbits(buf)
        return buf.reshape(self.height, self.width)


@dataclass(frozen=True, slots=True)
class GameHeader:
    format_version: int
    map_name: str
    map_width: int
    map_height: int
    playable_area: tuple[int, int, int, int]  # x0, y0, x1, y1
    start_locations: tuple[tuple[float, float], ...]
    pathing_grid: TerrainGrid
    placement_grid: TerrainGrid
    terrain_height: TerrainGrid
    bot_player_id: int
    sample_loops: int
    memory_ttl_seconds: float

    @classmethod
    def from_game_info(cls, game_info, *, bot_player_id: int, sample_loops: int, memory_ttl_seconds: float) -> "GameHeader":
        sr = game_info.start_raw
        return cls(
            format_version=FORMAT_VERSION,
            map_name=game_info.map_name,
            map_width=sr.map_size.x,
            map_height=sr.map_size.y,
            playable_area=(sr.playable_area.p0.x, sr.playable_area.p0.y, sr.playable_area.p1.x, sr.playable_area.p1.y),
            start_locations=tuple((p.x, p.y) for p in sr.start_locations),
            pathing_grid=TerrainGrid.from_proto(sr.pathing_grid),
            placement_grid=TerrainGrid.from_proto(sr.placement_grid),
            terrain_height=TerrainGrid.from_proto(sr.terrain_height),
            bot_player_id=bot_player_id,
            sample_loops=sample_loops,
            memory_ttl_seconds=memory_ttl_seconds,
        )


@dataclass(frozen=True, slots=True)
class ExtractedFrame:
    """A Frame plus the enemy-memory view for that same game loop.

    The memory tracker is stateful across the whole sequence, so it has to run
    during extraction, in order — not something render can reconstruct from a single
    frame record.
    """

    frame: Frame
    remembered_enemies: tuple[RememberedEnemy, ...]


def _unit_from_dict(d: dict) -> UnitSnapshot:
    return UnitSnapshot(**d)


def _header_from_dict(d: dict) -> GameHeader:
    d = dict(d)
    d.pop("kind", None)
    d["playable_area"] = tuple(d["playable_area"])
    d["start_locations"] = tuple(tuple(p) for p in d["start_locations"])
    d["pathing_grid"] = TerrainGrid(**d["pathing_grid"])
    d["placement_grid"] = TerrainGrid(**d["placement_grid"])
    d["terrain_height"] = TerrainGrid(**d["terrain_height"])
    return GameHeader(**d)


def _extracted_frame_from_dict(d: dict) -> ExtractedFrame:
    d = dict(d)
    d.pop("kind", None)
    remembered_raw = d.pop("remembered_enemies")
    d["own_units"] = tuple(_unit_from_dict(u) for u in d["own_units"])
    d["enemy_visible"] = tuple(_unit_from_dict(u) for u in d["enemy_visible"])
    d["enemy_snapshot"] = tuple(_unit_from_dict(u) for u in d["enemy_snapshot"])
    frame = Frame(**d)
    remembered = tuple(
        RememberedEnemy(unit=_unit_from_dict(r["unit"]), last_seen_loop=r["last_seen_loop"])
        for r in remembered_raw
    )
    return ExtractedFrame(frame=frame, remembered_enemies=remembered)


def write_frame_file(path: Path, header: GameHeader, frames: Iterable[ExtractedFrame]) -> int:
    """Streams `frames` straight to disk — never holds the whole game in memory."""
    count = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "header", **dataclasses.asdict(header)}) + "\n")
        for ef in frames:
            record = {
                "kind": "frame",
                **dataclasses.asdict(ef.frame),
                "remembered_enemies": [
                    {"unit": dataclasses.asdict(r.unit), "last_seen_loop": r.last_seen_loop}
                    for r in ef.remembered_enemies
                ],
            }
            f.write(json.dumps(record) + "\n")
            count += 1
    return count


class FrameFileReader:
    """Streaming reader — the header is available immediately, frames on iteration.

        with FrameFileReader(path) as r:
            r.header          # GameHeader
            for extracted in r:
                ...
    """

    def __init__(self, path: Path):
        self._path = path
        self._f = None
        self.header: GameHeader

    def __enter__(self) -> "FrameFileReader":
        self._f = gzip.open(self._path, "rt", encoding="utf-8")
        self.header = _header_from_dict(json.loads(self._f.readline()))
        return self

    def __exit__(self, *exc) -> None:
        if self._f is not None:
            self._f.close()

    def __iter__(self) -> Iterator[ExtractedFrame]:
        for line in self._f:
            yield _extracted_frame_from_dict(json.loads(line))
