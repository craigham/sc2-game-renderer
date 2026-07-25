"use strict";

/* Interactive browser viewer — addition alongside the batch MP4 pipeline (see
 * docs/SPEC.md § Stage 2b). Reads the same .frames.jsonl.gz extract produces;
 * no server, no build step. Deliberately does NOT read stderr.log — the
 * bot-state overlay (events/banners/ticker/belief cross-check) is MP4-only for
 * now. Mirrors render_terrain.py / render_units.py / render_hud.py's visual
 * language in JS/canvas rather than reusing Python-rendered images, so this
 * file is the only place that logic is duplicated.
 */

const LOOPS_PER_SECOND = 22.4;
const MAX_DISPLAY_SIZE = 720; // map pane fits within this many px on its longer side

const COLORS = {
  unpathable: [18, 18, 34],
  unbuildableTint: [60, 70, 110],
  own: "rgb(70,150,235)",
  enemy: "rgb(230,70,70)",
};

// ---------- state ----------
let header = null;
let frames = []; // parsed frame records, in game-loop order
let currentIndex = 0;
let playing = false;
let playTimer = null;
let transform = null; // world<->pixel, see computeLayout()
let terrainCanvas = null; // offscreen, rendered once per loaded file
let hitTargets = []; // rebuilt every renderFrame() call, for click hit-testing
let selectedTag = null; // persists across frames so the panel follows a unit

// ---------- name lookups (ABILITY_NAMES / UNIT_TYPE_NAMES from data/*.js) ----------
function abilityName(id) {
  return ABILITY_NAMES[String(id)] || `Ability ${id}`;
}
function unitTypeName(id) {
  return UNIT_TYPE_NAMES[String(id)] || `Type ${id}`;
}

// ---------- loading the frame file ----------
document.getElementById("fileInput").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  setStatus(`Decompressing ${file.name}...`);
  try {
    const text = await decompressToText(file);
    parseFrameFile(text, file.name);
  } catch (err) {
    setStatus(`Failed to load ${file.name}: ${err.message}`);
    console.error(err);
  }
});

async function decompressToText(file) {
  // Browser-native gzip decompression — no library, works on a File directly
  // (unlike fetch(), which most browsers block for local file:// pages, this is
  // exactly why the frame file is loaded via <input type="file">, not fetch()).
  const stream = file.stream().pipeThrough(new DecompressionStream("gzip"));
  return await new Response(stream).text();
}

function parseFrameFile(text, filename) {
  const lines = text.split("\n").filter((l) => l.length > 0);
  header = JSON.parse(lines[0]);
  frames = lines.slice(1).map((l) => JSON.parse(l));

  setStatus(`${filename}: ${header.map_name}, ${frames.length} frames, bot_player_id=${header.bot_player_id}`);
  selectedTag = null;
  document.getElementById("unitDetail").innerHTML = "<em>Click a unit to inspect it</em>";

  computeLayout();
  renderTerrainBackground();

  const scrub = document.getElementById("scrubBar");
  scrub.min = 0;
  scrub.max = frames.length - 1;
  scrub.value = 0;

  renderFrame(0);
}

function setStatus(text) {
  document.getElementById("loadStatus").textContent = text;
}

// ---------- coordinate transform (mirrors coords.py's WorldToPixel exactly) ----------
function computeLayout() {
  const [x0, y0, x1, y1] = header.playable_area;
  const extentWidth = x1 - x0;
  const extentHeight = y1 - y0;
  const scale = MAX_DISPLAY_SIZE / Math.max(extentWidth, extentHeight);
  transform = { originX: x0, originY: y0, extentWidth, extentHeight, scale };

  const canvas = document.getElementById("mapCanvas");
  canvas.width = Math.round(extentWidth * scale);
  canvas.height = Math.round(extentHeight * scale);
}

function worldToPixel(x, y) {
  return [
    (x - transform.originX) * transform.scale,
    (transform.originY + transform.extentHeight - y) * transform.scale,
  ];
}

// ---------- terrain decode + draw (mirrors render_terrain.py) ----------
function base64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function unpackBits(bytes) {
  // MSB-first per byte — matches numpy.unpackbits's default bitorder ('big'),
  // which is what frame_file.py's TerrainGrid.to_numpy() relies on.
  const out = new Uint8Array(bytes.length * 8);
  for (let i = 0; i < bytes.length; i++) {
    const byte = bytes[i];
    for (let b = 0; b < 8; b++) out[i * 8 + b] = (byte >> (7 - b)) & 1;
  }
  return out;
}

function decodeGrid(grid) {
  const bytes = base64ToBytes(grid.data_base64);
  const data = grid.bits_per_pixel === 1 ? unpackBits(bytes) : bytes;
  return { width: grid.width, data }; // row-major, row index = world y
}

