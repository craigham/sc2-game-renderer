from sc2_game_renderer.frame import Frame
from sc2_game_renderer.supply_block_tracker import SupplyBlockTracker


def _frame(loop: int, supply_blocked: bool) -> Frame:
    return Frame(
        game_loop=loop,
        own_units=(), enemy_visible=(), enemy_snapshot=(),
        minerals=0, vespene=0, minerals_rate=0.0, vespene_rate=0.0,
        supply_used=0, supply_cap=0, supply_army=0, supply_workers=0, idle_worker_count=0,
        supply_blocked=supply_blocked,
        army_value_minerals=0, army_value_vespene=0,
    )


def test_not_blocked_returns_zero():
    tracker = SupplyBlockTracker()
    assert tracker.update(_frame(0, supply_blocked=False)) == 0.0


def test_freshly_blocked_frame_returns_zero_duration():
    tracker = SupplyBlockTracker()
    assert tracker.update(_frame(100, supply_blocked=True)) == 0.0


def test_duration_grows_across_consecutive_blocked_frames():
    tracker = SupplyBlockTracker()
    tracker.update(_frame(0, supply_blocked=True))
    tracker.update(_frame(112, supply_blocked=True))  # 5s later
    duration = tracker.update(_frame(224, supply_blocked=True))  # 10s later
    assert duration == 10.0


def test_unblocking_resets_duration():
    tracker = SupplyBlockTracker()
    tracker.update(_frame(0, supply_blocked=True))
    tracker.update(_frame(224, supply_blocked=True))  # blocked 10s
    assert tracker.update(_frame(228, supply_blocked=False)) == 0.0

    # blocking again afterwards starts a fresh count, not a continuation
    assert tracker.update(_frame(232, supply_blocked=True)) == 0.0


def test_two_separate_blocked_periods_are_independent():
    tracker = SupplyBlockTracker()
    tracker.update(_frame(0, supply_blocked=True))
    tracker.update(_frame(112, supply_blocked=True))  # 5s blocked
    tracker.update(_frame(156, supply_blocked=False))  # unblocked
    tracker.update(_frame(200, supply_blocked=True))  # new block starts
    duration = tracker.update(_frame(312, supply_blocked=True))  # 5s into new block
    assert duration == 5.0
