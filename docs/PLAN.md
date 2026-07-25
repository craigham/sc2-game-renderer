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

## Slice 5 — Static terrain background — ✅ DONE

`src/sc2_game_renderer/coords.py`: `WorldToPixel`, the world↔pixel transform every
later rendering slice reuses. Crops to `playable_area` (only ~72% of the full grid on
the fixture map — the rest is unpathable border, not worth canvas) and flips
vertically, since SC2's y axis increases north but image rows increase downward. The
flip direction is confirmed against the vendored python-sc2 `PixelMap` (its own
`.plot()` uses `origin="lower"`, i.e. raw row 0 is y=0/south) rather than guessed.

`src/sc2_game_renderer/render_terrain.py`: height as grayscale, unpathable cells
(cliffs/water) near-black, pathable-but-unbuildable cells (ramps) blue-tinted, start
locations as red-ring markers.

**Verified — pure transform math** (allowed under non-goal 9; this is geometry, not
an assertion on rendered pixels): `tests/test_coords.py`, 7 tests — corner mapping in
all four directions (the north/south flip is exactly the kind of thing that's easy to
get backwards), scale, and that out-of-bounds points aren't clamped.

**Verified by eye:** `scripts/preview_terrain.py` against the real fixture's frame
file. Result — elevated plateaus at distinct gray levels, diagonal blue-tinted ramps
connecting them, black cliff gaps, one red start-location marker, and the map's
2-player rotational symmetry all clearly legible.

**Observation, not a bug:** `game_info.start_raw.start_locations` returns only
**one** location (ours) despite 2 players in `player_info` — SC2 withholds the
opponent's start location from `RequestGameInfo` itself under fog. Consistent with
this tool's whole premise (render only what the bot could see), so left as-is rather
than "fixed".

## Slice 6 — Unit rendering + trails — ✅ DONE

`src/sc2_game_renderer/trail_tracker.py`: `TrailTracker`, render-time and stateful
like `EnemyMemory` — `unit_tag -> deque of positions`, capped length, dropped
entirely (not faded) the moment a tag leaves `own_units`. Deliberately *not* stored in
the frame file: own-unit trails are always reconstructable by replaying frames in
order, which rendering does anyway, so persisting them would just be redundant derived
data.

`src/sc2_game_renderer/render_units.py`: own units (filled blue), enemy visible
(filled red), enemy snapshot (hollow red — SC2's own remembered structures), enemy
remembered (dashed red + `"Xs ago"` label — our memory tracker's output, already
computed at extraction time and carried on `ExtractedFrame`). Trails as fading
line segments, oldest faintest.

**Verified — pure trail logic:** `tests/test_trail_tracker.py`, 7 tests — append,
length cap dropping oldest first, drop-on-death, no continuity across a gap for a
reappearing tag, multi-unit independence.

**Verified by eye:** `scripts/preview_frames.py` walks the real fixture's frame file
in order (so trail history is correct) and dumps PNGs at 6 loops spanning the game.
The result reads as the actual defeat: loop 12800 shows a visible-red mass gathering
near the map's choke; by 14000 that same mass is sitting on the bot's own base (solid
red — still visible, still happening); by 15200 it's faded to dashed markers with age
labels as the bot loses vision entirely (base destroyed) — solid vs. dashed is
immediately legible as "happening now" vs. "last known", which is the whole point of
the view. Trails fan out from the base in the direction units actually moved.

**Known cosmetic limitation, not fixed now:** age labels overlap illegibly in dense
clusters (e.g. 15+ remembered enemies stacked in one base). Acceptable for v1 — not
required by this slice's verify bar — revisit only if it turns out to matter in
practice (e.g. as part of the slice 9 polish pass).

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
