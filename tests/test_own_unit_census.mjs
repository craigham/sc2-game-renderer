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

// Values / arrays from the vm context are different-realm objects; copy into
// this realm before assert.deepEqual (Node treats cross-realm arrays as unequal).
function plainRows(rows) {
  const out = [];
  for (const r of rows) {
    out.push([String(r.name), Number(r.alive), Number(r.dead)]);
  }
  return out;
}

assert.equal(Number(canonicalUnitType(32)), 33); // sieged → tank
assert.equal(Number(canonicalUnitType(48)), 48); // marine identity

// Alive only at frame 0 (structures excluded; tied alive → name ascending)
{
  const frames = [frame([u(1, 45, false), u(2, 48, false), u(3, 18, true)])];
  const rows = plainRows(computeOwnUnitCensus(frames, 0));
  assert.deepEqual(rows, [
    ["MARINE", 1, 0],
    ["SCV", 1, 0],
  ]);
}

// Death: marine tag disappears
{
  const frames = [
    frame([u(1, 45, false), u(2, 48, false)]),
    frame([u(1, 45, false)]),
  ];
  const rows = plainRows(computeOwnUnitCensus(frames, 1));
  const byName = Object.fromEntries(rows.map(([name, alive, dead]) => [name, { alive, dead }]));
  assert.equal(byName.SCV.alive, 1);
  assert.equal(byName.SCV.dead, 0);
  assert.equal(byName.MARINE.alive, 0);
  assert.equal(byName.MARINE.dead, 1);
}

// Morph ≠ death: same tag, tank then sieged
{
  const frames = [
    frame([u(9, 33, false)]),
    frame([u(9, 32, false)]),
  ];
  const rows = plainRows(computeOwnUnitCensus(frames, 1));
  assert.equal(rows.length, 1);
  assert.equal(rows[0][0], "SIEGETANK");
  assert.equal(rows[0][1], 1);
  assert.equal(rows[0][2], 0);
}

// Missing is_structure → include
{
  const frames = [frame([u(1, 48)])];
  const rows = plainRows(computeOwnUnitCensus(frames, 0));
  assert.equal(rows[0][0], "MARINE");
  assert.equal(rows[0][1], 1);
}

console.log("ok");
