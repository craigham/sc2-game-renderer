from collections import Counter
from pathlib import Path

from sc2_game_renderer.bot_log import (
    _LOG_LINE,  # white-box: used only to characterize the unparsed-line set below
    BotEvent,
    LogLine,
    classify_events,
    infer_bot_player_id,
    infer_result,
    join_events_to_frames,
    parse_log_lines,
)

STDERR_LOG = Path(__file__).parent.parent / "replays" / "4891371" / "stderr.log"


def _load():
    text = STDERR_LOG.read_text(errors="replace")
    lines, stats = parse_log_lines(text)
    return text, lines, stats


# --- parse_log_lines -----------------------------------------------------------------

def test_parse_rate_is_at_least_99_percent():
    _, _, stats = _load()
    assert stats.total_lines == 2997
    assert stats.parse_rate >= 0.99


def test_unparsed_lines_are_the_known_non_bot_preamble_and_shutdown_noise():
    text, _, stats = _load()
    assert stats.unparsed_lines == 6
    # every unparsed line is one of: matplotlib/mkdir startup noise, a loguru-default
    # sc2 line (before the bot's own sink is installed), or aiohttp shutdown chatter —
    # never a malformed *bot* log line.
    known_fragments = ("matplotlib", "mkdir -p failed", "sc2.protocol", "sc2.main", "client_session", "Unclosed client session")
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if not _LOG_LINE.match(raw):
            assert any(f in raw for f in known_fragments), f"unexpected unparsed line: {raw!r}"


def test_negative_minerals_parse_as_negative_ints_not_crash():
    _, lines, _ = _load()
    negative = [l for l in lines if l.minerals < 0]
    assert len(negative) == 4
    assert {l.minerals for l in negative} == {-100, -50, -46}


def test_step_size_is_four_loops():
    _, lines, _ = _load()
    assert all(l.game_loop % 4 == 0 for l in lines)


# --- infer_bot_player_id / infer_result -----------------------------------------------

def test_infer_bot_player_id():
    text, _, _ = _load()
    assert infer_bot_player_id(text) == 2


def test_infer_result():
    _, lines, _ = _load()
    assert infer_result(lines) == (2, "Defeat")


def test_infer_result_returns_none_without_a_result_line():
    lines = [LogLine(0, 0, 0, 0, 0, 0, "INFO", "x", 1, "nothing interesting")]
    assert infer_result(lines) is None


# --- classify_events: noise exclusion -------------------------------------------------

def test_pulling_worker_noise_is_excluded():
    """75% of the file is this one repeated zone_defense message; it must never
    produce an event, or the overlay is unreadable."""
    _, lines, _ = _load()
    pulling_worker_lines = [l for l in lines if "Pulling worker" in l.message]
    assert len(pulling_worker_lines) > 2000  # sanity: this really is the dominant line
    assert list(classify_events(pulling_worker_lines)) == []


def test_total_event_count_and_noise_ratio():
    _, lines, _ = _load()
    events = list(classify_events(lines))
    assert len(events) == 722
    assert len(events) < len(lines) * 0.3  # whitelist, not everything


# --- classify_events: per-kind counts (regression pins) -------------------------------

def test_event_kind_counts():
    _, lines, _ = _load()
    events = list(classify_events(lines))
    counts = Counter(e.kind for e in events)
    assert counts == {
        "high_working_danger": 236,
        "advantage": 235,
        "unit_trained": 51,
        "workers_in_danger": 50,
        "build_addon": 43,
        "action_error": 37,
        "unit_summary": 28,
        "unreachable": 21,
        "no_path": 13,
        "build_gas": 4,
        "cancel_building": 2,
        "resource_summary": 2,
    }


# --- classify_events: exact field values on real lines ---------------------------------

def test_unit_trained_event_fields():
    _, lines, _ = _load()
    events = list(classify_events(lines))
    first = next(e for e in events if e.kind == "unit_trained")
    assert first.game_loop == 340
    assert first.pos == (42.5, 46.5)
    assert first.data_dict() == {"unit": "SCV", "structure": "COMMANDCENTER"}


