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
   within it to see entries around the paused frame.

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

The log panel shows raw parsed lines (loop, clock, level, logger, message) only.
**Not included, on purpose:** the classified bot-state overlay — positioned
build/pathing events, banners, the recent-events ticker, and the belief-vs-truth
resource cross-check. Those are MP4-only for now (`render --log`). Porting
`bot_log.py`'s event classifier to JS would roughly double this addition's scope;
worth doing later if wanted, not bundled into this pass.

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
