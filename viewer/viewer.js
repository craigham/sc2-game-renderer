"use strict";

/* Interactive browser viewer — addition alongside the batch MP4 pipeline (see
 * docs/SPEC.md § Stage 2b). Reads the same .frames.jsonl.gz extract produces;
 * no server, no build step. Mirrors render_terrain.py / render_units.py /
 * render_hud.py's visual language in JS/canvas rather than reusing
 * Python-rendered images, so this file is the only place that logic is
 * duplicated. Optionally also reads the bot's raw stderr.log (same line
 * format bot_log.py parses) for the scrollable log panel — that panel shows
 * raw parsed lines only; the classified BotEvent whitelist/banners/ticker/
 * belief cross-check overlay is still MP4-only for now.
 */

const LOOPS_PER_SECOND = 22.4;
// Clickable radius is deliberately more generous than the drawn marker (a 5px dot
// with a 7px hit area is hard to land in a dense base cluster with dozens of
// overlapping units) — this is the click target, not the visual glyph.
const HIT_RADIUS_MIN = 10;

const MIN_ZOOM = 1; // 1 = fit the whole map inside the pane, the old fixed-size behavior
const MAX_ZOOM = 8;
const ZOOM_STEP_FACTOR = 1.2; // per wheel notch / +/- keypress

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
let liveExtractionUrl = null; // set while ?frames=<url> is still mid-extraction; null once finalized
let livePollTimer = null;
const LIVE_POLL_INTERVAL_MS = 2000;
let zoomLevel = MIN_ZOOM;

let logLines = []; // parsed stderr.log entries, file order == game-loop order
let logRows = []; // <tr> elements, index-aligned with logLines
let highlightedLogRow = null;

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
    const text = await decompressStreamToText(file.stream());
    parseFrameFile(text, file.name);
  } catch (err) {
    setStatus(`Failed to load ${file.name}: ${err.message}`);
    console.error(err);
  }
});

// A `?log=<url>` query param loads the bot log over fetch() the same way, for the
// same reason `?frames=<url>` exists: the log lives on the server that's serving
// this page, not on whatever machine is viewing it, so the file-input picker
// can't reach it. Unlike frames there's no live-extraction case to poll for —
// the log is a static artifact of a match that already finished.
const logUrl = new URLSearchParams(window.location.search).get("log");
if (logUrl) loadLogFromUrl(logUrl);

async function loadLogFromUrl(url) {
  setLogStatus(`Fetching ${url}...`);
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    parseLogFile(await response.text(), url);
  } catch (err) {
    setLogStatus(`Failed to load ${url}: ${err.message}`);
    console.error(err);
  }
}

// A `?frames=<url>` query param loads a frame file over fetch() instead of the
// file picker — for pages served over real http(s), not local file:// (which is
// what the file-input path above exists to work around; fetch() is fine here).
const framesUrl = new URLSearchParams(window.location.search).get("frames");
if (framesUrl) loadFromUrl(framesUrl);

async function loadFromUrl(url) {
  setStatus(`Fetching ${url}...`);
  try {
    const { text, stillExtracting } = await fetchFrameText(url);
    parseFrameFile(text, url);
    if (stillExtracting) {
      setStatus(`${header.map_name}, ${frames.length} frames, bot_player_id=${header.bot_player_id} (extracting…)`);
      liveExtractionUrl = url;
      scheduleLivePoll();
    }
  } catch (err) {
    setStatus(`Failed to load ${url}: ${err.message}`);
    console.error(err);
  }
}

async function fetchFrameText(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  // While a match is still being extracted, the server serves plain, uncompressed
  // ndjson (frames land on disk incrementally — see FrameFileWriter in
  // frame_file.py) instead of the finalized frames.jsonl.gz, so playback can
  // start well before the whole game has been stepped. Content-Type says which:
  // application/gzip once finalized, application/x-ndjson while still running.
  const contentType = response.headers.get("Content-Type") || "";
  const stillExtracting = !contentType.includes("gzip");
  const text = stillExtracting ? await response.text() : await decompressStreamToText(response.body);
  return { text, stillExtracting };
}

