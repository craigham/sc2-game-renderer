# Own Unit Census Panel

Date: 2026-07-27  
Status: approved design (pending implementation plan)

## Goal

Add a side-pane table in the interactive browser viewer that shows, as of the
currently scrubbed frame, how many of each **own** army/worker unit type are
alive vs dead so far in the game.

Example:

```
Type      Alive  Dead
SCV          23     0
Marine       45    12
```

## Scope

**In scope**

- Viewer only: `viewer/index.html`, `viewer/viewer.js`, `viewer/viewer.css`
- Own units only
- Army + workers only (skip structures via `is_structure`)
- Collapse known Terran morph variants into one row
- Recompute on each scrub/step/playback frame (approach: scan `frames[0..currentIndex]` each update)
- Bump `viewer.js?v=` / `viewer.css?v=` cache-busters in `index.html`

**Out of scope**

- Enemy unit census
- Structures in the table
- Python extract / frame-file schema changes
- MP4 / Pillow HUD overlay
- Precomputing a per-frame census cache on load (rejected in favor of simpler per-scrub scan)

## UI

- New `#unitCensus` element in `#sidePane`, after `#botAnalysis`, before `#unitDetail`.
- Section label: `Own Units` (same `.section-label` styling as Game Analyzer / Build Detector).
- Compact monospace table with columns: Type | Alive | Dead.
- One row per canonical type that has ever been seen by the current frame (including alive 0 / dead N).
- Sort: alive descending, then type name ascending.
- Display names use existing `unitTypeName()` (enum-style names from `UNIT_TYPE_NAMES`, e.g. `SCV`, `MARINE`).
- Independent of bot log load: census comes from frame data only. Placeholder when no frames are loaded: e.g. `Load a frame file to see unit counts`.

## Counting model

Pure function conceptually: `computeOwnUnitCensus(frames, throughIndex) → [{ typeId, name, alive, dead }, ...]`.

1. Consider only `frame.own_units`.
2. Skip units where `is_structure === true`. If `is_structure` is missing (older frame files), treat as non-structure and include (same defensive pattern as other optional fields).
3. Map each unit's `unit_type` through a Terran morph canonical map before counting (see below).
4. Walk frames `0..throughIndex` inclusive:
   - Maintain `lastCanonicalTypeByTag: Map<tag, typeId>`.
   - On each frame, for each included own unit, set/update the tag's canonical type.
5. After the walk, for the current frame's alive tags (included own units only):
   - **Alive**: count by canonical type among tags present now.
   - **Dead**: every tag ever seen whose tag is not in the current alive set; credit to `lastCanonicalTypeByTag`.
6. Display name via existing `unitTypeName(id)` / `UNIT_TYPE_NAMES`.

Morph ≠ death: if a tag remains present but its `unit_type` changes (e.g. SiegeTank → SiegeTankSieged), update the canonical type only; do not increment dead.

### Terran morph canonical map

Hardcoded id→base-id map in `viewer.js` covering common Terran army morphs (numeric ids from `UNIT_TYPE_NAMES`):

| Variant | Base |
|---------|------|
| SIEGETANKSIEGED (32) | SIEGETANK (33) |
| HELLIONTANK (484) | HELLION (53) |
| VIKINGASSAULT (34) | VIKINGFIGHTER (35) |
| WIDOWMINEBURROWED (500) | WIDOWMINE (498) |
| THORAP (691) | THOR (52) |
| LIBERATORAG (734) | LIBERATOR (689) |

Map stores variant→base only; base ids and all other types fall through as identity. Display uses the base id's name.

Workers (SCV) and non-morphing army types map to themselves (identity).

## Architecture

| Piece | Role |
|-------|------|
| `#unitCensus` | DOM mount point |
| `TERRAN_MORPH_CANONICAL` | static `{ [variantId]: baseId }` |
| `canonicalUnitType(id)` | lookup with identity fallback |
| `computeOwnUnitCensus(frames, throughIndex)` | pure tally |
| `updateUnitCensusPanel(index)` | render HTML table into `#unitCensus` |
| `renderFrame` | calls `updateUnitCensusPanel(index)` alongside HUD updates |

No shared state with the bot-log Game Analyzer panel beyond physical placement under it.

## Performance note

Recomputing by scanning all frames up to the scrub position on every `renderFrame` is intentional (chosen over precompute). Acceptable for typical match sizes; if scrub hitching appears later, a follow-up can add an on-load prefix cache without changing the UI contract.

## Edge cases

| Case | Behavior |
|------|----------|
| No frames loaded | Placeholder text |
| Frame 0 / early game | Alive counts only; dead 0 |
| Unit dies (tag leaves `own_units`) | Dead +1 on last canonical type |
| Unit morphs (same tag, new type) | No death; row follows canonical type |
| All of a type dead | Row remains with alive 0, dead N |
| Structure (CC, Depot, Barracks, …) | Excluded |
| Addon / flying structure morphs | Excluded via `is_structure` |

## Testing

- Manual: load a known match, scrub early/mid/late; confirm SCV/Marine-style rows, deaths increase when army is lost, morphing tanks do not inflate dead.
- Optional lightweight check: hand-built mini frame arrays exercised against `computeOwnUnitCensus` if a no-build-step JS test harness is added; not required for v1 if none exists.

## Success criteria

1. Side pane shows Own Units table under Game Analyzer / Build Detector when frames are loaded.
2. Table updates as the user scrubs/steps/plays.
3. Own army + workers only; structures absent.
4. Morph variants share one row; morphing does not count as death.
5. Cache-buster bumped so test_lab embeds pick up the change after deploy.
