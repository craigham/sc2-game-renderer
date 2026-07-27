# Interactive browser viewer

An addition alongside the batch MP4 pipeline (`render`), not a replacement — see
`docs/SPEC.md` § Stage 2b. Reads the same `.frames.jsonl.gz` file `extract` produces.
No server, no build step, no npm.

## Use

1. Open `viewer/index.html` directly in a browser (double-click it, or `open
   viewer/index.html`).
2. Click "Choose File" and pick a `.frames.jsonl.gz` from `out/`.
3. Scrub, play/pause, step frame-by-frame. Click any unit marker to inspect it —
   health, shields, energy, and (own units only) current order(s).
4. Optionally also pick the match's `stderr.log` in the second file input to populate
   the log panel at the bottom of the page. Drag the handle above it to resize. The
   panel scrolls to and highlights the log line nearest the current frame's game
   loop — but only when playback is paused, stepped, or scrubbed, never while
   playing, so it doesn't fight a manual scroll 10 times a second. Scroll freely
   within it to see entries around the paused frame. Only the ~400 lines around
   that position are actually in the DOM at once (real match logs can run 80k+
   lines — rendering the whole table plus `scrollIntoView` on it measured at
   ~13s on one such log); scrubbing further re-centers the window.

Requires a browser with `DecompressionStream` (Chrome/Edge 80+, Firefox 113+, Safari
16.4+) — all recent.

Alternatively, when this page is served over real http(s) (not `file://`), passing
`?frames=<url>` loads that frame file automatically via `fetch()`, skipping the file
picker — e.g. `index.html?frames=/frames/1234.frames.jsonl.gz`. This is how
`sc_bot_test_lab`'s replay-render view drives it.

## What it does and doesn't show

Same visual language as the Python renderer (`render_terrain.py` / `render_units.py`):
own units filled blue, enemy visible filled red, enemy structures SC2 remembers
through fog hollow red, enemy positions this tool remembers dashed red with an age
label.

**Structures vs. mobile units:** both are sized proportional to their real per-unit
`radius` (from the observation, not a guess), so a Command Center reads much larger
than an SCV, and shaded a step darker/more muted than the same-side unit color —
still one recognizable hue per side, not a new marker shape. Classified via SC2's own
game data (the `Structure` attribute, fetched once per extraction), not inferred from
radius or health alone — a Thor or Ultralisk has a large radius too, but isn't a
structure.

**Enemy structures stay on screen through fog** as the hollow "snapshot" marker
(SC2's own memory, not this tool's) for as long as SC2 itself remembers them.
Clicking one adds "last seen Xs ago" when it can be determined — computed here in
the browser (not extracted in Python) by scanning backward through the already-loaded
frames for the most recent sampled frame where that same tag was directly
`enemy_visible`. **This often comes back empty, and that's real, not a bug**: checked
against the fixture, and a structure can go straight from "never seen" to a snapshot
with no `enemy_visible` sighting anywhere in the sampled data — a fast pass (a raid,
a drop) can cross a structure's vision radius in under one sample interval (~0.18s of
game time at the default 4-loop sampling) even though SC2 itself registered the
reveal at the time. The panel says "no directly-observed sighting in sampled data"
rather than silently omitting the age, since in this fixture that's the *common*
case, not rare. (Separately, and unexpectedly: SC2 doesn't always keep a structure
snapshotted forever once first seen either — one was observed going fully absent for
several minutes, then reappearing later. Not chased further here; worth keeping in
mind if `enemy_snapshot` ever seems to have fewer entries than expected.)

**Weapon range circle:** clicking a unit with a weapon draws a dashed circle at its
real range (from SC2's own game data, `UnitTypeData.weapons` — max across all of a
unit's weapons if it has more than one, e.g. a Thor's separate ground/air ranges).
Zero for unarmed units (most workers/structures) — no circle, not an error. Frame
files extracted before this field existed have no `weapon_range` at all; the check is
`> 0`, which is `false` for `undefined` too, so those just don't show a circle rather
than throwing.

**Game Analyzer / Build Detector summary**, in its own panel below the HUD: the
bot's persistent last-known state — each `[GameAnalyzer]` metric (Income/Known
army/Predicted army advantage) at its latest value, plus `terranbot/managers/
build_detector.py`'s recognized enemy build and any flagged rush hypotheses (these
only ever accumulate — the log has no "ruled out" event). This is recomputed **as of
the currently paused frame's game loop**, not the whole game at once, so scrubbing
backward genuinely shows what was known then, not future knowledge (verified
directly: an event placed after the paused frame in a synthetic log correctly does
not appear).

The log panel itself shows raw parsed lines (loop, clock, level, logger, message).
**Still not included:** the rest of the classified bot-state overlay — positioned
build/pathing events, the recent-events ticker, and the belief-vs-truth resource
cross-check. Those stay MP4-only (`render --log`) for now. The Game Analyzer/Build
Detector summary above is a deliberately scoped subset of `bot_log.py`'s classifier
(3 event kinds, not the full whitelist) — porting the rest would still meaningfully
grow this addition's scope; worth doing later if wanted, not bundled into this pass.

**Current order(s):** SC2 only ever reports a unit's queued order for units you own
— an enemy's order would leak intel straight through fog, so it's simply absent from
the observation for enemy units (confirmed directly against real data: 0 of 69 enemy
units had any order in the fixture, vs. 81 of 108 own units). The panel says "not
visible through fog" for enemy/remembered units rather than "idle", since "idle"
would falsely claim knowledge we don't have.

## Files

| File | Role |
| --- | --- |
| `index.html` | page skeleton |
| `viewer.css` | dark theme, matches the Python renderer's palette |
| `viewer.js` | everything: gzip decompression, terrain decode, world↔pixel transform, unit/HUD rendering, click hit-testing |
| `data/ability_names.js`, `data/unit_type_names.js` | static id→name tables, generated once by `scripts/generate_id_names.py` from burnysc2's enums — shipped as `<script src>`-loaded `.js` (not `.json` + `fetch()`, which most browsers refuse for local `file://` pages) |

Regenerate the name tables only if burnysc2 is upgraded to a version with new/renamed
ids:

```bash
uv run python scripts/generate_id_names.py
```