function scheduleLivePoll() {
  if (livePollTimer) clearTimeout(livePollTimer);
  livePollTimer = setTimeout(pollLiveExtraction, LIVE_POLL_INTERVAL_MS);
}

async function pollLiveExtraction() {
  if (!liveExtractionUrl) return;
  try {
    const { text, stillExtracting } = await fetchFrameText(liveExtractionUrl);
    extendFrames(text, stillExtracting);
    if (stillExtracting) {
      scheduleLivePoll();
    } else {
      liveExtractionUrl = null; // finalized — this was the last fetch needed
    }
  } catch (err) {
    // Transient (e.g. caught the server mid-write) — just retry on the next tick.
    console.error(err);
    scheduleLivePoll();
  }
}

// Extends the in-memory frame list from a fresh fetch without resetting playback
// position or the selected-unit panel the way a full parseFrameFile() load would —
// this runs every couple seconds while a match is still being watched live.
function extendFrames(text, stillExtracting) {
  const lines = text.split("\n").filter((l) => l.length > 0);
  const newFrames = lines.slice(1).map((l) => JSON.parse(l));
  const wasAtLiveEdge = currentIndex === frames.length - 1;
  const grew = newFrames.length > frames.length;
  frames = newFrames;

  const scrub = document.getElementById("scrubBar");
  scrub.max = frames.length - 1;

  const suffix = stillExtracting ? " (extracting…)" : "";
  setStatus(`${header.map_name}, ${frames.length} frames, bot_player_id=${header.bot_player_id}${suffix}`);

  if (grew && wasAtLiveEdge) {
    renderFrame(frames.length - 1); // follow the live edge if that's where we were
  } else {
    updateScrubUI(currentIndex, frames[currentIndex]); // keep the frame counter label fresh either way
  }
}

async function decompressStreamToText(stream) {
  // Browser-native gzip decompression — no library. Works on any
  // ReadableStream, whether it comes from a File (file-input path) or a
  // fetch() Response body (?frames=<url> path).
  return await new Response(stream.pipeThrough(new DecompressionStream("gzip"))).text();
}

// The frame file header carries no match id or player names — the only place a
// match identifier exists is the filename (file-picker) or URL (?frames=<url>,
// e.g. sc_bot_test_lab serving /frames/1234.frames.jsonl.gz). Pulled out into its
// own always-visible bar (see #matchTitle in viewer.css) rather than left buried
// in the loading-status line, which can be squeezed out of a short embed.
function deriveMatchLabel(source) {
  const base = source.split("/").pop().split("?")[0];
  return base.replace(/\.frames\.jsonl\.gz$/, "");
}

function setMatchTitle(source, mapName) {
  document.getElementById("matchTitle").textContent = `${deriveMatchLabel(source)} — ${mapName}`;
}

function parseFrameFile(text, filename) {
  const lines = text.split("\n").filter((l) => l.length > 0);
  header = JSON.parse(lines[0]);
  frames = lines.slice(1).map((l) => JSON.parse(l));

  setMatchTitle(filename, header.map_name);
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
  const pane = document.getElementById("mapPane");
  // Fit the whole map inside the pane at zoom 1 — the pane fills the browser window
  // (see viewer.css), so this replaces the old fixed 720px cap.
  const baseScale = Math.min(pane.clientWidth / extentWidth, pane.clientHeight / extentHeight);
  transform = { originX: x0, originY: y0, extentWidth, extentHeight, baseScale, scale: baseScale };
  resizeCanvasToZoom();
}

function resizeCanvasToZoom() {
  transform.scale = transform.baseScale * zoomLevel;
  const canvas = document.getElementById("mapCanvas");
  canvas.width = Math.round(transform.extentWidth * transform.scale);
  canvas.height = Math.round(transform.extentHeight * transform.scale);
}

