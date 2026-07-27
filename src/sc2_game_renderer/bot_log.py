"""Parses the bot's stderr.log — what the ladder actually returns, not the richer
structured JSONL streams documented in tbone's own logging contract (see
docs/SPEC.md § Bot-state overlay for why).

Two layers:

  raw line -> LogLine        (parse_log_lines)   — the sharpy log_manager prefix,
                                                    ~99.8% of in-game lines
  LogLine  -> BotEvent | None (classify_events)   — a whitelist of the messages worth
                                                    rendering; most lines are noise
                                                    (75% of the file is one repeated
                                                    "Pulling worker" line) and produce
                                                    nothing

Both are pure — no I/O, no SC2.
"""

import bisect
import re
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Sequence

LOOPS_PER_SECOND = 22.4

# clock is captured but not parsed further: it's redundant with game_loop / 22.4, and
# its shape varies (bot-startup lines use elapsed wall time "H:MM:SS"; in-game lines
# use the game clock "MM:SS"). Loop, not clock, is the field everything joins on.
_LOG_LINE = re.compile(
    r"^(?P<clock>\S+)\s+(?P<game_loop>\d+)\s+(?P<step_ms>\d+)ms\s+"
    r"(?P<minerals>-?\d+)M\s+(?P<vespene>-?\d+)G\s+"
    r"(?P<supply_used>\d+)/\s*(?P<supply_cap>\d+)U\s+"
    r"(?P<level>INFO|WARNING|ERROR|DEBUG)\s+(?P<logger>[\w.]+):(?P<lineno>\d+)\s(?P<message>.*)$"
)


@dataclass(frozen=True, slots=True)
class LogLine:
    game_loop: int
    step_ms: int
    minerals: int
    vespene: int
    supply_used: int
    supply_cap: int
    level: str
    logger: str
    lineno: int
    message: str


@dataclass(frozen=True, slots=True)
class ParseStats:
    total_lines: int
    parsed_lines: int

    @property
    def unparsed_lines(self) -> int:
        return self.total_lines - self.parsed_lines

    @property
    def parse_rate(self) -> float:
        return self.parsed_lines / self.total_lines if self.total_lines else 1.0


def parse_log_lines(text: str) -> tuple[list[LogLine], ParseStats]:
    """Lines that don't match the sharpy log_manager prefix are a different logging
    system entirely (matplotlib/mkdir warnings, loguru-default sc2 startup lines
    before the bot installs its own sink, aiohttp shutdown noise) — not this tool's
    concern, but counted so a real regression is visible rather than silently eating
    lines.
    """
    lines: list[LogLine] = []
    total = 0
    for raw in text.splitlines():
        if not raw.strip():
            continue
        total += 1
        m = _LOG_LINE.match(raw)
        if m is None:
            continue
        lines.append(
            LogLine(
                game_loop=int(m["game_loop"]),
                step_ms=int(m["step_ms"]),
                minerals=int(m["minerals"]),
                vespene=int(m["vespene"]),
                supply_used=int(m["supply_used"]),
                supply_cap=int(m["supply_cap"]),
                level=m["level"],
                logger=m["logger"],
                lineno=int(m["lineno"]),
                message=m["message"],
            )
        )
    return lines, ParseStats(total_lines=total, parsed_lines=len(lines))


# --- bot player id / game result --------------------------------------------------
#
# Both come from lines that predate the bot's own logging sink (loguru's default
# format), so they need their own patterns rather than reusing _LOG_LINE / message
# classification below.

_PLAYER_LINE = re.compile(r"Player (?P<player_id>\d+) - Bot ")
_RESULT_MESSAGE = re.compile(r"^Result for player (?P<player_id>\d+).*: (?P<result>\w+)$")


def infer_bot_player_id(text: str) -> int | None:
    m = _PLAYER_LINE.search(text)
    return int(m["player_id"]) if m else None


def infer_result(lines: Iterable[LogLine]) -> tuple[int, str] | None:
    for line in lines:
        m = _RESULT_MESSAGE.match(line.message)
        if m:
            return int(m["player_id"]), m["result"]
    return None


