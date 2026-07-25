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

## Slice 7 — HUD sidebar — ✅ DONE

`src/sc2_game_renderer/supply_block_tracker.py`: `SupplyBlockTracker`, render-time and
stateful like `TrailTracker`/`EnemyMemory` — duration resets to 0 the moment
`frame.supply_blocked` goes false, so consecutive blocked periods don't bleed into
each other.

`src/sc2_game_renderer/render_hud.py`: `render_hud_panel` (clock, minerals/vespene +
rate, supply + `BLOCKED Xs` when applicable, workers + idle count, army value) and
`compose_frame` (map pane + HUD side by side at their natural sizes — fitting to a
final output resolution is a slice 9 concern).

**Verified — pure tracker logic:** `tests/test_supply_block_tracker.py`, 5 tests —
zero when unblocked, zero on the frame a block starts, growing duration across
consecutive blocked frames, reset on unblocking, two separate blocked periods staying
independent.

**Verified by eye, against the replay's own numbers** (this slice's specified bar):
`scripts/preview_frames.py` extended to compose the full map+HUD frame. At loop
12768 the HUD reads minerals=125, supply=81/118 — an exact match to the fixture's
independently-documented values. At loop 0 it reads minerals=50, supply=12/15 —
matching `stderr.log`'s own first `[GameAnalyzer]` line byte for byte.

**Bug found and fixed by this same eyeballing step:** the HUD showed `BLOCKED 27s`
at the fixture's final frame (loop 15200), where the bot is fully wiped out at
0/0 supply. `frame.py`'s original `supply_blocked` condition
(`food_used >= food_cap and food_cap < 200`) is true whenever both are 0 — a
defeated player with no supply structures left isn't meaningfully "blocked," there's
nothing to be blocked *on*. Fixed to require `food_cap > 0`, with a regression test
(`test_supply_blocked_false_when_wiped_out_at_zero_zero`) and a regenerated fixture
frame file confirming the corrected render. This is the second real bug this build
has caught by actually looking at output rather than trusting the code once tests
pass — see slice 1's idle-worker/army-value corrections for the first.

## Slice 8 — Bot-state overlay — ✅ DONE

`src/sc2_game_renderer/bot_state_overlay.py`: `build_overlay(log_text, frame_loops,
sample_loops)` wires slice 4's parser/classifier/joiner into a queryable
`BotStateOverlay` — `events_at(loop)` for per-frame event lookup, and
`resource_belief_at(loop)` (nearest-log-line-at-or-before, since the bot doesn't log
every single step) for the belief-vs-truth cross-check. `IncomeAdvantageTracker` is
the one banner treated as persistent state (the log frames it as "is now X"); worker
danger and evacuation warnings have no "cleared" event in the log, so they're
rendered only on the exact frame they land on, rather than inventing an ungrounded
decay timeout.

`src/sc2_game_renderer/event_ticker.py`: pure `describe_event` formatter +
`EventTicker` (rolling recent-events history) — this is what keeps an event visible
longer than the single frame it's joined to.

`src/sc2_game_renderer/render_bot_events.py`: positioned world markers — yellow
diamonds for builds/trains, orange X's (+ a connecting line for `no_path`, at both
endpoints) for pathing failures.

`render_hud.py` extended with the belief-vs-truth lines (muted when equal, warning-
colored when they diverge), the persistent income-advantage banner, momentary danger
warnings, and the ticker.

**Verified — pure layer:** `tests/test_event_ticker.py` (8 tests) and
`tests/test_bot_state_overlay.py` (13 tests, both a hand-crafted synthetic log and
the real fixture) — join-to-nearest-frame, empty lookups, mismatched-pairing drop
counts, nearest-before belief lookup (including before-any-line and after-last-line
edges), and `IncomeAdvantageTracker`'s metric filtering.

**Verified by eye, exactly per this slice's bar**, via `scripts/preview_frames.py`
extended with `--log`:

- **`No path found`** (loop 13316): the orange X + connecting line sit precisely at
  the failed route's two endpoints — which turned out to be right where the enemy
  army was standing, explaining *why* the path failed.
- **`[TrainSCV] … at (42.5, 46.5)`** (loop 340): the yellow diamond sits exactly on
  the command center, confirmed by cropping and zooming into that region.