def test_no_path_event_has_two_positions():
    _, lines, _ = _load()
    events = list(classify_events(lines))
    first = next(e for e in events if e.kind == "no_path")
    assert first.pos == (47.5, 45.625)
    assert first.pos2 == (76.62132034355965, 50.621320343559645)


def test_action_error_event_fields():
    _, lines, _ = _load()
    events = list(classify_events(lines))
    first = next(e for e in events if e.kind == "action_error")
    assert first.data_dict() == {
        "ability_id": 558, "unit_tag": 4357095425, "result": 44, "ability_name": "MORPH_SUPPLYDEPOT_RAISE",
    }


def test_high_working_danger_extracts_diagnostic_floats():
    _, lines, _ = _load()
    events = list(classify_events(lines))
    first = next(e for e in events if e.kind == "high_working_danger")
    data = first.data_dict()
    assert data["mineral_center_enemy_influence"] == 1.0028577960676721
    assert data["max_threat"] == 15.11404511507392


def test_unit_summary_labels_own_and_enemy_sections_correctly():
    _, lines, _ = _load()
    events = [e for e in classify_events(lines) if e.kind == "unit_summary"]

    own_marine = next(e for e in events if e.data_dict()["section"] == "own" and e.data_dict()["unit_type"] == "MARINE")
    assert own_marine.data_dict() == {"section": "own", "unit_type": "MARINE", "total": 54, "alive": 0, "dead": 54}

    enemy_marine = next(e for e in events if e.data_dict()["section"] == "enemy" and e.data_dict()["unit_type"] == "MARINE")
    assert enemy_marine.data_dict() == {"section": "enemy", "unit_type": "MARINE", "total": 90, "alive": 78, "dead": 12}


def test_resource_summary_events():
    _, lines, _ = _load()
    events = [e for e in classify_events(lines) if e.kind == "resource_summary"]
    by_resource = {e.data_dict()["resource"]: e.data_dict() for e in events}
    assert by_resource["Minerals"] == {"resource": "Minerals", "max": 740, "average": 129}
    assert by_resource["Vespene"] == {"resource": "Vespene", "max": 1136, "average": 599}


# --- build_recognized / possible_rush --------------------------------------------------
#
# Not in the checked-in fixture (this bot's build_detector never fired during that
# particular game) — synthetic lines instead, in the real sharpy prefix format. Both
# the tagged and untagged variants are real: every actual match log inspected
# (tbone's match_logs/*.log) has "[BuildDetector] " prefixed, but the currently
# checked-out tbone source calls self.print() for these two messages with no
# explicit tag at all — likely an older bot version produced the tagged logs. The
# parser has to handle whichever one shows up.

def test_build_recognized_with_tag():
    lines, _ = parse_log_lines(
        "04:44 6376   76ms   155M  178G  59/ 70U INFO sharpy.managers.core.log_manager:80 "
        "[BuildDetector] Enemy normal build recognized as Mutalisks\n"
    )
    events = list(classify_events(lines))
    assert len(events) == 1
    assert events[0].kind == "build_recognized"
    assert events[0].data_dict() == {"build": "Mutalisks"}


def test_build_recognized_without_tag():
    lines, _ = parse_log_lines(
        "04:44 6376   76ms   155M  178G  59/ 70U INFO sharpy.managers.core.log_manager:80 "
        "Enemy normal build recognized as BattleCruisers\n"
    )
    events = list(classify_events(lines))
    assert len(events) == 1
    assert events[0].data_dict() == {"build": "BattleCruisers"}


def test_possible_rush_with_tag():
    lines, _ = parse_log_lines(
        "01:32 2064   51ms   285M   26G  19/ 23U INFO sharpy.managers.core.log_manager:80 "
        "[BuildDetector] POSSIBLE RUSH: OneBaseRax.\n"
    )
    events = list(classify_events(lines))
    assert len(events) == 1
    assert events[0].kind == "possible_rush"
    assert events[0].data_dict() == {"rush": "OneBaseRax"}


