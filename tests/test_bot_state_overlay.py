from pathlib import Path

from sc2_game_renderer.bot_log import BotEvent
from sc2_game_renderer.bot_state_overlay import IncomeAdvantageTracker, build_overlay

STDERR_LOG = Path(__file__).parent.parent / "replays" / "4891371" / "stderr.log"

# Hand-crafted, matching the real sharpy log_manager prefix (see bot_log.py / the
# fixture stderr.log) closely enough to exercise parsing + classification + joining
# together, without depending on exact real-game values.
SYNTHETIC_LOG = "\n".join([
    "00:00    0    0ms    50M    0G  12/ 15U INFO sharpy.managers.core.log_manager:80 [GameAnalyzer] Income advantage is now SmallDisadvantage",
    "00:00    4    5ms    50M    0G  12/ 15U INFO sharpy.managers.core.log_manager:80 [TrainSCV] SCV from COMMANDCENTER at (42.5, 46.5)",
    "00:01   20   10ms    65M   10G  13/ 15U INFO sharpy.managers.core.log_manager:80 [GameAnalyzer] Income advantage is now SlightAdvantage",
    "00:02   44   12ms    80M   20G  14/ 15U WARNING sharpy.managers.core.pathing_manager:312 No path found (10.0, 10.0), (20.0, 20.0)",
])


# --- build_overlay: synthetic log ------------------------------------------------

def test_events_join_to_the_nearest_frame_at_or_after():
    frame_loops = [0, 4, 8, 20, 44]
    overlay = build_overlay(SYNTHETIC_LOG, frame_loops, sample_loops=4)

    assert [e.kind for e in overlay.events_at(0)] == ["advantage"]
    assert [e.kind for e in overlay.events_at(4)] == ["unit_trained"]
    assert [e.kind for e in overlay.events_at(20)] == ["advantage"]
    assert [e.kind for e in overlay.events_at(44)] == ["no_path"]
    assert overlay.dropped_event_count == 0
    assert overlay.total_event_count == 4


def test_events_at_returns_empty_tuple_for_a_loop_with_no_events():
    overlay = build_overlay(SYNTHETIC_LOG, [0, 4, 8, 20, 44], sample_loops=4)
    assert overlay.events_at(8) == ()


def test_parse_stats_reflect_the_synthetic_log():
    overlay = build_overlay(SYNTHETIC_LOG, [0, 4, 8, 20, 44], sample_loops=4)
    assert overlay.parse_stats.total_lines == 4
    assert overlay.parse_stats.parsed_lines == 4


def test_mismatched_frame_loops_drop_everything():
    overlay = build_overlay(SYNTHETIC_LOG, [10_000, 10_004], sample_loops=4)
    assert overlay.dropped_event_count == 4
    assert overlay.events_at(10_000) == ()


# --- resource_belief_at ------------------------------------------------------------

def test_resource_belief_at_exact_loop_match():
    overlay = build_overlay(SYNTHETIC_LOG, [0, 4, 8, 20, 44], sample_loops=4)
    belief = overlay.resource_belief_at(20)
    assert (belief.minerals, belief.vespene, belief.supply_used, belief.supply_cap) == (65, 10, 13, 15)


def test_resource_belief_at_uses_nearest_before_when_no_exact_line():
    overlay = build_overlay(SYNTHETIC_LOG, [0, 4, 8, 20, 44], sample_loops=4)
    # loop 8 has no log line; nearest-before is the loop-4 line (50M/0G, 12/15)
    belief = overlay.resource_belief_at(8)
    assert (belief.minerals, belief.vespene) == (50, 0)


def test_resource_belief_at_before_any_log_line_is_none():
    overlay = build_overlay(SYNTHETIC_LOG, [0, 4, 8, 20, 44], sample_loops=4)
    assert overlay.resource_belief_at(-1) is None


def test_resource_belief_at_after_last_log_line_uses_last_known():
    overlay = build_overlay(SYNTHETIC_LOG, [0, 4, 8, 20, 44], sample_loops=4)
    belief = overlay.resource_belief_at(10_000)
    assert (belief.minerals, belief.vespene, belief.supply_used, belief.supply_cap) == (80, 20, 14, 15)


# --- IncomeAdvantageTracker ---------------------------------------------------------

def test_income_advantage_tracker_starts_none():
    assert IncomeAdvantageTracker().state is None


def test_income_advantage_tracker_updates_to_latest_value():
    tracker = IncomeAdvantageTracker()
    tracker.update([BotEvent("advantage", 0, data=(("metric", "Income advantage"), ("state", "SmallDisadvantage")))])
    assert tracker.state == "SmallDisadvantage"
    tracker.update([BotEvent("advantage", 20, data=(("metric", "Income advantage"), ("state", "SlightAdvantage")))])
    assert tracker.state == "SlightAdvantage"


def test_income_advantage_tracker_ignores_other_advantage_metrics():
    tracker = IncomeAdvantageTracker()
    tracker.update([BotEvent("advantage", 0, data=(("metric", "Known army advantage"), ("state", "SlightAdvantage")))])
    assert tracker.state is None


def test_income_advantage_tracker_ignores_unrelated_events():
    tracker = IncomeAdvantageTracker()
    tracker.update([BotEvent("workers_in_danger", 0, data=(("count", 1),))])
    assert tracker.state is None


# --- real fixture: end-to-end -------------------------------------------------------

def test_build_overlay_against_the_real_fixture_log():
    text = STDERR_LOG.read_text(errors="replace")
    frame_loops = list(range(0, 15232 + 1, 4))  # matches the real 3,809-frame extract

    overlay = build_overlay(text, frame_loops, sample_loops=4)

    assert overlay.total_event_count == 722
    assert overlay.dropped_event_count == 0
    assert overlay.parse_stats.parse_rate >= 0.99

    # the documented first unit_trained event, from tests/test_bot_log.py
    events_at_340 = overlay.events_at(340)
    assert len(events_at_340) == 1
    assert events_at_340[0].kind == "unit_trained"
    assert events_at_340[0].pos == (42.5, 46.5)

    # resource belief at loop 0 matches stderr.log's own first line
    belief = overlay.resource_belief_at(0)
    assert (belief.minerals, belief.supply_used, belief.supply_cap) == (50, 12, 15)
