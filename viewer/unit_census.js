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
