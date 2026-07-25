# Implementation Plan

Sliced so each slice ends somewhere useful. Data layer is test-first; the rendering
layer is verified by looking at output frames (no pixel-position assertions).

---

## Slice 0 — Scaffold + stepping spike (**gate**) — ✅ DONE

Outcome: **Mac stepping failed, Docker succeeded.** Extraction runs in a linux/amd64
container; see `docs/SPEC.md` § Chief risk for the numbers and the two gotchas.

- ✅ `uv` project, Python 3.12, ffmpeg 8.1.2 present.
- ✅ Local Mac attempt — SC2 4.10 aborts on macOS 26.5.1 (SIGABRT under Rosetta).
- ✅ `docker/Dockerfile` → `sc2-extract:4.10`.
- ✅ `scripts/spike_step_replay.py` steps the full fixture replay: 3,809 frames,
  correct end-of-game detection (`player_id: 2, result: Defeat`, matching `stderr.log`).
- ✅ Fixture captured to `tests/fixtures/4891371/` — 51 observations + game_info,
  244 KB, loads on the Mac with no SC2 and no Docker.

---

## Slice 1 — Frame model + mapper *(test-first)* — ✅ DONE

`src/sc2_game_renderer/frame.py`: pure `ResponseObservation -> Frame`. Own units,
enemy visible/snapshot, resources + income rate, supply (+ `supply_blocked`), idle
workers, army value.

Two corrections to the original spec while implementing, both free from the
observation rather than needing derivation: `idle_worker_count` is a `player_common`
field directly, and army value comes from `score.score_details.used_minerals/vespene
.army` — SC2's own running spent-minus-lost tally, the same figure the client's built-
in graphs use, not a recomputation from unit type costs.

**Verified:** `tests/test_frame.py`, 9 tests against `tests/fixtures/4891371/` — frame
42 (loop 12768) matches the documented values exactly (108 own / 42 enemy-visible / 27
enemy-snapshot / 125 minerals / 81:118 supply / army value 1900🟦475🟨).

## Slice 2 — Enemy memory tracker *(test-first)* — ✅ DONE

`src/sc2_game_renderer/enemy_memory.py`: `EnemyMemory.update(frame)` called once per
sampled frame in loop order; `.remembered(loop)` returns out-of-vision enemies within
TTL, oldest first. A unit enters memory the frame after it drops out of both
`enemy_visible` and `enemy_snapshot`; re-sighting (either category) or TTL expiry
removes it.

**Verified:** `tests/test_enemy_memory.py`, 11 tests, synthetic frames (no SC2/fixture
needed) — lost-unit tracking, age computation, `last_seen_loop` staying fixed across
consecutive absent frames, re-sighting at a new position, the visible→snapshot
transition (a structure must not be double-tracked), TTL expiry, multi-unit
independence, sort order.

## Slice 3 — Frame file format + `extract` CLI — ✅ DONE

`src/sc2_game_renderer/frame_file.py` (pure: `GameHeader`/`ExtractedFrame` dataclasses,
`write_frame_file`, streaming `FrameFileReader`) behind `src/sc2_game_renderer/
cli_extract.py`, on top of a new thin, deliberately untested adapter
`sc2_stepper.py` (`ReplaySession` — owns `SC2Process`/`start_replay`/`step`, carries
forward slice 0's fixes: absolute-path replay start with a `replay_data` fallback,
fog always on).

**Verified — pure layer:** `tests/test_frame_file.py`, 5 tests, round-trips the real
51-frame fixture through the actual extraction pipeline (`frame_from_observation` +
`EnemyMemory`) byte-for-byte, including the `remembered_enemies` category.

**Verified — SC2 layer, in Docker, against the full fixture replay:**

| | |
| --- | --- |
| Output | 3,809 frames, 3.7 MB — matches slice 0's spike run exactly |
| Wall time | 5m29s (SC2 boot + full stepping + write) |
| Cross-check | Frame at loop 12768 inside the *full* 3,809-frame run reads 108/42/27/125/81:118 — identical to the 51-frame fixture's documented values, plus 39 units the memory tracker is holding that neither raw category shows |
| End state | Last frame: 0 own units, supply 0/0 — the recorded defeat |

`extract` is invoked via `docker run … sc2-extract:4.10 -m sc2_game_renderer.
cli_extract <replay> --player <id> --out <path>`, mounting `src/` at `/work/src` with
`PYTHONPATH=/work/src`, plus the replay and the map file from local SC2. Worth turning
into a `docker/run-extract.sh` wrapper once slice 4 stabilizes the interface — held
off since it would still be a one-file convenience wrapper, not new logic.

## Slice 4 — `stderr.log` parser + joiner *(test-first)* — ✅ DONE

`src/sc2_game_renderer/bot_log.py`, three pure layers:

