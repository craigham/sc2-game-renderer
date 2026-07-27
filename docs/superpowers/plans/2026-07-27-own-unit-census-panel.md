# Own Unit Census Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a side-pane table in the browser viewer showing, as of the scrubbed frame, alive vs dead counts for each own army/worker unit type (morphs collapsed, structures excluded).

**Architecture:** Pure tally logic lives in a small `viewer/unit_census.js` script (no DOM) so it can be exercised with Node's built-in `assert` without adding npm. `viewer.js` calls `computeOwnUnitCensus(frames, index)` on every `renderFrame` and renders a compact table into `#unitCensus` under the Game Analyzer panel.

**Tech Stack:** Vanilla JS (existing viewer), HTML/CSS, Node.js `assert` + `vm` for pure-logic tests (no package.json / build step).

## Global Constraints

- Own units only; army + workers only (`is_structure === true` excluded; missing `is_structure` → include).
- Collapse Terran morph variants via hardcoded id map (see Task 1).
- Recompute by scanning `frames[0..throughIndex]` on each scrub (no on-load cache).
- Viewer-only; no Python extract / MP4 changes.
- Bump `viewer.js?v=` and `viewer.css?v=` (and add `unit_census.js?v=`) in `index.html` on ship.
- Display names via existing `unitTypeName()` / `UNIT_TYPE_NAMES` (enum-style: `SCV`, `MARINE`).

## File structure

| File | Responsibility |
|------|----------------|
| `viewer/unit_census.js` | Morph map, `canonicalUnitType`, `computeOwnUnitCensus` (pure) |
| `tests/test_own_unit_census.mjs` | Node assert tests for the pure tally |
| `viewer/viewer.js` | `updateUnitCensusPanel` + call from `renderFrame` |
| `viewer/index.html` | `#unitCensus` mount + script tag + cache-busters |
| `viewer/viewer.css` | Compact census table styles |
| `viewer/README.md` | One short paragraph documenting the panel |

---

### Task 1: Pure census logic + Node tests

**Files:**
- Create: `viewer/unit_census.js`
- Create: `tests/test_own_unit_census.mjs`
- Test: `tests/test_own_unit_census.mjs`

**Interfaces:**
- Consumes: none (tests stub `unitTypeName` if needed; production uses global from `viewer.js`)
- Produces:
  - `canonicalUnitType(id: number): number`
  - `computeOwnUnitCensus(frames: Array<{own_units: Array}>, throughIndex: number): Array<{typeId: number, name: string, alive: number, dead: number}>`
  - Globals attached on `globalThis` for the browser script tag

- [ ] **Step 1: Write the failing Node test**

Create `tests/test_own_unit_census.mjs`:

```js
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const src = fs.readFileSync(path.join(root, "viewer/unit_census.js"), "utf8");

const context = {
  unitTypeName(id) {
    const names = {
      45: "SCV",
      48: "MARINE",
      33: "SIEGETANK",
      32: "SIEGETANKSIEGED",
      18: "COMMANDCENTER",
    };
    return names[id] || `Type ${id}`;
  },
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(src, context);

const { canonicalUnitType, computeOwnUnitCensus } = context;

function u(tag, unit_type, is_structure) {
  const out = { tag, unit_type };
  if (is_structure !== undefined) out.is_structure = is_structure;
  return out;
}
function frame(own_units) {
  return { own_units };
}

assert.equal(canonicalUnitType(32), 33); // sieged → tank
assert.equal(canonicalUnitType(48), 48); // marine identity

// Alive only at frame 0
{
  const frames = [frame([u(1, 45, false), u(2, 48, false), u(3, 18, true)])];
  const rows = computeOwnUnitCensus(frames, 0);
  assert.deepEqual(
    rows.map((r) => [r.name, r.alive, r.dead]),
    [
      ["SCV", 1, 0],
      ["MARINE", 1, 0],
    ],
  );
}

// Death: marine tag disappears
{
  const frames = [
    frame([u(1, 45, false), u(2, 48, false)]),
    frame([u(1, 45, false)]),
  ];
  const rows = computeOwnUnitCensus(frames, 1);
  const byName = Object.fromEntries(rows.map((r) => [r.name, r]));
  assert.equal(byName.SCV.alive, 1);
  assert.equal(byName.SCV.dead, 0);
  assert.equal(byName.MARINE.alive, 0);
  assert.equal(byName.MARINE.dead, 1);
}

// Morph ≠ death: same tag, sieged then tank type
{
  const frames = [
    frame([u(9, 33, false)]),
    frame([u(9, 32, false)]),
  ];
  const rows = computeOwnUnitCensus(frames, 1);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].name, "SIEGETANK");
  assert.equal(rows[0].alive, 1);
  assert.equal(rows[0].dead, 0);
}

// Missing is_structure → include
{
  const frames = [frame([u(1, 48)])];
  const rows = computeOwnUnitCensus(frames, 0);
  assert.equal(rows[0].name, "MARINE");
  assert.equal(rows[0].alive, 1);
}

console.log("ok");
```

