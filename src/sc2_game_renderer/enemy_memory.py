"""Tracks enemy units the bot has seen but no longer has vision of.

SC2 does this for us for structures (display_type == Snapshot, see frame.py). For
mobile units it does nothing — a unit that leaves vision simply disappears from the
observation. This module is what makes "last known position" possible for those.

Pure and stateful: call `update()` once per sampled frame, in game-loop order. No SC2,
no I/O.
"""

from dataclasses import dataclass

from sc2_game_renderer.frame import Frame, UnitSnapshot

LOOPS_PER_SECOND = 22.4


@dataclass(frozen=True, slots=True)
class RememberedEnemy:
    unit: UnitSnapshot
    last_seen_loop: int

    def age_seconds(self, current_loop: int) -> float:
        return (current_loop - self.last_seen_loop) / LOOPS_PER_SECOND


class EnemyMemory:
    """`enemy_tag -> RememberedEnemy` for enemy units currently out of vision.

    A unit enters memory the moment it's no longer in `enemy_visible` for a frame
    where it previously was. It leaves memory when re-sighted (it belongs in the
    frame's own `enemy_visible`/`enemy_snapshot` then, not here) or when its entry
    exceeds `ttl_seconds`.
    """

    def __init__(self, ttl_seconds: float = 60.0):
        self.ttl_seconds = ttl_seconds
        self._by_tag: dict[int, RememberedEnemy] = {}
        self._last_visible_units: dict[int, UnitSnapshot] = {}
        self._last_visible_loop: int = 0

    def update(self, frame: Frame) -> None:
        visible_tags = {u.tag for u in frame.enemy_visible}
        snapshot_tags = {u.tag for u in frame.enemy_snapshot}
        now_known_tags = visible_tags | snapshot_tags

        # Drop anything re-sighted, expired, or otherwise stale before considering
        # this frame's newly-lost units — re-sighted units must not still be
        # reported as remembered below.
        for tag in list(self._by_tag):
            entry = self._by_tag[tag]
            if tag in now_known_tags or entry.age_seconds(frame.game_loop) > self.ttl_seconds:
                del self._by_tag[tag]

        # Units visible last update but not this one start being remembered here.
        # (Enemy structures never need this — they get an SC2 snapshot instead — but
        # a unit already present with a snapshot entry this frame was excluded above,
        # so no double-bookkeeping.)
        newly_lost = self._last_visible_units.keys() - now_known_tags
        for tag in newly_lost:
            self._by_tag[tag] = RememberedEnemy(
                unit=self._last_visible_units[tag], last_seen_loop=self._last_visible_loop
            )

        self._last_visible_units = {u.tag: u for u in frame.enemy_visible}
        self._last_visible_loop = frame.game_loop

    def remembered(self, current_loop: int) -> list[RememberedEnemy]:
        """Enemies out of vision right now, still within TTL, oldest first."""
        return sorted(self._by_tag.values(), key=lambda e: e.last_seen_loop)