# --- event classification -----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class BotEvent:
    kind: str
    game_loop: int
    pos: tuple[float, float] | None = None
    pos2: tuple[float, float] | None = None
    data: tuple[tuple[str, Any], ...] = ()  # frozen-hashable stand-in for a dict

    def data_dict(self) -> dict[str, Any]:
        return dict(self.data)


_UNIT_TRAINED = re.compile(r"^\[(?:TrainSCV|TerranUnit)\] (?P<unit>\w+) from (?P<structure>\w+) at \((?P<x>-?[\d.]+), (?P<y>-?[\d.]+)\)$")
_BUILD_ADDON = re.compile(r"^\[BuildAddon\] UnitTypeId\.(?P<addon>\w+) to \((?P<x>-?[\d.]+), (?P<y>-?[\d.]+)\)$")
_BUILD_GAS = re.compile(r"^\[BuildGas\] Building (?P<unit>\w+) to \((?P<x>-?[\d.]+), (?P<y>-?[\d.]+)\)$")
_CANCEL_BUILDING = re.compile(r"^\[PlanCancelBuilding\] Cancelled (?P<unit>\w+) at \((?P<x>-?[\d.]+), (?P<y>-?[\d.]+)\) with (?P<health>[\d.]+) health$")
_NO_PATH = re.compile(r"^No path found \((?P<x0>-?[\d.]+), (?P<y0>-?[\d.]+)\), \((?P<x1>-?[\d.]+), (?P<y1>-?[\d.]+)\)$")
_UNREACHABLE = re.compile(r"^target \((?P<x>-?[\d.]+), (?P<y>-?[\d.]+)\) unreachable!$")
_ADVANTAGE = re.compile(r"^\[GameAnalyzer\] (?P<metric>.+) is now (?P<state>\S+)$")
_WORKERS_IN_DANGER = re.compile(r"^Workers in danger: (?P<count>\d+)$")
_HIGH_WORKING_DANGER = re.compile(r"^High working danger, should evacuate mining zone\.(?P<detail>.*)$")
_HIGH_WORKING_DANGER_FLOATS = re.compile(
    r"mineral_center_enemy_influence=np\.float64\((?P<influence>[\d.]+)\).*max_threat=np\.float64\((?P<threat>[\d.]+)\)"
)
_ACTION_ERROR = re.compile(r"^Action error: ActionError\(ability_id=(?P<ability_id>\d+), unit_tag=(?P<unit_tag>\d+), result=(?P<result>\d+)\)-?\s*(?P<ability_name>\S*)$")
_GAE_SECTION = re.compile(r"^\[GameAnalyzerEnd\] (?P<section>Own|Enemy) units:$")
_GAE_UNIT_ROW = re.compile(r"^\[GameAnalyzerEnd\] (?P<unit_type>[A-Z0-9]+)\s+total:\s*(?P<total>\d+) alive:\s*(?P<alive>\d+) dead:\s*(?P<dead>\d+)\s*$")
_GAE_RESOURCE = re.compile(r"^\[GameAnalyzerEnd\] (?P<resource>Minerals|Vespene) max (?P<max>\d+) Average (?P<avg>\d+)$")
# The "[BuildDetector] " prefix is optional: the currently-checked-out tbone source
# calls self.print() for these two messages with no explicit tag, but every real
# match log actually inspected has the tag anyway (likely an older bot version) —
# matching both rather than assuming which one produced any given log.
_BUILD_RECOGNIZED = re.compile(r"^(?:\[BuildDetector\] )?Enemy normal build recognized as (?P<build>\S+)$")
_POSSIBLE_RUSH = re.compile(r"^(?:\[BuildDetector\] )?POSSIBLE RUSH: (?P<rush>\S+)\.$")