- **Resource cross-check reads equal during normal play**: confirmed at loops 12768
  and 13316 — both show "bot believed" matching truth with no warning color.

**Real discrepancy found, not a bug:** at loop 340, the cross-check flagged a genuine
divergence — bot believed 5 minerals, true observation was 55, a gap of exactly 50
(an SCV's cost). Confirmed directly against `stderr.log:27`. This is the actual bot
internal-state-vs-game-truth timing gap the cross-check exists to catch, not a
rendering defect — exactly the "separate bad information from bad decisions"
payoff the spec is built around.

**Known cosmetic limitation, not fixed now:** long state names (e.g.
"OverwhelmingDisadvantage") overflow the 280px sidebar width. Same category as
slice 6's label-overlap finding — deferred to the slice 9 polish pass.

## Slice 9 — `render` CLI → MP4 — ✅ DONE

`src/sc2_game_renderer/layout.py`: `compute_layout`, pure geometry that fits the map
pane into (output_resolution − fixed-width sidebar) via letterboxing rather than
stretching — stretching would silently corrupt every world→pixel position. Feeds
`render_terrain`/`WorldToPixel` the exact scale needed, and its rounding matches
theirs exactly, so the map image never needs a resize once rendered — just a paste.

`render_hud.assemble_frame` composes the letterboxed map + HUD into one frame
guaranteed to be exactly (output_width, output_height) — the property that makes it
safe to pipe straight to ffmpeg as fixed-size rawvideo.

`src/sc2_game_renderer/cli_render.py`: the full pipeline — one upfront pass over the
frame file to collect game loops (for the bot-log join), then a second pass per
frame running every render-time tracker from slices 6-8 (trails, supply-block
duration, income-advantage state, event ticker) and piping raw RGB straight to
`ffmpeg -f rawvideo ... -i - ... out.mp4`. `-loglevel error` keeps ffmpeg's stderr
pipe empty in the normal case, avoiding a real deadlock risk (ffmpeg blocking on a
full stderr pipe while this process blocks writing more stdin) without needing a
separate reader thread.

**Bugs found and fixed by actually running it, not just reading the code:**

1. Calling `proc.communicate()` after manually closing `proc.stdin` raised
   `ValueError: flush of closed file` — `communicate()` tries to close stdin itself.
   Fixed to `stdin.close(); wait(); stderr.read()` instead. (The MP4 itself was
   already correct when this hit — ffmpeg had already exited — but the CLI itself
   crashed on cleanup, which would be confusing to hit for real.)
2. `--realtime` rounded 5.6fps (`22.4 / sample_loops=4`) to 6fps, which ran the
   fixture's full replay in 634.8s instead of the true 680.0s game length — a 7%
   speedup that would make "realtime" a misnomer. Fixed by passing the exact
   fractional rate straight to ffmpeg's `-r` (it accepts non-integer rates natively)
   instead of rounding for display. Confirmed via ffprobe: `r_frame_rate=28/5`
   (exactly 5.6), duration 680.18s — matching the game length to within one frame
   interval.

**Verified — pure layout math:** `tests/test_layout.py`, 5 tests — square-into-square
(no letterbox), wide-map and tall-map letterboxing in both axes, and the real
fixture's actual shape (square map, 1280×720 output, 280px sidebar) producing the
exact expected offset.

**Verified — the real thing, end to end**, against the full fixture replay:

| | Default (`--fps 30`) | `--realtime` |
| --- | --- | --- |
| Frames | 3,809 | 3,809 |
| Resolution | 1280×720 | 1280×720 |
| `r_frame_rate` (ffprobe) | 30/1 | 28/5 (= 5.6 exactly) |
| Duration (ffprobe) | 126.966016s | 680.178571s |
| Expected | 3809/30 = 126.9667s ✓ | ≈15232/22.4 = 680.0s ✓ (within one frame interval) |

No dropped or duplicated frames — `render()` asserts the written count equals the
frame file's own frame count before returning. **Readable when paused:** extracted
exact frames from the encoded MP4 with `ffmpeg -vf select=eq(n\,N)` (frame-accurate;
plain `-ss` before `-i` does fast keyframe-only seeking and landed on the wrong
frame the first time this was tried) at frame 85 (loop 340) and frame 3192 (loop
12768) — both reproduce slice 7/8's documented values exactly, byte-for-byte,
confirming the encode is faithful: minerals 55/believed 5, and 125/125/supply
81:118, respectively.

## Addition — interactive browser viewer — ✅ DONE

Requested after slice 9: click a unit to see its state (health, current command),
in a browser, as an *addition* alongside the MP4 pipeline — not a replacement. See
`docs/SPEC.md` § Stage 2b for the architecture (one frame file, two independent
renderers).

Two parts:

1. **Unit orders in the data model.** `Frame`/`UnitSnapshot` didn't capture "current
   command" at all before this. Added `UnitOrder` (`frame.py`: ability_id, a
   target — unit tag or world position, mutually exclusive via the proto's `target`
   oneof — and progress) and wired it through `frame_file.py`'s (de)serialization.
   Confirmed directly against the fixture, not assumed: **SC2 only ever populates
   orders for the observing player's own units** — 0 of 69 enemy units had any order
   vs. 81 of 108 own units, the same fog-of-war-applies-to-metadata pattern already
   found for `start_locations` in slice 5. Required a fresh Docker extraction (the
   previously-generated frame file predates this field).