// Zooms so the world point currently under (anchorClientX, anchorClientY) stays
// under it after the resize — otherwise every zoom would recenter on the
// pane's top-left corner instead of wherever the mouse/keyboard zoom was aimed.
function applyZoom(newZoomLevel, anchorClientX, anchorClientY) {
  const clamped = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, newZoomLevel));
  if (clamped === zoomLevel || !transform) return;

  const pane = document.getElementById("mapPane");
  const rect = pane.getBoundingClientRect();
  const oldWidth = transform.extentWidth * transform.scale;
  const oldHeight = transform.extentHeight * transform.scale;
  const fracX = (pane.scrollLeft + (anchorClientX - rect.left)) / oldWidth;
  const fracY = (pane.scrollTop + (anchorClientY - rect.top)) / oldHeight;

  zoomLevel = clamped;
  resizeCanvasToZoom();
  renderFrame(currentIndex);

  const newWidth = transform.extentWidth * transform.scale;
  const newHeight = transform.extentHeight * transform.scale;
  pane.scrollLeft = fracX * newWidth - (anchorClientX - rect.left);
  pane.scrollTop = fracY * newHeight - (anchorClientY - rect.top);
}

function zoomAtPaneCenter(factor) {
  const pane = document.getElementById("mapPane");
  const rect = pane.getBoundingClientRect();
  applyZoom(zoomLevel * factor, rect.left + rect.width / 2, rect.top + rect.height / 2);
}

document.getElementById("mapPane").addEventListener("wheel", (e) => {
  if (!transform) return;
  e.preventDefault();
  const factor = e.deltaY < 0 ? ZOOM_STEP_FACTOR : 1 / ZOOM_STEP_FACTOR;
  applyZoom(zoomLevel * factor, e.clientX, e.clientY);
}, { passive: false });

window.addEventListener("keydown", (e) => {
  if (!transform) return;
  if (e.key === "+" || e.key === "=") {
    e.preventDefault();
    zoomAtPaneCenter(ZOOM_STEP_FACTOR);
  } else if (e.key === "-" || e.key === "_") {
    e.preventDefault();
    zoomAtPaneCenter(1 / ZOOM_STEP_FACTOR);
  }
});

window.addEventListener("resize", () => {
  if (!header) return;
  const pane = document.getElementById("mapPane");
  transform.baseScale = Math.min(pane.clientWidth / transform.extentWidth, pane.clientHeight / transform.extentHeight);
  resizeCanvasToZoom();
  renderFrame(currentIndex);
});

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
  // Scrubbing/stepping/stopping call stopPlayback() before ever reaching
  // renderFrame(), so `playing` is already false for those — only the
  // playback timer's own tick leaves it true here. Skipping the scroll in
  // that case is deliberate: jumping the log panel to a new row 10x/sec
  // during playback would fight any manual scrolling the user is doing.
  if (!playing) updateLogPanelForFrame(frame);
}

function drawFilledCircle(ctx, u, r, color, category) {
  const [px, py] = worldToPixel(u.x, u.y);
  ctx.beginPath();
  ctx.arc(px, py, r, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  hitTargets.push({ px, py, r: Math.max(r + 2, HIT_RADIUS_MIN), category, unit: u });
}

function drawHollowCircle(ctx, u, r, color, category) {
  const [px, py] = worldToPixel(u.x, u.y);
  ctx.beginPath();
  ctx.arc(px, py, r, 0, Math.PI * 2);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.stroke();
  hitTargets.push({ px, py, r: Math.max(r + 2, HIT_RADIUS_MIN), category, unit: u });
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
  hitTargets.push({ px, py, r: Math.max(r + 2, HIT_RADIUS_MIN), category, unit: u, ageSeconds });
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

// ---------- bot log panel (raw stderr.log lines, joined to the paused frame) ----------
// Mirrors bot_log.py's _LOG_LINE regex exactly — same sharpy log_manager prefix.
const LOG_LINE_RE =
  /^(\S+)\s+(\d+)\s+(\d+)ms\s+(-?\d+)M\s+(-?\d+)G\s+(\d+)\/\s*(\d+)U\s+(INFO|WARNING|ERROR|DEBUG)\s+([\w.]+):(\d+)\s(.*)$/;

document.getElementById("logFileInput").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  setLogStatus(`Reading ${file.name}...`);
  try {
    const text = await file.text();
    parseLogFile(text, file.name);
  } catch (err) {
    setLogStatus(`Failed to load ${file.name}: ${err.message}`);
    console.error(err);
  }
});