def classify_events(lines: Iterable[LogLine]) -> Iterator[BotEvent]:
    """One pass over the parsed lines, in order. The only state kept is which
    [GameAnalyzerEnd] section ("Own units:" / "Enemy units:") we're currently under,
    needed to label the per-unit-type rows that follow each header.
    """
    gae_section: str | None = None

    for line in lines:
        msg = line.message

        if m := _UNIT_TRAINED.match(msg):
            yield BotEvent("unit_trained", line.game_loop, pos=(float(m["x"]), float(m["y"])),
                            data=(("unit", m["unit"]), ("structure", m["structure"])))
        elif m := _BUILD_ADDON.match(msg):
            yield BotEvent("build_addon", line.game_loop, pos=(float(m["x"]), float(m["y"])),
                            data=(("addon", m["addon"]),))
        elif m := _BUILD_GAS.match(msg):
            yield BotEvent("build_gas", line.game_loop, pos=(float(m["x"]), float(m["y"])),
                            data=(("unit", m["unit"]),))
        elif m := _CANCEL_BUILDING.match(msg):
            yield BotEvent("cancel_building", line.game_loop, pos=(float(m["x"]), float(m["y"])),
                            data=(("unit", m["unit"]), ("health", float(m["health"]))))
        elif m := _NO_PATH.match(msg):
            yield BotEvent("no_path", line.game_loop,
                            pos=(float(m["x0"]), float(m["y0"])), pos2=(float(m["x1"]), float(m["y1"])))
        elif m := _UNREACHABLE.match(msg):
            yield BotEvent("unreachable", line.game_loop, pos=(float(m["x"]), float(m["y"])))
        elif m := _ADVANTAGE.match(msg):
            yield BotEvent("advantage", line.game_loop, data=(("metric", m["metric"]), ("state", m["state"])))
        elif m := _WORKERS_IN_DANGER.match(msg):
            yield BotEvent("workers_in_danger", line.game_loop, data=(("count", int(m["count"])),))
        elif m := _HIGH_WORKING_DANGER.match(msg):
            data: list[tuple[str, Any]] = []
            if fm := _HIGH_WORKING_DANGER_FLOATS.search(m["detail"]):
                data = [("mineral_center_enemy_influence", float(fm["influence"])), ("max_threat", float(fm["threat"]))]
            yield BotEvent("high_working_danger", line.game_loop, data=tuple(data))
        elif m := _ACTION_ERROR.match(msg):
            yield BotEvent("action_error", line.game_loop,
                            data=(("ability_id", int(m["ability_id"])), ("unit_tag", int(m["unit_tag"])),
                                  ("result", int(m["result"])), ("ability_name", m["ability_name"])))
        elif m := _BUILD_RECOGNIZED.match(msg):
            yield BotEvent("build_recognized", line.game_loop, data=(("build", m["build"]),))
        elif m := _POSSIBLE_RUSH.match(msg):
            yield BotEvent("possible_rush", line.game_loop, data=(("rush", m["rush"]),))
        elif m := _GAE_SECTION.match(msg):
            gae_section = m["section"].lower()
        elif m := _GAE_UNIT_ROW.match(msg):
            yield BotEvent("unit_summary", line.game_loop,
                            data=(("section", gae_section), ("unit_type", m["unit_type"]),
                                  ("total", int(m["total"])), ("alive", int(m["alive"])), ("dead", int(m["dead"]))))
        elif m := _GAE_RESOURCE.match(msg):
            yield BotEvent("resource_summary", line.game_loop,
                            data=(("resource", m["resource"]), ("max", int(m["max"])), ("average", int(m["avg"]))))
        # else: not on the whitelist — most lines (e.g. the 75%-of-file "Pulling
        # worker" noise), silently skipped by design.


# --- joining to sampled frames -------------------------------------------------------

@dataclass(frozen=True, slots=True)
class JoinResult:
    joined: tuple[tuple[BotEvent, int], ...]  # (event, frame_game_loop)
    dropped: int


def join_events_to_frames(events: Iterable[BotEvent], frame_loops: Sequence[int], sample_loops: int) -> JoinResult:
    """Attaches each event to the nearest sampled frame at or after it, within one
    sample interval. Events that land after the last frame, or further than
    `sample_loops` from the nearest following frame, are dropped and counted — a
    mismatched replay/log pairing should be loud, not a silently empty overlay.
    """
    joined: list[tuple[BotEvent, int]] = []
    dropped = 0
    for event in events:
        i = bisect.bisect_left(frame_loops, event.game_loop)
        if i >= len(frame_loops) or frame_loops[i] - event.game_loop > sample_loops:
            dropped += 1
            continue
        joined.append((event, frame_loops[i]))
    return JoinResult(joined=tuple(joined), dropped=dropped)
