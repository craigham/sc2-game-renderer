"""Pure mapping from an SC2 observation proto to our own Frame model.

No SC2 client, no I/O. Input is a `ResponseObservation` as returned by
`Client.observation()` (see scripts/spike_step_replay.py) — either live or read back
from a captured fixture.
"""

from dataclasses import dataclass

from s2clientprotocol import raw_pb2, sc2api_pb2


@dataclass(frozen=True, slots=True)
class UnitOrder:
    ability_id: int
    target_unit_tag: int | None
    target_pos: tuple[float, float] | None
    progress: float


@dataclass(frozen=True, slots=True)
class UnitSnapshot:
    tag: int
    unit_type: int
    x: float
    y: float
    health: float
    health_max: float
    shield: float
    shield_max: float
    energy: float
    energy_max: float
    # SC2 only ever populates orders for the observing player's own units — an enemy
    # unit's queued order is exactly the kind of intel fog is supposed to hide, and
    # this was confirmed against the fixture (0 of 69 enemy units had any order vs.
    # 81 of 108 own units). So this is always empty for enemy_visible/enemy_snapshot;
    # kept as one uniform shape rather than a separate own-only type.
    orders: tuple[UnitOrder, ...]


@dataclass(frozen=True, slots=True)
class Frame:
    game_loop: int

    own_units: tuple[UnitSnapshot, ...]
    enemy_visible: tuple[UnitSnapshot, ...]
    # Enemy structures SC2 itself remembers through fog (display_type == Snapshot).
    # Mobile enemy units have no equivalent — see the memory tracker (frame_memory.py).
    enemy_snapshot: tuple[UnitSnapshot, ...]

    minerals: int
    vespene: int
    minerals_rate: float
    vespene_rate: float

    supply_used: int
    supply_cap: int
    supply_army: int
    supply_workers: int
    idle_worker_count: int
    # True when the bot cannot produce anything supply-gated right now. Whether this
    # has persisted across frames (block *duration*) is a render-layer concern — it
    # needs the frame sequence, not a single observation.
    supply_blocked: bool

    # Current worth of the live army, in resources: SC2's own running "used" tally
    # (spent minus lost), the same figure the client's built-in graphs use — not a
    # recomputation from unit type costs.
    army_value_minerals: int
    army_value_vespene: int


def _order(o: raw_pb2.UnitOrder) -> UnitOrder:
    which = o.WhichOneof("target")
    return UnitOrder(
        ability_id=o.ability_id,
        target_unit_tag=o.target_unit_tag if which == "target_unit_tag" else None,
        target_pos=(o.target_world_space_pos.x, o.target_world_space_pos.y) if which == "target_world_space_pos" else None,
        progress=o.progress,
    )


def _unit(u: raw_pb2.Unit) -> UnitSnapshot:
    return UnitSnapshot(
        tag=u.tag,
        unit_type=u.unit_type,
        x=u.pos.x,
        y=u.pos.y,
        health=u.health,
        health_max=u.health_max,
        shield=u.shield,
        shield_max=u.shield_max,
        energy=u.energy,
        energy_max=u.energy_max,
        orders=tuple(_order(o) for o in u.orders),
    )


def frame_from_observation(response_observation: sc2api_pb2.ResponseObservation) -> Frame:
    obs = response_observation.observation

    own: list[UnitSnapshot] = []
    enemy_visible: list[UnitSnapshot] = []
    enemy_snapshot: list[UnitSnapshot] = []
    for u in obs.raw_data.units:
        if u.alliance == raw_pb2.Self:
            own.append(_unit(u))
        elif u.alliance == raw_pb2.Enemy:
            if u.display_type == raw_pb2.Visible:
                enemy_visible.append(_unit(u))
            elif u.display_type == raw_pb2.Snapshot:
                enemy_snapshot.append(_unit(u))

    pc = obs.player_common
    sd = obs.score.score_details

    return Frame(
        game_loop=obs.game_loop,
        own_units=tuple(own),
        enemy_visible=tuple(enemy_visible),
        enemy_snapshot=tuple(enemy_snapshot),
        minerals=pc.minerals,
        vespene=pc.vespene,
        minerals_rate=sd.collection_rate_minerals,
        vespene_rate=sd.collection_rate_vespene,
        supply_used=pc.food_used,
        supply_cap=pc.food_cap,
        supply_army=pc.food_army,
        supply_workers=pc.food_workers,
        idle_worker_count=pc.idle_worker_count,
        # food_cap > 0 excludes a wiped-out player (0/0): with no supply structures
        # left at all, "blocked" is meaningless — there's nothing to be blocked on.
        supply_blocked=0 < pc.food_cap < 200 and pc.food_used >= pc.food_cap,
        army_value_minerals=round(sd.used_minerals.army),
        army_value_vespene=round(sd.used_vespene.army),
    )
