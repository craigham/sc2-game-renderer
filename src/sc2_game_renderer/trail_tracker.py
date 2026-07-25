"""Tracks each own unit's recent positions for the movement-trail overlay.

Pure and stateful across ordered frames — same shape as enemy_memory.py's
EnemyMemory: call `update(frame)` once per sampled frame, in game-loop order.

This is a render-time concern, not stored in the frame file: own-unit trails can
always be reconstructed by replaying the frames that already exist, in order, which
is exactly what rendering does anyway — no need to bloat the persisted format with
derived history (see docs/SPEC.md § Architecture / frame_file.py's ExtractedFrame,
which stores only per-frame data plus the enemy-memory view, which *can't* be
reconstructed without also replaying the whole sequence).
"""

from collections import deque

from sc2_game_renderer.frame import Frame

DEFAULT_MAX_TRAIL_LENGTH = 20


class TrailTracker:
    """`unit_tag -> deque of (x, y)`, oldest first, capped at `max_length`.

    A unit's trail is dropped entirely the moment it no longer appears in
    `frame.own_units` — own units are never fogged, so absence means it died (or the
    replay ended). There's no "gap and reappear" continuity: a tag reappearing after
    disappearing starts a fresh trail.
    """

    def __init__(self, max_length: int = DEFAULT_MAX_TRAIL_LENGTH):
        self.max_length = max_length
        self._trails: dict[int, deque[tuple[float, float]]] = {}

    def update(self, frame: Frame) -> None:
        current_tags = {u.tag for u in frame.own_units}
        for tag in list(self._trails):
            if tag not in current_tags:
                del self._trails[tag]

        for u in frame.own_units:
            trail = self._trails.setdefault(u.tag, deque(maxlen=self.max_length))
            trail.append((u.x, u.y))

    def trails(self) -> dict[int, list[tuple[float, float]]]:
        return {tag: list(points) for tag, points in self._trails.items()}
