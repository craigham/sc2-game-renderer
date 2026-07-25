from sc2_game_renderer.enemy_memory import EnemyMemory
from sc2_game_renderer.frame import Frame, UnitSnapshot

LOOPS_PER_SECOND = 22.4


def _unit(tag: int, x: float = 10.0, y: float = 20.0) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag, unit_type=48, x=x, y=y,
        health=45.0, health_max=45.0, shield=0.0, shield_max=0.0, energy=0.0, energy_max=0.0,
        orders=(),
    )


def _frame(loop: int, enemy_visible: tuple[UnitSnapshot, ...] = (), enemy_snapshot: tuple[UnitSnapshot, ...] = ()) -> Frame:
    return Frame(
        game_loop=loop,
        own_units=(),
        enemy_visible=enemy_visible,
        enemy_snapshot=enemy_snapshot,
        minerals=0, vespene=0, minerals_rate=0.0, vespene_rate=0.0,
        supply_used=0, supply_cap=0, supply_army=0, supply_workers=0, idle_worker_count=0,
        supply_blocked=False,
        army_value_minerals=0, army_value_vespene=0,
    )


def test_unit_never_seen_is_not_remembered():
    memory = EnemyMemory()
    memory.update(_frame(0))
    assert memory.remembered(0) == []


def test_visible_unit_is_not_remembered_while_still_visible():
    memory = EnemyMemory()
    zealot = _unit(tag=1)
    memory.update(_frame(0, enemy_visible=(zealot,)))
    assert memory.remembered(0) == []


def test_unit_lost_from_vision_becomes_remembered():
    memory = EnemyMemory()
    zealot = _unit(tag=1, x=15.0, y=25.0)
    memory.update(_frame(loop=0, enemy_visible=(zealot,)))
    memory.update(_frame(loop=44))  # ~2s later, no longer visible

    remembered = memory.remembered(current_loop=44)
    assert len(remembered) == 1
    assert remembered[0].unit.tag == 1
    assert remembered[0].unit.x == 15.0
    assert remembered[0].unit.y == 25.0
    assert remembered[0].last_seen_loop == 0


def test_remembered_age_seconds_computed_from_last_seen_loop():
    memory = EnemyMemory()
    memory.update(_frame(loop=0, enemy_visible=(_unit(tag=1),)))
    memory.update(_frame(loop=224))  # exactly 10 game-seconds later

    entry = memory.remembered(current_loop=224)[0]
    assert entry.age_seconds(224) == 10.0


def test_last_seen_loop_does_not_advance_while_still_out_of_vision():
    memory = EnemyMemory()
    memory.update(_frame(loop=0, enemy_visible=(_unit(tag=1),)))
    memory.update(_frame(loop=44))
    memory.update(_frame(loop=88))  # still not seen — must not look "freshly lost"

    entry = memory.remembered(current_loop=88)[0]
    assert entry.last_seen_loop == 0


def test_resighting_removes_unit_from_memory():
    memory = EnemyMemory()
    zealot = _unit(tag=1)
    memory.update(_frame(loop=0, enemy_visible=(zealot,)))
    memory.update(_frame(loop=44))  # lost
    assert len(memory.remembered(44)) == 1

    memory.update(_frame(loop=88, enemy_visible=(zealot,)))  # re-sighted
    assert memory.remembered(88) == []


def test_resighting_at_new_position_then_losing_again_uses_updated_position():
    memory = EnemyMemory()
    memory.update(_frame(loop=0, enemy_visible=(_unit(tag=1, x=10.0, y=10.0),)))
    memory.update(_frame(loop=44))  # lost at (10, 10)
    memory.update(_frame(loop=88, enemy_visible=(_unit(tag=1, x=50.0, y=60.0),)))  # resighted, moved
    memory.update(_frame(loop=132))  # lost again

    entry = memory.remembered(132)[0]
    assert (entry.unit.x, entry.unit.y) == (50.0, 60.0)
    assert entry.last_seen_loop == 88


def test_becoming_a_snapshot_removes_unit_from_memory():
    """A unit that goes from visible -> memory -> SC2 snapshot (e.g. it's a structure
    the bot lost vision of and SC2 now remembers itself) must not be double-tracked."""
    memory = EnemyMemory()
    structure = _unit(tag=1)
    memory.update(_frame(loop=0, enemy_visible=(structure,)))
    memory.update(_frame(loop=44))  # briefly out of vision, we remember it
    assert len(memory.remembered(44)) == 1

    memory.update(_frame(loop=88, enemy_snapshot=(structure,)))  # SC2 now snapshots it
    assert memory.remembered(88) == []


def test_entry_expires_after_ttl():
    memory = EnemyMemory(ttl_seconds=60.0)
    memory.update(_frame(loop=0, enemy_visible=(_unit(tag=1),)))
    just_under_ttl = round(59 * LOOPS_PER_SECOND)
    just_over_ttl = round(61 * LOOPS_PER_SECOND)

    memory.update(_frame(loop=just_under_ttl))
    assert len(memory.remembered(just_under_ttl)) == 1

    memory.update(_frame(loop=just_over_ttl))
    assert memory.remembered(just_over_ttl) == []


def test_remembered_sorted_oldest_first():
    memory = EnemyMemory()
    memory.update(_frame(loop=0, enemy_visible=(_unit(tag=1), _unit(tag=2))))
    memory.update(_frame(loop=22))  # tag 1 lost at loop 0... both lost together here
    # Lose them at different times: reintroduce tag 2, then drop it later.
    memory.update(_frame(loop=44, enemy_visible=(_unit(tag=2),)))
    memory.update(_frame(loop=66))  # tag 2 now lost at loop 44; tag 1 still lost since loop 0

    remembered = memory.remembered(66)
    assert [e.unit.tag for e in remembered] == [1, 2]


def test_multiple_units_tracked_independently():
    memory = EnemyMemory()
    memory.update(_frame(loop=0, enemy_visible=(_unit(tag=1), _unit(tag=2), _unit(tag=3))))
    memory.update(_frame(loop=44, enemy_visible=(_unit(tag=2),)))  # 1 and 3 lost

    tags = {e.unit.tag for e in memory.remembered(44)}
    assert tags == {1, 3}