Note: `unit_census.js` must define `canonicalUnitType` / `computeOwnUnitCensus` as top-level `function` declarations (or assign them onto `globalThis`) so both the browser and the `vm` harness can see them. Prefer:

```js
function canonicalUnitType(id) { ... }
function computeOwnUnitCensus(frames, throughIndex) { ... }
if (typeof globalThis !== "undefined") {
  globalThis.canonicalUnitType = canonicalUnitType;
  globalThis.computeOwnUnitCensus = computeOwnUnitCensus;
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node tests/test_own_unit_census.mjs`  
Expected: FAIL with `ENOENT` (file missing) or `canonicalUnitType is not defined`

- [ ] **Step 3: Implement `viewer/unit_census.js`**

```js
// Own army/worker census as of a scrubbed frame. Pure — no DOM.
// Morph variants collapse to a base type id (variant → base only).

const TERRAN_MORPH_CANONICAL = {
  32: 33,   // SIEGETANKSIEGED → SIEGETANK
  484: 53,  // HELLIONTANK → HELLION
  34: 35,   // VIKINGASSAULT → VIKINGFIGHTER
  500: 498, // WIDOWMINEBURROWED → WIDOWMINE
  691: 52,  // THORAP → THOR
  734: 689, // LIBERATORAG → LIBERATOR
};

function canonicalUnitType(id) {
  return TERRAN_MORPH_CANONICAL[id] ?? id;
}

function isCensusUnit(u) {
  // Older frame files may omit is_structure — include those (same defensive
  // pattern as other optional fields in the viewer).
  return u.is_structure !== true;
}

/**
 * @param {Array<{own_units: Array}>} frames
 * @param {number} throughIndex inclusive
 * @returns {Array<{typeId: number, name: string, alive: number, dead: number}>}
 */
function computeOwnUnitCensus(frames, throughIndex) {
  if (!frames || frames.length === 0 || throughIndex < 0) return [];

  const end = Math.min(throughIndex, frames.length - 1);
  const lastCanonicalTypeByTag = new Map();

  for (let i = 0; i <= end; i++) {
    const own = frames[i].own_units || [];
    for (const u of own) {
      if (!isCensusUnit(u)) continue;
      lastCanonicalTypeByTag.set(u.tag, canonicalUnitType(u.unit_type));
    }
  }

  const current = frames[end].own_units || [];
  const aliveTags = new Set();
  const aliveCounts = new Map(); // typeId → count

  for (const u of current) {
    if (!isCensusUnit(u)) continue;
    const typeId = canonicalUnitType(u.unit_type);
    aliveTags.add(u.tag);
    lastCanonicalTypeByTag.set(u.tag, typeId);
    aliveCounts.set(typeId, (aliveCounts.get(typeId) || 0) + 1);
  }

  const deadCounts = new Map();
  for (const [tag, typeId] of lastCanonicalTypeByTag) {
    if (aliveTags.has(tag)) continue;
    deadCounts.set(typeId, (deadCounts.get(typeId) || 0) + 1);
  }

  const typeIds = new Set([...aliveCounts.keys(), ...deadCounts.keys()]);
  const nameFn = typeof unitTypeName === "function" ? unitTypeName : (id) => `Type ${id}`;

  const rows = [];
  for (const typeId of typeIds) {
    rows.push({
      typeId,
      name: nameFn(typeId),
      alive: aliveCounts.get(typeId) || 0,
      dead: deadCounts.get(typeId) || 0,
    });
  }

  rows.sort((a, b) => b.alive - a.alive || a.name.localeCompare(b.name));
  return rows;
}

if (typeof globalThis !== "undefined") {
  globalThis.canonicalUnitType = canonicalUnitType;
  globalThis.computeOwnUnitCensus = computeOwnUnitCensus;
}
```

- [ ] **Step 4: Run tests and make sure they pass**

Run: `node tests/test_own_unit_census.mjs`  
Expected: `ok` and exit code 0

- [ ] **Step 5: Commit**

```bash
git add viewer/unit_census.js tests/test_own_unit_census.mjs
git commit -m "$(cat <<'EOF'
Add own-unit alive/dead census tally with Node tests.

EOF
)"
```

---

### Task 2: Wire panel into the viewer UI

**Files:**
- Modify: `viewer/index.html`
- Modify: `viewer/viewer.js` (add `updateUnitCensusPanel`; call from `renderFrame`)
- Modify: `viewer/viewer.css`
- Test: manual browser load + `node tests/test_own_unit_census.mjs` still passes

**Interfaces:**
- Consumes: `computeOwnUnitCensus(frames, throughIndex)` from Task 1 (global)
- Produces: `#unitCensus` DOM updated on every `renderFrame`

- [ ] **Step 1: Add mount point and script tag in `viewer/index.html`**

In `#sidePane`, after `#botAnalysis` / its `<hr>`, before `#unitDetail`:

```html
    <div id="botAnalysis"><em>Load a bot log to see Game Analyzer / Build Detector</em></div>
    <hr>
    <div id="unitCensus"><em>Load a frame file to see unit counts</em></div>
    <hr>
    <div id="unitDetail"><em>Click a unit to inspect it</em></div>
```

