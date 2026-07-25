from s2clientprotocol import sc2api_pb2

from sc2_game_renderer.frame import frame_from_observation

from .fixture_io import FIXTURES_DIR, read_records


def _load_observations():
    return list(
        read_records(FIXTURES_DIR / "4891371" / "observations.pb.gz", sc2api_pb2.ResponseObservation)
    )


def test_fixture_has_expected_frame_count():
    assert len(_load_observations()) == 51


def test_known_frame_matches_documented_values():
    # Frame 42, game loop 12768 — documented in tests/fixtures/README.md.
    obs = _load_observations()[42]
    frame = frame_from_observation(obs)

    assert frame.game_loop == 12768
    assert len(frame.own_units) == 108
    assert len(frame.enemy_visible) == 42
    assert len(frame.enemy_snapshot) == 27
    assert frame.minerals == 125
    assert frame.supply_used == 81
    assert frame.supply_cap == 118


def test_own_units_exclude_enemy_and_neutral():
    frame = frame_from_observation(_load_observations()[42])
    # 108 self + 42 enemy-visible + 27 enemy-snapshot were counted directly off the
    # proto; neutral (mineral fields, etc.) must not leak into any of these buckets.
    own_tags = {u.tag for u in frame.own_units}
    enemy_tags = {u.tag for u in frame.enemy_visible} | {u.tag for u in frame.enemy_snapshot}
    assert own_tags.isdisjoint(enemy_tags)


def test_unit_snapshot_fields_are_populated():
    frame = frame_from_observation(_load_observations()[42])
    u = frame.own_units[0]
    assert u.tag != 0
    assert u.unit_type != 0
    assert u.health > 0
    assert u.health_max >= u.health
    # position is inside the map, not left at the zero default
    assert 0 < u.x < 200
    assert 0 < u.y < 200


def test_army_value_and_supply_derived_fields():
    frame = frame_from_observation(_load_observations()[42])
    assert frame.army_value_minerals == 1900
    assert frame.army_value_vespene == 475
    assert frame.supply_blocked is False


def test_supply_blocked_true_when_at_cap_below_200():
    obs = _load_observations()[42]
    obs.observation.player_common.food_used = obs.observation.player_common.food_cap
    frame = frame_from_observation(obs)
    assert frame.supply_blocked is True


def test_supply_blocked_false_at_the_200_hard_cap():
    obs = _load_observations()[42]
    obs.observation.player_common.food_cap = 200
    obs.observation.player_common.food_used = 200
    frame = frame_from_observation(obs)
    assert frame.supply_blocked is False


def test_supply_blocked_false_when_wiped_out_at_zero_zero():
    """A defeated player with no supply structures left reads 0/0. food_used(0) >=
    food_cap(0) would naively read as blocked, but there's nothing to be blocked on —
    found by eye in the slice 7 HUD preview at the fixture's final frame."""
    obs = _load_observations()[42]
    obs.observation.player_common.food_cap = 0
    obs.observation.player_common.food_used = 0
    frame = frame_from_observation(obs)
    assert frame.supply_blocked is False


def test_first_and_last_frame_loops_match_fixture_readme():
    observations = _load_observations()
    assert observations[0].observation.game_loop == 0
    assert observations[-1].observation.game_loop == 15200


def test_frame_from_observation_is_a_pure_function():
    obs = _load_observations()[42]
    a = frame_from_observation(obs)
    b = frame_from_observation(obs)
    assert a == b
