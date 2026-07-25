"""Tracks how long supply has been continuously blocked.

`Frame.supply_blocked` (frame.py) is true/false for a single observation — whether
it's a fresh block or one that's persisted for five minutes needs the frame sequence,
so it's computed here at render time, the same reasoning as trail_tracker.py.
"""

from sc2_game_renderer.frame import Frame

LOOPS_PER_SECOND = 22.4


class SupplyBlockTracker:
    def __init__(self):
        self._blocked_since_loop: int | None = None

    def update(self, frame: Frame) -> float:
        """Returns seconds continuously blocked as of this frame; 0.0 if not blocked
        right now. Call once per frame, in game-loop order."""
        if not frame.supply_blocked:
            self._blocked_since_loop = None
            return 0.0

        if self._blocked_since_loop is None:
            self._blocked_since_loop = frame.game_loop
        return (frame.game_loop - self._blocked_since_loop) / LOOPS_PER_SECOND