Before `viewer.js`, load the census script. Bump cache-busters (`viewer.css` 5→6, `viewer.js` 7→8, census at `v=1`):

```html
<link rel="stylesheet" href="viewer.css?v=6">
...
<script src="data/ability_names.js"></script>
<script src="data/unit_type_names.js"></script>
<script src="unit_census.js?v=1"></script>
<script src="viewer.js?v=8"></script>
```

- [ ] **Step 2: Add CSS for the census table in `viewer/viewer.css`**

Append:

```css
#unitCensusTable {
  width: 100%;
  border-collapse: collapse;
  font-family: "SF Mono", Menlo, monospace;
  font-size: 12px;
  margin-top: 4px;
}

#unitCensusTable th,
#unitCensusTable td {
  text-align: left;
  padding: 1px 4px;
  border-bottom: 1px solid #22222a;
}

#unitCensusTable th:nth-child(2),
#unitCensusTable td:nth-child(2),
#unitCensusTable th:nth-child(3),
#unitCensusTable td:nth-child(3) {
  text-align: right;
  font-variant-numeric: tabular-nums;
  width: 48px;
}

#unitCensusTable thead th {
  color: #8c8c96;
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: 0.04em;
  font-weight: 600;
}
```

- [ ] **Step 3: Add panel updater and hook `renderFrame` in `viewer/viewer.js`**

Add near the HUD helpers (after `updateHud` is fine):

```js
function updateUnitCensusPanel(index) {
  const el = document.getElementById("unitCensus");
  if (!el) return;
  if (!frames || frames.length === 0) {
    el.innerHTML = "<em>Load a frame file to see unit counts</em>";
    return;
  }
  const rows = computeOwnUnitCensus(frames, index);
  if (rows.length === 0) {
    el.innerHTML = `<div class="section-label">Own Units</div><em>No army/workers yet</em>`;
    return;
  }
  let html = `<div class="section-label">Own Units</div>`;
  html += `<table id="unitCensusTable"><thead><tr><th>Type</th><th>Alive</th><th>Dead</th></tr></thead><tbody>`;
  for (const r of rows) {
    html += `<tr><td>${escapeHtml(r.name)}</td><td>${r.alive}</td><td>${r.dead}</td></tr>`;
  }
  html += `</tbody></table>`;
  el.innerHTML = html;
}
```

In `renderFrame`, after `updateHud(frame);` (and with the other panel updates), add:

```js
  updateUnitCensusPanel(index);
```

`escapeHtml` already exists later in `viewer.js` — either move `escapeHtml` above this function, or inline a local escape for the name cell. Prefer moving the existing `escapeHtml` definition above first use (or call it only if already hoisted — it is a `function` declaration today near the log panel, so it is hoisted; no move required).

- [ ] **Step 4: Sanity-check tests still pass**

Run: `node tests/test_own_unit_census.mjs`  
Expected: `ok`

- [ ] **Step 5: Manual browser check**

Open `viewer/index.html`, load a `.frames.jsonl.gz`:

1. Side pane shows **Own Units** table under Game Analyzer / Build Detector.
2. Scrub early → mostly alive, dead near 0.
3. Scrub after a fight → dead counts rise for lost army types.
4. Structures (CC, Depot, Barracks) do not appear as rows.
5. If the match has siege tanks, sieged/unsieged share one `SIEGETANK` row.

- [ ] **Step 6: Commit**

```bash
git add viewer/index.html viewer/viewer.js viewer/viewer.css
git commit -m "$(cat <<'EOF'
Show own unit alive/dead census in the viewer side pane.

EOF
)"
```

---

### Task 3: Document in viewer README

**Files:**
- Modify: `viewer/README.md`
- Test: read-through only (no automated test)

**Interfaces:**
- Consumes: UI behavior from Task 2
- Produces: short user-facing description

- [ ] **Step 1: Add a paragraph after the Game Analyzer section**

Insert after the Game Analyzer / Build Detector paragraph (~line 80):

```markdown
**Own Units census**, below Game Analyzer / Build Detector: a live table of your
army and workers (structures excluded) with alive and dead counts as of the
current scrub position. Counts come from frame tags — a unit is dead once its
tag leaves `own_units`. Terran morph variants (siege mode, Hellbat, Liberator AG,
etc.) collapse to one row so a morph is not counted as a death. Recomputed on
every frame change by scanning frames up to the scrub index (no bot log required).
```

- [ ] **Step 2: Commit**

```bash
git add viewer/README.md
git commit -m "$(cat <<'EOF'
Document the own-units census panel in the viewer README.

EOF
)"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| `#unitCensus` under bot analysis, before unit detail | Task 2 |
| Type / Alive / Dead table, Own Units label, sort | Task 2 |
| Own only, skip structures, missing `is_structure` include | Task 1 |
| Morph collapse map (6 pairs) | Task 1 |
| Scan `0..throughIndex` each scrub | Task 1 + 2 |
| Independent of bot log | Task 2 |
| Cache-buster bump | Task 2 |
| Node/manual tests | Task 1 + 2 |
| README note | Task 3 |
| No extract/MP4/enemy/structures/precompute | respected (out of scope) |