function renderTerrainBackground() {
  const pathing = decodeGrid(header.pathing_grid);
  const placement = decodeGrid(header.placement_grid);
  const heightGrid = decodeGrid(header.terrain_height);

  const [x0, y0, x1, y1] = header.playable_area;
  const w = x1 - x0;
  const h = y1 - y0;

  let hMin = 255;
  let hMax = 0;
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const v = heightGrid.data[y * heightGrid.width + x];
      if (v < hMin) hMin = v;
      if (v > hMax) hMax = v;
    }
  }
  const span = Math.max(hMax - hMin, 1);

  const off = document.createElement("canvas");
  off.width = w;
  off.height = h;
  const octx = off.getContext("2d");
  const img = octx.createImageData(w, h);

  for (let row = 0; row < h; row++) {
    const worldY = y0 + row;
    const outRow = h - 1 - row; // raw row 0 = y=0 (south); output row 0 must be north
    for (let col = 0; col < w; col++) {
      const worldX = x0 + col;
      const hVal = heightGrid.data[worldY * heightGrid.width + worldX];
      let r = Math.round(((hVal - hMin) / span) * 150 + 60);
      let g = r;
      let b = r;

      const isPathable = pathing.data[worldY * pathing.width + worldX] !== 0;
      const isPlaceable = placement.data[worldY * placement.width + worldX] !== 0;

      if (!isPathable) {
        [r, g, b] = COLORS.unpathable;
      } else if (!isPlaceable) {
        r = Math.round(r * 0.4 + COLORS.unbuildableTint[0] * 0.6);
        g = Math.round(g * 0.4 + COLORS.unbuildableTint[1] * 0.6);
        b = Math.round(b * 0.4 + COLORS.unbuildableTint[2] * 0.6);
      }

      const outIdx = (outRow * w + col) * 4;
      img.data[outIdx] = r;
      img.data[outIdx + 1] = g;
      img.data[outIdx + 2] = b;
      img.data[outIdx + 3] = 255;
    }
  }
  octx.putImageData(img, 0, 0);
  terrainCanvas = off;
}

// ---------- per-frame render (mirrors render_units.py's marker language) ----------
function renderFrame(index) {
  currentIndex = index;
  const frame = frames[index];
  const canvas = document.getElementById("mapCanvas");
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(terrainCanvas, 0, 0, canvas.width, canvas.height);

  hitTargets = [];
  const r = Math.max(2, transform.scale * 0.9);

  for (const u of frame.own_units) drawFilledCircle(ctx, u, r, COLORS.own, "own");
  for (const u of frame.enemy_visible) drawFilledCircle(ctx, u, r, COLORS.enemy, "enemy_visible");
  for (const u of frame.enemy_snapshot) drawHollowCircle(ctx, u, r, COLORS.enemy, "enemy_snapshot");
  for (const rem of frame.remembered_enemies) {
    const age = (frame.game_loop - rem.last_seen_loop) / LOOPS_PER_SECOND;
    drawDashedCircle(ctx, rem.unit, r, COLORS.enemy, "remembered", age);
  }

  updateHud(frame);
  updateScrubUI(index, frame);
  updateSelectedUnitPanel();
}