function parseLogFile(text, filename) {
  logLines = [];
  let total = 0;
  for (const raw of text.split("\n")) {
    if (!raw.trim()) continue;
    total++;
    const m = LOG_LINE_RE.exec(raw);
    if (!m) continue; // container preamble / non-sharpy lines — see bot_log.py's parse_log_lines
    logLines.push({
      clock: m[1],
      game_loop: parseInt(m[2], 10),
      level: m[8],
      logger: `${m[9]}:${m[10]}`,
      message: m[11],
    });
  }
  setLogStatus(`${filename}: ${logLines.length}/${total} lines parsed`);
  buildLogTable();
  if (frames.length > 0) updateLogPanelForFrame(frames[currentIndex]);
}

function setLogStatus(text) {
  document.getElementById("logStatus").textContent = text;
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function buildLogTable() {
  const tbody = document.getElementById("logTableBody");
  tbody.innerHTML = "";
  logRows = new Array(logLines.length);
  highlightedLogRow = null;
  const frag = document.createDocumentFragment();
  logLines.forEach((line, i) => {
    const tr = document.createElement("tr");
    tr.className = `loglevel-${line.level}`;
    tr.innerHTML = `<td>${line.game_loop}</td><td>${line.clock}</td><td>${line.level}</td>` +
      `<td>${line.logger}</td><td>${escapeHtml(line.message)}</td>`;
    logRows[i] = tr;
    frag.appendChild(tr);
  });
  tbody.appendChild(frag);
}

// bisect_left on game_loop, then pick whichever neighbor is closer — mirrors
// join_events_to_frames' nearest-frame join in bot_log.py, but for scrolling
// the panel there's no reason to drop out-of-tolerance entries the way that
// join does; any nearest row is still useful context.
function findNearestLogIndex(gameLoop) {
  if (logLines.length === 0) return -1;
  let lo = 0;
  let hi = logLines.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (logLines[mid].game_loop < gameLoop) lo = mid + 1;
    else hi = mid;
  }
  if (lo >= logLines.length) return logLines.length - 1;
  if (lo > 0 && logLines[lo].game_loop - gameLoop > gameLoop - logLines[lo - 1].game_loop) return lo - 1;
  return lo;
}

function updateLogPanelForFrame(frame) {
  if (logRows.length === 0) return;
  const idx = findNearestLogIndex(frame.game_loop);
  if (idx < 0) return;
  if (highlightedLogRow) highlightedLogRow.classList.remove("current");
  const row = logRows[idx];
  row.classList.add("current");
  row.scrollIntoView({ block: "center" });
  highlightedLogRow = row;
}

// ---------- log panel resize (drag the handle at its top edge) ----------
const logPanel = document.getElementById("logPanel");
const logResizeHandle = document.getElementById("logResizeHandle");
let resizingLogPanel = false;

logResizeHandle.addEventListener("mousedown", (e) => {
  resizingLogPanel = true;
  e.preventDefault();
});
window.addEventListener("mousemove", (e) => {
  if (!resizingLogPanel) return;
  const rect = logPanel.getBoundingClientRect();
  const newHeight = rect.bottom - e.clientY; // handle sits at the panel's top edge
  logPanel.style.height = `${Math.min(window.innerHeight * 0.7, Math.max(80, newHeight))}px`;
});
window.addEventListener("mouseup", () => {
  resizingLogPanel = false;
});
