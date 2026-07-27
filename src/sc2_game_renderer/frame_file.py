"""On-disk frame file format: extract's output, render's input.

Gzipped JSONL. First line is a header record (map/terrain, once); every line after is
one sampled frame. Everything the render stage needs lives in this file — it never
touches SC2, a replay, or game_info again (see docs/SPEC.md § Architecture).
"""

import base64
import dataclasses
import gzip
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np
from s2clientprotocol import common_pb2, sc2api_pb2

from sc2_game_renderer.enemy_memory import RememberedEnemy
from sc2_game_renderer.frame import Frame, UnitOrder, UnitSnapshot

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
class OpponentInfo:
    race: str  # "Terran" / "Zerg" / "Protoss" / "Random" / "NoRace"
    player_type: str  # "Participant" / "Computer" / "Observer"
    # Only ever meaningful (and only ever set) for a Computer opponent — a real
    # player/bot has no "difficulty". Distinguished via the proto's own field
    # presence (HasField), not by treating an unset value as a guessed default:
    # difficulty/ai_build's zero-values (VeryEasy=1, RandomBuild=1) aren't 0, so an
    # absent field can't be told apart from a genuinely-set first value any other way.
    difficulty: str | None
    ai_build: str | None
    name: str  # often empty — confirmed on a real ladder match (privacy, presumably)

    @classmethod
    def from_player_info(cls, p) -> "OpponentInfo":
        return cls(
            race=common_pb2.Race.Name(p.race_actual),
            player_type=sc2api_pb2.PlayerType.Name(p.type),
            difficulty=sc2api_pb2.Difficulty.Name(p.difficulty) if p.HasField("difficulty") else None,
            ai_build=sc2api_pb2.AIBuild.Name(p.ai_build) if p.HasField("ai_build") else None,
            name=p.player_name,
        )

    def describe(self) -> str:
        """'vs Terran' for a real opponent; 'vs Zerg (VeryHard, Rush AI)' for a
        Blizzard AI one. Mirrors viewer.js's describeOpponent — kept in sync by hand,
        since one's JS and one's Python."""
        text = f"vs {self.race}"
        if self.player_type == "Computer":
            parts = [p for p in (self.difficulty, f"{self.ai_build} AI" if self.ai_build else None) if p]
            if parts:
                text += f" ({', '.join(parts)})"
        return text


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
    opponent: OpponentInfo

    @classmethod
    def from_game_info(cls, game_info, *, bot_player_id: int, sample_loops: int, memory_ttl_seconds: float) -> "GameHeader":
        sr = game_info.start_raw
        opponent_pb = next(p for p in game_info.player_info if p.player_id != bot_player_id)
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
            opponent=OpponentInfo.from_player_info(opponent_pb),
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


def _order_from_dict(d: dict) -> UnitOrder:
    target_pos = d["target_pos"]
    return UnitOrder(
        ability_id=d["ability_id"],
        target_unit_tag=d["target_unit_tag"],
        target_pos=tuple(target_pos) if target_pos is not None else None,
        progress=d["progress"],
    )


def _unit_from_dict(d: dict) -> UnitSnapshot:
    d = dict(d)
    d["orders"] = tuple(_order_from_dict(o) for o in d["orders"])
    return UnitSnapshot(**d)


def _header_from_dict(d: dict) -> GameHeader:
    d = dict(d)
    d.pop("kind", None)
    d["playable_area"] = tuple(d["playable_area"])
    d["start_locations"] = tuple(tuple(p) for p in d["start_locations"])
    d["pathing_grid"] = TerrainGrid(**d["pathing_grid"])
    d["placement_grid"] = TerrainGrid(**d["placement_grid"])
    d["terrain_height"] = TerrainGrid(**d["terrain_height"])
    d["opponent"] = OpponentInfo(**d["opponent"])
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


def _header_record(header: GameHeader) -> dict:
    return {"kind": "header", **dataclasses.asdict(header)}


def _frame_record(ef: ExtractedFrame) -> dict:
    return {
        "kind": "frame",
        **dataclasses.asdict(ef.frame),
        "remembered_enemies": [
            {"unit": dataclasses.asdict(r.unit), "last_seen_loop": r.last_seen_loop}
            for r in ef.remembered_enemies
        ],
    }


def write_frame_file(path: Path, header: GameHeader, frames: Iterable[ExtractedFrame]) -> int:
    """Streams `frames` straight to disk — never holds the whole game in memory."""
    count = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps(_header_record(header)) + "\n")
        for ef in frames:
            f.write(json.dumps(_frame_record(ef)) + "\n")
            count += 1
    return count


class FrameFileWriter:
    """Streaming writer that lets a frame file be watched while it's still being
    extracted, instead of only once the whole replay has been stepped.

    Frames land in a plain, uncompressed `<path>.tmp` as they're written, flushed
    after every single write — so the file on disk always ends on a complete line,
    and a concurrent reader can safely serve it up to whatever the current size is
    at any moment, no byte-offset bookkeeping required. A `<path>.progress.json`
    sidecar (rewritten at most twice a second, not every frame) records the frame
    count and done/error state, so a consumer (e.g. a web server polling for "is
    there more yet") doesn't have to open the growing frame file itself just to
    answer that.

    On a clean exit, the accumulated file is compressed into `path` itself — the
    exact same frames.jsonl.gz format write_frame_file/FrameFileReader already
    produce and consume, so nothing downstream changes for the finished case. On
    an exception, whatever was captured so far is still compressed and kept (a
    crash partway through a game leaves a valid, playable partial replay, not
    nothing) and the sidecar is left with done=False, error=<message>; the
    exception itself is not suppressed.

        with FrameFileWriter(path, header) as w:
            for ef in frames:
                w.write(ef)
    """

    _PROGRESS_UPDATE_INTERVAL = 0.5  # seconds — throttles sidecar rewrites, not the frame writes themselves

    def __init__(self, path: Path, header: GameHeader):
        self._path = Path(path)
        self._tmp_path = Path(str(self._path) + ".tmp")
        self._progress_path = Path(str(self._path) + ".progress.json")
        self._header = header
        self._count = 0
        self._f = None
        self._last_progress_write = 0.0

    def __enter__(self) -> "FrameFileWriter":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self._tmp_path, "w", encoding="utf-8")
        self._f.write(json.dumps(_header_record(self._header)) + "\n")
        self._f.flush()
        self._write_progress(done=False, error=None)
        self._last_progress_write = time.monotonic()
        return self

    def write(self, ef: ExtractedFrame) -> None:
        self._f.write(json.dumps(_frame_record(ef)) + "\n")
        self._f.flush()
        self._count += 1
        now = time.monotonic()
        if now - self._last_progress_write >= self._PROGRESS_UPDATE_INTERVAL:
            self._write_progress(done=False, error=None)
            self._last_progress_write = now

    def __exit__(self, exc_type, exc, tb) -> None:
        self._f.close()
        try:
            with open(self._tmp_path, encoding="utf-8") as src, gzip.open(self._path, "wt", encoding="utf-8") as dst:
                shutil.copyfileobj(src, dst)
        finally:
            self._tmp_path.unlink(missing_ok=True)
        self._write_progress(done=exc_type is None, error=None if exc_type is None else str(exc))

    def _write_progress(self, *, done: bool, error: str | None) -> None:
        tmp = Path(str(self._progress_path) + ".tmp")
        tmp.write_text(json.dumps({"frames_written": self._count, "done": done, "error": error}))
        tmp.replace(self._progress_path)


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
