"""Wires slice 4 (bot_log.py) to the render layer: parses stderr.log, classifies
events, joins them to a frame file's sampled game loops, and exposes both per-frame
event lookups and the bot's own believed resource/supply values for the
belief-vs-truth cross-check (docs/SPEC.md § Bot-state overlay).
"""

import bisect
from dataclasses import dataclass
from typing import Sequence

from sc2_game_renderer.bot_log import BotEvent, ParseStats, classify_events, join_events_to_frames, parse_log_lines


@dataclass(frozen=True, slots=True)
class ResourceBelief:
    """What the bot's own log reported at some game loop — compared against a
    Frame's minerals/vespene/supply (ground truth from the observation) to catch a
    divergence between what the bot believed and what was actually true."""

    minerals: int
    vespene: int
    supply_used: int
    supply_cap: int


class GameAnalyzerTracker:
    """Persistent last-known state for every GameAnalyzer metric the bot reports
    (Income/Known army/Predicted army advantage, and any future one — not
    hardcoded to these three names). Treated as persistent, unlike most banners,
    because the log itself frames each as an ongoing status ("is now X"), so "the
    last one we heard" is a real, current fact — not a guess at whether it's still
    true. The other banners (worker danger, evacuation warnings) have no
    corresponding "cleared" event in the log, so they're rendered only on the exact
    frame they land on — see render_hud.py — rather than invented a decay timeout
    not grounded in the data.
    """

    def __init__(self):
        self.state: dict[str, str] = {}  # metric name -> latest state

    def update(self, events: Sequence[BotEvent]) -> None:
        for e in events:
            if e.kind == "advantage":
                d = e.data_dict()
                self.state[d["metric"]] = d["state"]


class BuildDetectorTracker:
    """Persistent state: the bot's own best guess at the enemy's build, from
    terranbot/managers/build_detector.py's log output. `recognized_build` is the
    latest "normal" build recognition (stays None all game for a standard build).
    `possible_rushes` only ever grows — there's no "ruled out" event in the log, so
    once a rush hypothesis is flagged it stays flagged for the rest of the game.
    """

    def __init__(self):
        self.recognized_build: str | None = None
        self.possible_rushes: list[str] = []  # insertion order, deduplicated

    def update(self, events: Sequence[BotEvent]) -> None:
        for e in events:
            if e.kind == "build_recognized":
                self.recognized_build = e.data_dict()["build"]
            elif e.kind == "possible_rush":
                rush = e.data_dict()["rush"]
                if rush not in self.possible_rushes:
                    self.possible_rushes.append(rush)


class BotStateOverlay:
    def __init__(
        self,
        events_by_frame_loop: dict[int, tuple[BotEvent, ...]],
        parse_stats: ParseStats,
        dropped_event_count: int,
        total_event_count: int,
        belief_loops: tuple[int, ...],
        beliefs: tuple[ResourceBelief, ...],
    ):
        self.events_by_frame_loop = events_by_frame_loop
        self.parse_stats = parse_stats
        self.dropped_event_count = dropped_event_count
        self.total_event_count = total_event_count
        self._belief_loops = belief_loops
        self._beliefs = beliefs

    def events_at(self, frame_game_loop: int) -> tuple[BotEvent, ...]:
        return self.events_by_frame_loop.get(frame_game_loop, ())

    def resource_belief_at(self, frame_game_loop: int) -> ResourceBelief | None:
        """The bot's most recent resource snapshot at or before this game loop — not
        every loop has a log line (the bot only logs when something happens), so
        this is nearest-before, not an exact match."""
        i = bisect.bisect_right(self._belief_loops, frame_game_loop) - 1
        return self._beliefs[i] if i >= 0 else None


def build_overlay(log_text: str, frame_loops: Sequence[int], sample_loops: int) -> BotStateOverlay:
    lines, parse_stats = parse_log_lines(log_text)
    events = list(classify_events(lines))
    join_result = join_events_to_frames(events, frame_loops, sample_loops)

    by_loop: dict[int, list[BotEvent]] = {}
    for event, loop in join_result.joined:
        by_loop.setdefault(loop, []).append(event)

    belief_by_loop: dict[int, ResourceBelief] = {}
    for line in lines:
        belief_by_loop[line.game_loop] = ResourceBelief(
            line.minerals, line.vespene, line.supply_used, line.supply_cap
        )
    belief_loops = tuple(sorted(belief_by_loop))
    beliefs = tuple(belief_by_loop[lp] for lp in belief_loops)

    return BotStateOverlay(
        events_by_frame_loop={loop: tuple(evts) for loop, evts in by_loop.items()},
        parse_stats=parse_stats,
        dropped_event_count=join_result.dropped,
        total_event_count=len(events),
        belief_loops=belief_loops,
        beliefs=beliefs,
    )
