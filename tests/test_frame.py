import pytest
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


# --- unit orders ("current command") ------------------------------------------------

def _own_unit(frame, tag: int):
    return next(u for u in frame.own_units if u.tag == tag)


def test_order_with_a_unit_target():
    frame = frame_from_observation(_load_observations()[42])
    order = _own_unit(frame, 4354473986).orders[0]
    assert order.ability_id == 295
    assert order.target_unit_tag == 4302569473
    assert order.target_pos is None


def test_order_with_a_world_position_target():
    frame = frame_from_observation(_load_observations()[42])
    order = _own_unit(frame, 4363124737).orders[0]
    assert order.ability_id == 522
    assert order.target_pos == (38.5, 60.5)
    assert order.target_unit_tag is None


def test_order_with_no_target_but_progress():
    # A construction-style order (e.g. building something) reports progress with
    # neither a unit nor a world-position target.
    frame = frame_from_observation(_load_observations()[42])
    order = _own_unit(frame, 4380164097).orders[0]
    assert order.ability_id == 560
    assert order.progress == pytest.approx(0.9875)
    assert order.target_unit_tag is None
    assert order.target_pos is None


def test_enemy_units_never_have_orders():
    """SC2 never populates orders for a unit you don't own — that would leak the
    opponent's intentions straight through fog. Confirmed on the real fixture: 0 of
    69 enemy units had any order, vs. 81 of 108 own units."""
    frame = frame_from_observation(_load_observations()[42])
    assert all(u.orders == () for u in frame.enemy_visible)
    assert all(u.orders == () for u in frame.enemy_snapshot)
    assert any(u.orders != () for u in frame.own_units)  # sanity: own units do have some


def test_idle_own_unit_has_no_orders():
    frame = frame_from_observation(_load_observations()[42])
    idle_units = [u for u in frame.own_units if u.orders == ()]
    assert idle_units  # 108 - 81 = 27 own units with no queued order, per the fixture


# --- radius / is_structure ----------------------------------------------------------

def test_radius_captured_from_observation():
    frame = frame_from_observation(_load_observations()[42])
    scv = _own_unit(frame, 4354473986)
    orbital = _own_unit(frame, 4347658241)
    assert scv.radius == pytest.approx(0.375)
    assert orbital.radius == pytest.approx(2.75)


def test_is_structure_false_by_default_with_no_classification_provided():
    # frame_from_observation's structure_type_ids defaults to empty — honest
    # "not classified" rather than a guess, since without it we have no authoritative
    # signal (radius/health alone would misclassify large non-structures).
    frame = frame_from_observation(_load_observations()[42])
    orbital = _own_unit(frame, 4347658241)  # a real building, radius 2.75
    assert orbital.is_structure is False


def test_is_structure_true_when_type_id_is_in_the_provided_set():
    # 45 is the SCV's own unit_type — using it here (not the real ORBITALCOMMAND id)
    # keeps this test about the classification mechanism, not real game data.
    frame = frame_from_observation(_load_observations()[42], structure_type_ids=frozenset({45}))
    scv = _own_unit(frame, 4354473986)
    orbital = _own_unit(frame, 4347658241)
    assert scv.is_structure is True  # unit_type 45 is in the provided set
    assert orbital.is_structure is False  # unit_type 132 is not