function drawFilledCircle(ctx, u, r, color, category) {
  const [px, py] = worldToPixel(u.x, u.y);
  ctx.beginPath();
  ctx.arc(px, py, r, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  hitTargets.push({ px, py, r: r + 2, category, unit: u });
}

function drawHollowCircle(ctx, u, r, color, category) {
  const [px, py] = worldToPixel(u.x, u.y);
  ctx.beginPath();
  ctx.arc(px, py, r, 0, Math.PI * 2);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.stroke();
  hitTargets.push({ px, py, r: r + 2, category, unit: u });
}

function drawDashedCircle(ctx, u, r, color, category, ageSeconds) {
  const [px, py] = worldToPixel(u.x, u.y);
  ctx.beginPath();
  ctx.setLineDash([4, 3]);
  ctx.arc(px, py, r, 0, Math.PI * 2);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = color;
  ctx.font = "10px monospace";
  ctx.fillText(`${Math.round(ageSeconds)}s ago`, px + r + 2, py - r);
  hitTargets.push({ px, py, r: r + 2, category, unit: u, ageSeconds });
}

// ---------- HUD (mirrors render_hud.py's content; plain DOM text, no canvas needed
// for a sidebar that isn't being composited into a video frame) ----------
function formatClock(gameLoop) {
  const totalSeconds = Math.floor(gameLoop / LOOPS_PER_SECOND);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function updateHud(frame) {
  const supplyClass = frame.supply_blocked ? "warning" : "";
  const idleClass = frame.idle_worker_count > 0 ? "warning" : "";
  document.getElementById("hud").innerHTML = `
    <div class="clock">${formatClock(frame.game_loop)}</div>
    <div class="section-label">Resources</div>
    <div>Minerals ${frame.minerals} (${frame.minerals_rate.toFixed(0)}/min)</div>
    <div>Vespene ${frame.vespene} (${frame.vespene_rate.toFixed(0)}/min)</div>
    <div class="section-label">Supply</div>
    <div class="${supplyClass}">${frame.supply_used}/${frame.supply_cap}${frame.supply_blocked ? " BLOCKED" : ""}</div>
    <div class="section-label">Workers</div>
    <div class="${idleClass}">${frame.supply_workers} (idle: ${frame.idle_worker_count})</div>
    <div class="section-label">Army value</div>
    <div>${frame.army_value_minerals}m / ${frame.army_value_vespene}g</div>
  `;
}

function updateScrubUI(index, frame) {
  document.getElementById("scrubBar").value = index;
  document.getElementById("frameLabel").textContent =
    `frame ${index + 1}/${frames.length}  loop ${frame.game_loop}  ${formatClock(frame.game_loop)}`;
}

// ---------- click-to-inspect ----------
document.getElementById("mapCanvas").addEventListener("click", (e) => {
  const rect = e.target.getBoundingClientRect();
  const clickX = e.clientX - rect.left;
  const clickY = e.clientY - rect.top;

  let best = null;
  let bestDist = Infinity;
  for (const t of hitTargets) {
    const d = Math.hypot(t.px - clickX, t.py - clickY);
    if (d <= t.r && d < bestDist) {
      best = t;
      bestDist = d;
    }
  }

  if (best) {
    selectedTag = best.unit.tag;
    showUnitDetail(best);
  } else {
    selectedTag = null;
    document.getElementById("unitDetail").innerHTML = "<em>Click a unit to inspect it</em>";
  }
});

function updateSelectedUnitPanel() {
  if (selectedTag == null) return;
  const match = hitTargets.find((t) => t.unit.tag === selectedTag);
  if (match) {
    showUnitDetail(match);
  } else {
    document.getElementById("unitDetail").innerHTML =
      `<em>Unit ${selectedTag} not present in this frame</em>`;
  }
}

const CATEGORY_LABELS = {
  own: "Own unit",
  enemy_visible: "Enemy (visible)",
  enemy_snapshot: "Enemy structure (remembered by SC2 through fog)",
};

function describeOrder(o) {
  const name = abilityName(o.ability_id);
  let targetStr = "";
  if (o.target_unit_tag != null) targetStr = ` &rarr; unit ${o.target_unit_tag}`;
  else if (o.target_pos != null) targetStr = ` &rarr; (${o.target_pos[0].toFixed(1)}, ${o.target_pos[1].toFixed(1)})`;
  const progressStr = o.progress > 0 ? ` (${Math.round(o.progress * 100)}%)` : "";
  return `${name}${targetStr}${progressStr}`;
}

function showUnitDetail(target) {
  const u = target.unit;
  const isOwn = target.category === "own";
  const categoryLabel =
    target.category === "remembered"
      ? `Enemy &mdash; last seen ${Math.round(target.ageSeconds)}s ago`
      : CATEGORY_LABELS[target.category];

  // SC2 never reports an order for a unit you don't own (see frame.py) — showing
  // "idle" for an enemy would claim knowledge fog doesn't give us. Own units:
  // "idle" is a real, meaningful fact (no order queued).
  let ordersSection;
  if (!isOwn) {
    ordersSection = `<div class="section-label">Current order(s)</div><div><em>not visible through fog</em></div>`;
  } else {
    const ordersHtml = u.orders.length > 0 ? u.orders.map(describeOrder).join("<br>") : "<em>idle</em>";
    ordersSection = `<div class="section-label">Current order(s)</div><div>${ordersHtml}</div>`;
  }

  document.getElementById("unitDetail").innerHTML = `
    <div class="section-label">${categoryLabel}</div>
    <div><strong>${unitTypeName(u.unit_type)}</strong> (tag ${u.tag})</div>
    <div>Position: (${u.x.toFixed(1)}, ${u.y.toFixed(1)})</div>
    <div>Health: ${u.health.toFixed(0)} / ${u.health_max.toFixed(0)}</div>
    ${u.shield_max > 0 ? `<div>Shield: ${u.shield.toFixed(0)} / ${u.shield_max.toFixed(0)}</div>` : ""}
    ${u.energy_max > 0 ? `<div>Energy: ${u.energy.toFixed(0)} / ${u.energy_max.toFixed(0)}</div>` : ""}
    ${ordersSection}
  `;
}

// ---------- playback ----------
document.getElementById("playBtn").addEventListener("click", () => {
  if (playing) stopPlayback();
  else startPlayback();
});
document.getElementById("stepFwdBtn").addEventListener("click", () => {
  stopPlayback();
  if (currentIndex < frames.length - 1) renderFrame(currentIndex + 1);
});
document.getElementById("stepBackBtn").addEventListener("click", () => {
  stopPlayback();
  if (currentIndex > 0) renderFrame(currentIndex - 1);
});
document.getElementById("scrubBar").addEventListener("input", (e) => {
  stopPlayback();
  renderFrame(parseInt(e.target.value, 10));
});

function startPlayback() {
  if (frames.length === 0) return;
  playing = true;
  document.getElementById("playBtn").textContent = "Pause";
  playTimer = setInterval(() => {
    if (currentIndex >= frames.length - 1) {
      stopPlayback();
      return;
    }
    renderFrame(currentIndex + 1);
  }, 100); // 10 sampled-frames/sec — a scrubbing/review speed, not tied to any MP4 fps
}

function stopPlayback() {
  playing = false;
  document.getElementById("playBtn").textContent = "Play";
  if (playTimer) clearInterval(playTimer);
  playTimer = null;
}
