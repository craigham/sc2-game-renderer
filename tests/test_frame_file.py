from s2clientprotocol import common_pb2, sc2api_pb2

from sc2_game_renderer.enemy_memory import EnemyMemory
from sc2_game_renderer.frame import frame_from_observation
from sc2_game_renderer.frame_file import (
    ExtractedFrame,
    FrameFileReader,
    GameHeader,
    OpponentInfo,
    write_frame_file,
)

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


# --- opponent info -------------------------------------------------------------------

def test_opponent_info_for_a_real_participant_match():
    # The fixture is a genuine ladder match (bot vs. another real bot, not Blizzard
    # AI) — difficulty/ai_build are only ever meaningful for a Computer opponent, so
    # both should read as None here rather than a misleading guessed default.
    header = GameHeader.from_game_info(
        _load_game_info(), bot_player_id=2, sample_loops=4, memory_ttl_seconds=60.0
    )
    assert header.opponent.race == "Terran"
    assert header.opponent.player_type == "Participant"
    assert header.opponent.difficulty is None
    assert header.opponent.ai_build is None
    assert header.opponent.name == ""  # not populated on this real match


def test_opponent_info_reads_difficulty_and_ai_build_for_a_computer_opponent():
    # Synthetic: HasField's "unset" distinction can't be exercised by the real
    # fixture (it's not a vs-Blizzard-AI match), so build a PlayerInfo directly to
    # confirm the mechanism itself — that this is genuinely gated on the proto's own
    # field presence, not the numeric value (Difficulty/AIBuild's first values are
    # 1, not 0, so an unset field can't be told apart from "set to the first value"
    # any other way).
    p = sc2api_pb2.PlayerInfo(
        player_id=1,
        type=sc2api_pb2.Computer,
        race_actual=common_pb2.Zerg,
        difficulty=sc2api_pb2.VeryHard,
        ai_build=sc2api_pb2.Rush,
    )
    opponent = OpponentInfo.from_player_info(p)
    assert opponent.race == "Zerg"
    assert opponent.player_type == "Computer"
    assert opponent.difficulty == "VeryHard"
    assert opponent.ai_build == "Rush"


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
