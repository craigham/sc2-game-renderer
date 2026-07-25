from sc2_game_renderer.bot_log import BotEvent
from sc2_game_renderer.event_ticker import EventTicker, describe_event


def test_describe_event_for_each_positioned_kind():
    assert describe_event(BotEvent("unit_trained", 0, data=(("unit", "SCV"), ("structure", "COMMANDCENTER")))) == "Trained SCV (COMMANDCENTER)"
    assert describe_event(BotEvent("build_addon", 0, data=(("addon", "FACTORYREACTOR"),))) == "Building FACTORYREACTOR"
    assert describe_event(BotEvent("build_gas", 0, data=(("unit", "REFINERY"),))) == "Building REFINERY (gas)"
    assert describe_event(BotEvent("cancel_building", 0, data=(("unit", "STARPORTREACTOR"), ("health", 22.1)))) == "Cancelled STARPORTREACTOR"
    assert describe_event(BotEvent("no_path", 0)) == "No path found"
    assert describe_event(BotEvent("unreachable", 0)) == "Target unreachable"


def test_describe_event_for_banner_kinds():
    assert describe_event(BotEvent("advantage", 0, data=(("metric", "Income advantage"), ("state", "SmallDisadvantage")))) == "Income advantage: SmallDisadvantage"
    assert describe_event(BotEvent("workers_in_danger", 0, data=(("count", 3),))) == "Workers in danger: 3"
    assert describe_event(BotEvent("high_working_danger", 0)) == "High working danger — evacuate!"


def test_describe_event_action_error_falls_back_to_ability_id_when_name_empty():
    assert describe_event(BotEvent("action_error", 0, data=(("ability_id", 558), ("unit_tag", 1), ("result", 44), ("ability_name", "MORPH_X")))) == "Action error: MORPH_X"
    assert describe_event(BotEvent("action_error", 0, data=(("ability_id", 558), ("unit_tag", 1), ("result", 44), ("ability_name", "")))) == "Action error: 558"


def test_describe_event_returns_none_for_end_of_game_summaries():
    assert describe_event(BotEvent("unit_summary", 0, data=(("section", "own"), ("unit_type", "MARINE"), ("total", 1), ("alive", 1), ("dead", 0)))) is None
    assert describe_event(BotEvent("resource_summary", 0, data=(("resource", "Minerals"), ("max", 1), ("average", 1)))) is None


def test_ticker_accumulates_across_updates():
    ticker = EventTicker(max_entries=10)
    ticker.update([BotEvent("unreachable", 0)])
    ticker.update([BotEvent("no_path", 4)])
    assert ticker.entries() == ["Target unreachable", "No path found"]


def test_ticker_caps_at_max_entries_dropping_oldest():
    ticker = EventTicker(max_entries=2)
    ticker.update([BotEvent("unreachable", 0)])
    ticker.update([BotEvent("no_path", 4)])
    ticker.update([BotEvent("cancel_building", 8, data=(("unit", "X"), ("health", 1.0)))])
    assert ticker.entries() == ["No path found", "Cancelled X"]


def test_ticker_skips_events_with_no_description():
    ticker = EventTicker()
    ticker.update([
        BotEvent("unit_summary", 0, data=(("section", "own"), ("unit_type", "MARINE"), ("total", 1), ("alive", 1), ("dead", 0))),
        BotEvent("unreachable", 0),
    ])
    assert ticker.entries() == ["Target unreachable"]


def test_ticker_starts_empty():
    assert EventTicker().entries() == []