2. **`viewer/`** — static HTML+JS+CSS, no server, no build step. `index.html` +
   `viewer.js` + `viewer.css`, plus `data/ability_names.js` / `unit_type_names.js`
   (static id→name tables generated once by `scripts/generate_id_names.py` from
   burnysc2's enums). Loads a `.frames.jsonl.gz` via `<input type="file">` +
   the browser's native `DecompressionStream('gzip')` — deliberately not `fetch()`,
   which most browsers refuse for local `file://` pages, and deliberately not
   `.json` files, for the same reason (shipped as `<script src>`-loaded `.js`
   instead). Terrain decode, the world↔pixel transform, and the unit/HUD drawing
   are the same logic as `coords.py`/`render_terrain.py`/`render_units.py`, ported to
   JS/canvas — this is the one place that duplication was accepted, since a browser
   can't run the Python renderer.

   **Explicitly out of scope for this addition:** the `stderr.log` bot-state overlay
   (events, banners, ticker, belief cross-check) — porting `bot_log.py` to JS would
   roughly double this addition's scope. MP4-only for now; noted in `viewer/README.md`
   as a clearly-scoped follow-up, not a silent gap.

**Verified — pure layer:** existing `frame`/`frame_file` test suites extended with 5
new tests using real fixture examples for each of the three order shapes (unit
target, world-position target, no-target-with-progress) plus the enemy-never-has-
orders and idle-own-unit-has-no-orders invariants. All 99 tests pass.

**Verified in a real browser**, via the Browser pane tool. Hit one real environment
constraint doing this: the pane's file-input automation can't drive a native OS file
picker, and separately its `navigate` reuses a cached DOM/state snapshot across
reloads of the same local file rather than re-executing fresh each time (confirmed:
query-string parameters were silently dropped, and stale panel content survived a
"fresh" navigate). Worked around both with a throwaway same-realm test harness
(deleted before commit) that called the viewer's own functions directly — not a
workaround in the shipped code, just in how it was tested. Confirmed:

- Header parse: map name, frame count, `bot_player_id` all correct.
- Terrain renders correctly (plateaus/ramps/cliffs match the Python renderer).
- Scrubbing to loop 12768 reproduces the documented fixture values exactly
  (minerals 125, supply 81/118, army value 1900m/475g).
- **Click-to-inspect, the actual feature requested:** clicking an own SCV showed
  `HARVEST_GATHER_SCV → unit 4299948033`, health 45/45 — a human-readable order name,
  not a raw ability id.
- **A real bug caught by testing, not spotted in review:** the first version showed
  "idle" for a *remembered* enemy unit's orders — technically true (no orders field
  populated) but misleading, since it implies certainty about something fog hides.
  Fixed to say "not visible through fog" for any non-own unit; own units still
  correctly show real "idle" when they truly have no queued order (verified both
  cases explicitly, plus the own-unit-with-a-real-order case, against real fixture
  data with an explicit debug harness rather than trusting a screenshot read — which
  also caught that a unit tag and an age had been misread by eye from an earlier
  screenshot before being double-checked against the actual data).
- Play button advances frames continuously with live HUD updates, and the selected
  unit panel correctly follows the same unit across playback frames.

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