def test_possible_rush_without_tag():
    lines, _ = parse_log_lines(
        "01:32 2064   51ms   285M   26G  19/ 23U INFO sharpy.managers.core.log_manager:80 "
        "POSSIBLE RUSH: ProxyZealots.\n"
    )
    events = list(classify_events(lines))
    assert events[0].data_dict() == {"rush": "ProxyZealots"}


def test_multiple_possible_rush_flags_yield_separate_events():
    # Real match logs show several different rush hypotheses flagged back to back
    # (no "ruled out" message ever retracts one) — each is its own event, not
    # deduplicated at this layer.
    lines, _ = parse_log_lines(
        "01:50 2468   48ms   183M    4G  20/ 23U INFO sharpy.managers.core.log_manager:80 "
        "[BuildDetector] POSSIBLE RUSH: OneHatcheryAllIn.\n"
        "01:50 2468   78ms   178M    8G  20/ 23U INFO sharpy.managers.core.log_manager:80 "
        "[BuildDetector] POSSIBLE RUSH: ProxyZealots.\n"
    )
    events = list(classify_events(lines))
    assert [e.data_dict()["rush"] for e in events] == ["OneHatcheryAllIn", "ProxyZealots"]


# --- join_events_to_frames -------------------------------------------------------------

def _event(loop: int, kind: str = "workers_in_danger") -> BotEvent:
    return BotEvent(kind=kind, game_loop=loop)


def test_join_on_exact_boundary():
    result = join_events_to_frames([_event(100)], frame_loops=[92, 96, 100, 104], sample_loops=4)
    assert result.joined == ((_event(100), 100),)
    assert result.dropped == 0


def test_join_between_samples_within_tolerance():
    # event two loops after a frame, joins the *next* frame at exactly one sample away
    result = join_events_to_frames([_event(98)], frame_loops=[92, 96, 100, 104], sample_loops=4)
    assert result.joined == ((_event(98), 100),)
    assert result.dropped == 0


def test_join_exactly_at_tolerance_boundary_still_joins():
    # nearest following frame is exactly `sample_loops` away — spec says within
    # tolerance is inclusive
    result = join_events_to_frames([_event(96)], frame_loops=[92, 100], sample_loops=4)
    assert result.joined == ((_event(96), 100),)
    assert result.dropped == 0


def test_join_out_of_tolerance_is_dropped():
    result = join_events_to_frames([_event(95)], frame_loops=[92, 100], sample_loops=4)
    assert result.joined == ()
    assert result.dropped == 1


def test_join_event_after_last_frame_is_dropped():
    result = join_events_to_frames([_event(999)], frame_loops=[92, 96, 100], sample_loops=4)
    assert result.joined == ()
    assert result.dropped == 1


def test_join_real_events_against_realistic_frame_loops_has_zero_drops():
    """The real extraction's frame loops are exactly range(0, last_loop+1, 4) — every
    bot log line already lands on a multiple of 4, so a correctly paired replay/log
    should join everything."""
    _, lines, _ = _load()
    events = list(classify_events(lines))
    frame_loops = list(range(0, 15232 + 1, 4))  # matches the real 3,809-frame extract

    result = join_events_to_frames(events, frame_loops, sample_loops=4)
    assert result.dropped == 0
    assert len(result.joined) == len(events) == 722


def test_join_mismatched_replay_log_pairing_reports_high_drop_count():
    """A log paired with the wrong replay should be loud, not silently empty."""
    _, lines, _ = _load()
    events = list(classify_events(lines))
    wrong_game_frame_loops = list(range(20000, 20000 + 3809 * 4, 4))  # disjoint range

    result = join_events_to_frames(events, wrong_game_frame_loops, sample_loops=4)
    assert result.dropped == len(events)
    assert result.joined == ()