- `parse_log_lines`: raw line → `LogLine` (the sharpy prefix — clock, loop, step ms,
  minerals, gas, supply, level, logger, message). Clock is captured but deliberately
  unparsed further: its shape differs between bot-startup lines (`H:MM:SS` elapsed
  wall time) and in-game lines (`MM:SS` game clock), and game_loop is what everything
  joins on anyway.
- `classify_events`: `LogLine` → `BotEvent | None` against a 12-kind whitelist —
  positioned (`unit_trained`, `build_addon`, `build_gas`, `cancel_building`,
  `no_path`, `unreachable`), banners (`advantage`, `workers_in_danger`,
  `high_working_danger`, `action_error`), and end-of-game (`unit_summary`,
  `resource_summary`, stateful only in tracking which `[GameAnalyzerEnd]` section —
  "Own units:" / "Enemy units:" — the following rows belong to).
- `join_events_to_frames`: nearest-sampled-frame-at-or-after within one sample
  interval, via `bisect`; returns dropped count alongside joined pairs.

Plus `infer_bot_player_id` / `infer_result`, which read two lines that predate the
bot's own logging sink (loguru's default format, not the sharpy prefix) and so need
their own patterns rather than reusing the above.

**Verified — pure layer:** `tests/test_bot_log.py`, 23 tests against the real
`replays/4891371/stderr.log` (2,997 lines) plus synthetic join-boundary cases:

| | |
| --- | --- |
| Parse rate | 99.80% (2991/2997); the 6 failures are exactly matplotlib/mkdir startup noise, pre-sink loguru lines, and aiohttp shutdown chatter — pinned by name, not just a threshold |
| Negative minerals | 4 lines, values `{-100, -50, -46}` — parse correctly, no crash |
| Noise exclusion | 2,243 "Pulling worker" lines (75% of the file) → 0 events |
| Classified events | 722 total across 12 kinds (regression-pinned per-kind counts) |
| `infer_bot_player_id` | 2 |
| `infer_result` | `(2, "Defeat")` |

**Verified — real end-to-end**, joining the real 722 classified events against the
actual `out/4891371.frames.jsonl.gz` from slice 3 (not a synthetic proxy): **all 722
join, 0 dropped** — confirms the replay and the log are genuinely the same game
(loops from the log are exact multiples of 4, matching the bot's own step size and
the frame file's sampling interval). A deliberately mismatched pairing (real events
against a disjoint frame_loops range) drops all 722, as the design requires.

## Slice 5 — Static terrain background

Render `pathing_grid` / `placement_grid` / `terrain_height` + start locations to one
PNG. Establishes the world→pixel transform used by everything after.

**Verify:** open the PNG — ramps, cliffs, and unbuildable areas are legible and the
map is the right way up.

## Slice 6 — Unit rendering + trails

Own units, the three enemy categories (solid / hollow / dashed + age), movement trails
faded by age.

**Verify:** dump ~6 PNGs from across the fixture game and look at them — units are
where the minimap says they should be, remembered enemies visibly differ from live
ones, trails point the right way.

## Slice 7 — HUD sidebar

Resources, income, supply (+ block duration), workers, idle workers, army value, game
clock.

**Verify:** eyeball sampled frames against the replay's own numbers at the same time.

## Slice 8 — Bot-state overlay

Positioned log events drawn in the world (builds/trains at their coordinates, pathing
failures as markers on the failed route endpoints); state banners (income advantage,
worker danger, evacuation) in the sidebar; a recent-events ticker.

Includes the belief-vs-truth cross-check: log-reported minerals/gas/supply beside the
observation's, flagged when they diverge.

**Verify:** at a loop with a known `No path found` line, the frame shows that marker at
those coordinates; at a known `[TrainSCV] … at (x, y)` the marker sits on the command
centre; the resource cross-check reads equal during normal play.

## Slice 9 — `render` CLI → MP4

Pillow frames → raw RGB → `ffmpeg` stdin → MP4. `--fps`, `--resolution`, `--realtime`.

**Verify:** play the MP4 — correct duration, no dropped/duplicated frames, readable at
1× and when paused.

## Slice 10 — Performance pass *(only if needed)*

Measure first. Likely hot spots: full-observation pulls during extract, per-frame
Pillow draw. Fixes only if a 15-min game is unacceptably slow end to end.

---

## Open items

- **Structured streams don't reach the ladder.** Needs a decision in the tbone repo —
  see `docs/SPEC.md` § "Getting the structured streams onto the ladder". Not v1 work,
  but it caps how good the overlay can get for ladder games.
- Output defaults in the spec (resolution, fps, sample interval) are proposals.
- v2 candidates, deliberately out of v1: ground-truth comparison mode
  (`--disable-fog` side-by-side), the structured JSONL streams if they become
  available, running extraction on Proxmox.
