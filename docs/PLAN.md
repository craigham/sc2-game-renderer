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

## Slice 1 — Frame model + mapper *(test-first)*

Pure `observation proto → Frame`: own units, enemy units by visibility category,
resources, supply, workers, army value.

**Verify:** unit tests against the checked-in fixture dump — a known loop yields the
expected unit counts, resource totals, and supply; no SC2 required to run tests.

## Slice 2 — Enemy memory tracker *(test-first)*

Pure. `enemy_tag → (last_seen_loop, pos, type)`, TTL expiry, three-way categorisation
into `visible` / `snapshot` / `remembered`.

**Verify:** synthetic observation sequences — unit seen then lost becomes `remembered`
with correct age; re-sighting moves it back to `visible` and updates position; expiry
drops it after TTL.

## Slice 3 — Frame file format + `extract` CLI

Wire slices 1–2 behind `extract`, write gzipped JSONL (header record + one record per
frame).

**Verify:** round-trip test (write → read → identical frames); running `extract` on the
fixture replay produces a file whose frame count matches the expected game length.

## Slice 4 — `stderr.log` parser + joiner *(test-first)*

Parse the sharpy log prefix (clock, loop, step ms, minerals, gas, supply, level,
logger, message) and classify messages against a whitelist of interesting events —
positioned build/train events, pathing failures, income-advantage changes, worker
danger, action errors, `[GameAnalyzerEnd]` summary. Join to frames by game loop,
nearest-at-or-after within one sample interval; count and report unjoinable records.

Also infer bot player id and game result from the log preamble/postamble.

**Verify:** unit tests against the checked-in `4891371/stderr.log` — parse rate ≥99%
with the only failures being the known container preamble; **negative minerals
(`-100M`) parse correctly**; the 75%-of-lines `zone_defense` "Pulling worker" noise is
excluded by the whitelist; on-boundary, between-sample, and out-of-tolerance join
cases; a deliberately mismatched replay/log pairing reports a high drop count rather
than silently producing an empty overlay.

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
