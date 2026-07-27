"""Human-readable, rolling recent-events history for the HUD sidebar.

Complements the momentary world/banner flashes (an event only ever attaches to the
one frame it was joined to — see bot_state_overlay.py — which could pass by in a
single rendered frame): the ticker keeps recent event descriptions on screen for
longer than that single flash.
"""

from collections import deque
from typing import Sequence

from sc2_game_renderer.bot_log import BotEvent

DEFAULT_MAX_ENTRIES = 6


def describe_event(event: BotEvent) -> str | None:
    """None for event kinds that don't belong in a "things just happened" ticker —
    currently just the end-of-game summary rows, which are a different kind of
    display concern."""
    d = event.data_dict()
    if event.kind == "unit_trained":
        return f"Trained {d['unit']} ({d['structure']})"
    if event.kind == "build_addon":
        return f"Building {d['addon']}"
    if event.kind == "build_gas":
        return f"Building {d['unit']} (gas)"
    if event.kind == "cancel_building":
        return f"Cancelled {d['unit']}"
    if event.kind == "no_path":
        return "No path found"
    if event.kind == "unreachable":
        return "Target unreachable"
    if event.kind == "advantage":
        return f"{d['metric']}: {d['state']}"
    if event.kind == "workers_in_danger":
        return f"Workers in danger: {d['count']}"
    if event.kind == "high_working_danger":
        return "High working danger — evacuate!"
    if event.kind == "action_error":
        return f"Action error: {d['ability_name'] or d['ability_id']}"
    if event.kind == "build_recognized":
        return f"Enemy build recognized: {d['build']}"
    if event.kind == "possible_rush":
        return f"Possible rush: {d['rush']}"
    return None  # unit_summary, resource_summary: end-of-game, not a ticker item


class EventTicker:
    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES):
        self._entries: deque[str] = deque(maxlen=max_entries)

    def update(self, events: Sequence[BotEvent]) -> None:
        for event in events:
            text = describe_event(event)
            if text is not None:
                self._entries.append(text)

    def entries(self) -> list[str]:
        return list(self._entries)
