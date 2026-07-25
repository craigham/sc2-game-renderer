from s2clientprotocol import sc2api_pb2

from sc2_game_renderer.enemy_memory import EnemyMemory
from sc2_game_renderer.frame import frame_from_observation
from sc2_game_renderer.frame_file import ExtractedFrame, FrameFileReader, GameHeader, write_frame_file

from .fixture_io import FIXTURES_DIR, read_records


def _load_observations():
    return list(
        read_records(FIXTURES_DIR / "4891371" / "observations.pb.gz", sc2api_pb2.ResponseObservation)
    )


def _load_game_info():
    return next(
        read_records(FIXTURES_DIR / "4891371" / "game_info.pb.gz", sc2api_pb2.ResponseGameInfo)
    )


def _extracted_frames():
    """Real extraction pipeline: observation -> Frame -> memory-aware ExtractedFrame,
    same wiring the extract CLI does, over the whole fixture in game-loop order."""
    memory = EnemyMemory(ttl_seconds=60.0)
    for obs in _load_observations():
        frame = frame_from_observation(obs)
        memory.update(frame)
        yield ExtractedFrame(frame=frame, remembered_enemies=tuple(memory.remembered(frame.game_loop)))


def test_header_from_game_info_matches_known_fixture_values():
    header = GameHeader.from_game_info(
        _load_game_info(), bot_player_id=2, sample_loops=4, memory_ttl_seconds=60.0
    )
    assert header.map_name == "Ultralove AIE"
    assert (header.map_width, header.map_height) == (184, 184)
    assert header.playable_area == (26, 26, 158, 158)
    assert header.start_locations == ((141.5, 137.5),)
    assert header.pathing_grid.width == 184
    assert header.pathing_grid.bits_per_pixel == 1
    assert header.terrain_height.bits_per_pixel == 8
    assert header.bot_player_id == 2


def test_round_trip_preserves_header(tmp_path):
    header = GameHeader.from_game_info(
        _load_game_info(), bot_player_id=2, sample_loops=4, memory_ttl_seconds=60.0
    )
    out = tmp_path / "test.frames.jsonl.gz"
    write_frame_file(out, header, [])

    with FrameFileReader(out) as reader:
        assert reader.header == header


def test_round_trip_preserves_every_frame_exactly(tmp_path):
    header = GameHeader.from_game_info(
        _load_game_info(), bot_player_id=2, sample_loops=4, memory_ttl_seconds=60.0
    )
    original = list(_extracted_frames())
    out = tmp_path / "test.frames.jsonl.gz"

    written_count = write_frame_file(out, header, original)
    assert written_count == len(original) == 51

    with FrameFileReader(out) as reader:
        round_tripped = list(reader)

    assert round_tripped == original


def test_round_trip_preserves_remembered_enemies(tmp_path):
    """The whole point of routing through EnemyMemory during extraction: the
    'remembered' category must survive the round trip, not just visible/snapshot."""
    header = GameHeader.from_game_info(
        _load_game_info(), bot_player_id=2, sample_loops=4, memory_ttl_seconds=60.0
    )
    original = list(_extracted_frames())
    frames_with_memory = [ef for ef in original if ef.remembered_enemies]
    assert frames_with_memory, "fixture should exercise the memory tracker at least once"

    out = tmp_path / "test.frames.jsonl.gz"
    write_frame_file(out, header, original)

    with FrameFileReader(out) as reader:
        round_tripped = {ef.frame.game_loop: ef for ef in reader}

    for ef in frames_with_memory:
        restored = round_tripped[ef.frame.game_loop]
        assert restored.remembered_enemies == ef.remembered_enemies


def test_reader_is_a_streaming_iterator_not_a_list(tmp_path):
    header = GameHeader.from_game_info(
        _load_game_info(), bot_player_id=2, sample_loops=4, memory_ttl_seconds=60.0
    )
    out = tmp_path / "test.frames.jsonl.gz"
    write_frame_file(out, header, _extracted_frames())

    with FrameFileReader(out) as reader:
        first = next(iter(reader))
        assert first.frame.game_loop == 0
