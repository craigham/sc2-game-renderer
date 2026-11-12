import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const src = fs.readFileSync(path.join(root, "viewer/army_objective.js"), "utf8");
const context = {};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(src, context);

const { classifyArmyEvents, mainArmyAt, OBJECTIVE_RING_RADIUS } = context;

function plain(view) {
  if (!view || view.status !== "ready") return { status: view ? String(view.status) : null };
  const target = view.target
    ? [Number(view.target[0]), Number(view.target[1])]
    : null;
  return {
    status: "ready",
    objective: String(view.objective),
    action: view.action == null ? null : String(view.action),
    eta: view.eta == null ? null : String(view.eta),
    sim: view.sim == null ? null : String(view.sim).replaceAll("\u00A0", " "),
    target,
  };
}

const pathLine = {
  game_loop: 1000,
  message:
    "MOVE_EVT army_factor=1.0 event='path_route_resolved' path_len=3 " +
    "path_sample=[(0, 0), (40, 0), (80, 0)] squad_id='main_army:99' start=(0, 0) target=(80, 0)",
};
const bioLine = {
  game_loop: 1008,
  message:
    "MOVE_EVT event='bio_screen_decision_snapshot' movement_pattern='hold_position' " +
    "move_type='Assault' objective_id='zone:4' squad_id='main_army:99'",
};
const simLine = {
  game_loop: 900,
  message:
    "MOVE_EVT adjusted_sim='VICTORY_CLOSE' enemy_unit_count=8 event='combat_sim_snapshot' " +
    "our_type_counts={{'MARINE': 12}} our_unit_count=12 remaining_health_pct=0.62 we_win=True",
};
const reinforcement = {
  game_loop: 1004,
  message:
    "MOVE_EVT event='path_route_resolved' squad_id='reinforcement:5' target=(1, 2) path_sample=[(1, 2), (3, 4)]",
};

const classified = classifyArmyEvents([
  { game_loop: 10, message: "Pulling worker back to mining" },
  simLine,
  pathLine,
  reinforcement,
  bioLine,
  {
    game_loop: 2000,
    message:
      "MOVE_EVT event='path_route_resolved' squad_id='main_army:99' target=(10, 10) path_sample=[(0, 0), (10, 10)]",
  },
]);

assert.equal(Number(OBJECTIVE_RING_RADIUS), 4);
assert.equal(Boolean(classified.sawMoveEvt), true);

// Before the route exists: sim alone is not an objective.
assert.deepEqual(plain(mainArmyAt(classified, 900)), { status: "no-objective" });

// Path gives the ring and an estimated ETA. 80 / 2.25 = 35.55 → ~36s.
// Objective id has not arrived yet, so the action type is the label... there is
// no action yet either, so the objective line is the target point.
assert.deepEqual(plain(mainArmyAt(classified, 1000)), {
  status: "ready",
  objective: "(80, 0)",
  action: null,
  eta: "~36s",
  sim: "Victory close · win · 12 vs 8 · 62% hp",
  target: [80, 0],
});

// Reinforcement path does not move the main-army ring. Bio snapshot names the
// objective and wins the action over the Assault move type.
assert.deepEqual(plain(mainArmyAt(classified, 1008)), {
  status: "ready",
  objective: "zone:4",
  action: "hold position (hold_position)",
  eta: "~36s",
  sim: "Victory close · win · 12 vs 8 · 62% hp",
  target: [80, 0],
});

// A later main-army route replaces the point. Scrubbing back does not show it.
assert.deepEqual(plain(mainArmyAt(classified, 2000)).target, [10, 10]);
assert.deepEqual(plain(mainArmyAt(classified, 1008)).target, [80, 0]);

// No bio snapshot: move type is the action, and a unit-tag target is not a ring.
{
  const onlyOrder = classifyArmyEvents([
    {
      game_loop: 50,
      message:
        "MOVE_EVT event='unit_directive' move_type='Siege' objective_id='proxy:12' " +
        "squad_id='main_army:99' target=4387504129",
    },
  ]);
  assert.deepEqual(plain(mainArmyAt(onlyOrder, 50)), {
    status: "ready",
    objective: "proxy:12",
    action: "siege (Siege)",
    eta: null,
    sim: null,
    target: null,
  });
}

// Assault with no movement pattern reads as march. Straight-line ETA when the
// route sample is absent: 30 / 2.25 = 13.33 → ~13s.
{
  const march = classifyArmyEvents([
    {
      game_loop: 80,
      message:
        "MOVE_EVT event='unit_directive' move_type='Assault' objective_id=None squad_id='main_army:1'",
    },
    {
      game_loop: 80,
      message:
        "MOVE_EVT event='path_route_resolved' squad_id='main_army:1' start=(0, 0) target=(30, 0)",
    },
  ]);
  const view = plain(mainArmyAt(march, 80));
  assert.equal(view.objective, "march");
  assert.equal(view.action, "march (Assault)");
  assert.equal(view.eta, "~13s");
  assert.deepEqual(view.target, [30, 0]);
}

// A loss, and a log with no movement diagnostics.
{
  const loss = classifyArmyEvents([
    {
      game_loop: 10,
      message:
        "MOVE_EVT adjusted_sim='LOSS_DECISIVE' event='combat_sim_snapshot' we_win=False " +
        "our_unit_count=4 enemy_unit_count=11 remaining_health_pct=0.2",
    },
    {
      game_loop: 12,
      message: "MOVE_EVT event='bio_screen_decision_snapshot' movement_pattern='retreat' objective_id='zone:1' squad_id='main_army:1'",
    },
  ]);
  assert.equal(plain(mainArmyAt(loss, 12)).sim, "Loss decisive · loss · 4 vs 11 · 20% hp");
  assert.equal(plain(mainArmyAt(loss, 12)).action, "retreat (retreat)");
}

{
  const quiet = classifyArmyEvents([{ game_loop: 1, message: "[GameAnalyzer] Income advantage is now Even" }]);
  assert.equal(Boolean(quiet.sawMoveEvt), false);
  assert.equal(plain(mainArmyAt(quiet, 1)).status, "no-diagnostics");
  assert.equal(plain(mainArmyAt(null, 1)).status, "no-log");
}
