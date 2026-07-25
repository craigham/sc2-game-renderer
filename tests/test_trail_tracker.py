from sc2_game_renderer.frame import Frame, UnitSnapshot
from sc2_game_renderer.trail_tracker import TrailTracker


def _unit(tag: int, x: float, y: float) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag, unit_type=48, x=x, y=y,
        health=45.0, health_max=45.0, shield=0.0, shield_max=0.0, energy=0.0, energy_max=0.0,
        orders=(),
    )


def _frame(loop: int, own_units: tuple[UnitSnapshot, ...] = ()) -> Frame:
    return Frame(
        game_loop=loop,
        own_units=own_units,
        enemy_visible=(), enemy_snapshot=(),
        minerals=0, vespene=0, minerals_rate=0.0, vespene_rate=0.0,
        supply_used=0, supply_cap=0, supply_army=0, supply_workers=0, idle_worker_count=0,
        supply_blocked=False,
        army_value_minerals=0, army_value_vespene=0,
    )


def test_new_unit_starts_a_one_point_trail():
    tracker = TrailTracker()
    tracker.update(_frame(0, own_units=(_unit(1, 10.0, 20.0),)))
    assert tracker.trails() == {1: [(10.0, 20.0)]}


def test_consecutive_frames_append_to_the_trail():
    tracker = TrailTracker()
    tracker.update(_frame(0, own_units=(_unit(1, 10.0, 20.0),)))
    tracker.update(_frame(4, own_units=(_unit(1, 11.0, 20.0),)))
    tracker.update(_frame(8, own_units=(_unit(1, 12.0, 20.0),)))
    assert tracker.trails()[1] == [(10.0, 20.0), (11.0, 20.0), (12.0, 20.0)]


def test_trail_length_is_capped_dropping_oldest_first():
    tracker = TrailTracker(max_length=3)
    for i in range(5):
        tracker.update(_frame(i * 4, own_units=(_unit(1, float(i), 0.0),)))
    assert tracker.trails()[1] == [(2.0, 0.0), (3.0, 0.0), (4.0, 0.0)]


def test_unit_missing_from_a_frame_drops_its_trail_entirely():
    tracker = TrailTracker()
    tracker.update(_frame(0, own_units=(_unit(1, 10.0, 20.0),)))
    tracker.update(_frame(4, own_units=()))  # died
    assert tracker.trails() == {}


def test_reappearing_tag_starts_a_fresh_trail_not_a_continuation():
    tracker = TrailTracker()
    tracker.update(_frame(0, own_units=(_unit(1, 10.0, 20.0),)))
    tracker.update(_frame(4, own_units=()))  # gap
    tracker.update(_frame(8, own_units=(_unit(1, 99.0, 99.0),)))  # same tag returns
    assert tracker.trails()[1] == [(99.0, 99.0)]


def test_multiple_units_tracked_independently():
    tracker = TrailTracker()
    tracker.update(_frame(0, own_units=(_unit(1, 0.0, 0.0), _unit(2, 5.0, 5.0))))
    tracker.update(_frame(4, own_units=(_unit(1, 1.0, 0.0), _unit(2, 6.0, 5.0))))
    trails = tracker.trails()
    assert trails[1] == [(0.0, 0.0), (1.0, 0.0)]
    assert trails[2] == [(5.0, 5.0), (6.0, 5.0)]


def test_empty_before_any_update():
    tracker = TrailTracker()
    assert tracker.trails() == {}
