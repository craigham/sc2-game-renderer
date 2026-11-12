// Main-army objective panel. Pure — no DOM.
//
// Stitches three MOVE_EVT lines the bot already writes when movement diagnostics
// are on:
//   path_route_resolved (squad_id main_army:*) — objective point and route
//   bio_screen_decision_snapshot / unit_directive — objective id and action
//   combat_sim_snapshot — last combat-sim tier
// ETA is path length / tank speed. The log does not record an ETA.

var ARMY_MARCH_SPEED = 2.25; // siege-tank speed; a cohesive army is tank-limited
var OBJECTIVE_RING_RADIUS = 4;

var PATTERN_LABELS = {
  hold_position: "hold position",
  aggressive_forward: "march",
  stutter_step_forward: "march",
  kiting: "kite",
  retreat: "retreat",
  clear_frontline: "clear frontline",
};

var MOVE_TYPE_LABELS = {
  Assault: "march",
  Push: "march",
  SearchAndDestroy: "march",
  Kamikaze: "march",
  Siege: "siege",
  DefensiveRetreat: "retreat",
  PanicRetreat: "retreat",
  Harass: "harass",
  ReGroup: "regroup",
};

function isMainArmySquad(squadId) {
  return squadId === "main_army" || (typeof squadId === "string" && squadId.startsWith("main_army:"));
}

function skipSpace(s, i) {
  while (i < s.length && s[i] === " ") i++;
  return i;
}

function isIdentChar(c) {
  return !!c && /[A-Za-z0-9_]/.test(c);
}

// Python repr, the form emit_move_event writes (key=value!r). Enough for the
// scalars, points, and routes these events carry. Dict values are skipped by
// the caller; this still accepts one so a requested field can be a dict.
function parseReprAt(s, i) {
  i = skipSpace(s, i);
  const c = s[i];
  if (c === "'" || c === '"') return parsePyString(s, i);
  if (c === "(" || c === "[") return parsePySeq(s, i);
  if (c === "{") return parsePyBraces(s, i);
  if (s.startsWith("True", i) && !isIdentChar(s[i + 4])) return { value: true, next: i + 4 };
  if (s.startsWith("False", i) && !isIdentChar(s[i + 5])) return { value: false, next: i + 5 };
  if (s.startsWith("None", i) && !isIdentChar(s[i + 4])) return { value: null, next: i + 4 };
  const num = /^-?(?:\d+\.\d+|\d+)(?:[eE][+-]?\d+)?/.exec(s.slice(i));
  if (num) return { value: Number(num[0]), next: i + num[0].length };
  const ident = /^[A-Za-z_][A-Za-z0-9_]*/.exec(s.slice(i));
  if (ident) {
    let j = i + ident[0].length;
    if (s[j] === "(") {
      const inner = parsePySeq(s, j);
      const value = inner.value.length === 1 ? inner.value[0] : inner.value;
      return { value, next: inner.next };
    }
    return { value: ident[0], next: j };
  }
  throw new Error("unparsed repr");
}

function parsePyString(s, i) {
  const q = s[i];
  let j = i + 1;
  let out = "";
  while (j < s.length) {
    const c = s[j];
    if (c === "\\") {
      const n = s[j + 1];
      if (n === "n") out += "\n";
      else if (n === "t") out += "\t";
      else if (n === "r") out += "\r";
      else out += n ?? "";
      j += 2;
      continue;
    }
    if (c === q) return { value: out, next: j + 1 };
    out += c;
    j++;
  }
  throw new Error("unterminated string");
}

function parsePySeq(s, i) {
  const close = s[i] === "(" ? ")" : "]";
  let j = i + 1;
  const values = [];
  while (j < s.length) {
    j = skipSpace(s, j);
    if (s[j] === close) return { value: values, next: j + 1 };
    const parsed = parseReprAt(s, j);
    values.push(parsed.value);
    j = skipSpace(s, parsed.next);
    if (s[j] === ",") {
      j++;
      continue;
    }
    if (s[j] === close) return { value: values, next: j + 1 };
    throw new Error("bad sequence");
  }
  throw new Error("unterminated sequence");
}

function parsePyBraces(s, i) {
  // log_format doubles braces before loguru, and a value passed as "{}" keeps
  // them doubled in the file. Accept either {{...}} or {...} and discard it:
  // none of the fields this panel reads are dicts.
  let depth = 0;
  let j = i;
  while (j < s.length) {
    const c = s[j];
    if (c === "{") depth++;
    else if (c === "}") {
      depth--;
      if (depth === 0) return { value: null, next: j + 1 };
    } else if (c === "'" || c === '"') {
      j = parsePyString(s, j).next;
      continue;
    }
    j++;
  }
  throw new Error("unterminated brace value");
}

function readField(message, key) {
  const token = key + "=";
  let from = 0;
  while (from < message.length) {
    const at = message.indexOf(token, from);
    if (at < 0) return undefined;
    if (at === 0 || message[at - 1] === " ") {
      try {
        return parseReprAt(message, at + token.length).value;
      } catch {
        return undefined;
      }
    }
    from = at + 1;
  }
  return undefined;
}

function asPoint(value) {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const x = Number(value[0]);
  const y = Number(value[1]);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  return [x, y];
}

function asPath(value) {
  if (!Array.isArray(value)) return null;
  const points = [];
  for (const item of value) {
    const p = asPoint(item);
    if (!p) return null;
    points.push(p);
  }
  return points;
}

function asString(value) {
  return typeof value === "string" && value ? value : null;
}

function parseMoveEvt(message) {
  if (typeof message !== "string" || !message.startsWith("MOVE_EVT ")) return null;
  const event = asString(readField(message, "event"));
  if (!event) return null;
  return {
    event,
    squadId: readField(message, "squad_id") ?? null,
    target: asPoint(readField(message, "target")),
    pathSample: asPath(readField(message, "path_sample")),
    start: asPoint(readField(message, "start")),
    objectiveId: asString(readField(message, "objective_id")),
    movementPattern: asString(readField(message, "movement_pattern")),
    moveType: asString(readField(message, "move_type")),
    adjustedSim: asString(readField(message, "adjusted_sim")),
    weWin: readField(message, "we_win"),
    ourUnitCount: readField(message, "our_unit_count"),
    enemyUnitCount: readField(message, "enemy_unit_count"),
    remainingHealthPct: readField(message, "remaining_health_pct"),
  };
}

function keepArmyEvent(parsed) {
  if (parsed.event === "combat_sim_snapshot") return true;
  if (!isMainArmySquad(parsed.squadId)) return false;
  return (
    parsed.event === "path_route_resolved" ||
    parsed.event === "bio_screen_decision_snapshot" ||
    parsed.event === "unit_directive"
  );
}

function classifyArmyEvents(lines) {
  const events = [];
  let sawMoveEvt = false;
  for (const line of lines) {
    const message = line.message;
    if (typeof message !== "string" || !message.startsWith("MOVE_EVT ")) continue;
    sawMoveEvt = true;
    const parsed = parseMoveEvt(message);
    if (!parsed || !keepArmyEvent(parsed)) continue;
    events.push({ gameLoop: line.game_loop, ...parsed });
  }
  return { events, sawMoveEvt };
}

function armyStateAsOf(events, gameLoop) {
  let path = null;
  let objectiveId = null;
  let movementPattern = null;
  let moveType = null;
  let sim = null;
  for (const e of events) {
    if (e.gameLoop > gameLoop) break;
    if (e.event === "path_route_resolved" && e.target) {
      path = e;
    } else if (e.event === "bio_screen_decision_snapshot" || e.event === "unit_directive") {
      if (e.objectiveId) objectiveId = e.objectiveId;
      if (e.event === "bio_screen_decision_snapshot" && e.movementPattern) {
        movementPattern = e.movementPattern;
      }
      if (e.moveType) moveType = e.moveType;
    } else if (e.event === "combat_sim_snapshot" && e.adjustedSim) {
      sim = e;
    }
  }
  return {
    hasObjective: path != null || objectiveId != null,
    objectiveId,
    movementPattern,
    moveType,
    path,
    sim,
  };
}

function formatArmyAction(movementPattern, moveType) {
  if (movementPattern) {
    return {
      label: PATTERN_LABELS[movementPattern] || movementPattern.replaceAll("_", " "),
      raw: movementPattern,
    };
  }
  if (moveType) {
    return { label: MOVE_TYPE_LABELS[moveType] || moveType, raw: moveType };
  }
  return null;
}

function polylineLength(points) {
  if (!points || points.length < 2) return null;
  let distance = 0;
  for (let i = 1; i < points.length; i++) {
    distance += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
  }
  return distance;
}

function pathDistance(path) {
  if (!path) return null;
  const along = polylineLength(path.pathSample);
  if (along != null) return along;
  if (path.start && path.target) {
    return Math.hypot(path.target[0] - path.start[0], path.target[1] - path.start[1]);
  }
  return null;
}

function formatEta(path) {
  const distance = pathDistance(path);
  if (distance == null) return null;
  return `~${Math.round(distance / ARMY_MARCH_SPEED)}s`;
}

function formatTier(name) {
  const words = name.toLowerCase().split("_");
  if (!words[0]) return name;
  words[0] = words[0][0].toUpperCase() + words[0].slice(1);
  return words.join(" ");
}

function formatSim(sim) {
  if (!sim || !sim.adjustedSim) return null;
  const parts = [formatTier(sim.adjustedSim)];
  if (sim.weWin === true) parts.push("win");
  else if (sim.weWin === false) parts.push("loss");
  if (Number.isFinite(sim.ourUnitCount) && Number.isFinite(sim.enemyUnitCount)) {
    parts.push(`${sim.ourUnitCount} vs ${sim.enemyUnitCount}`);
  }
  if (typeof sim.remainingHealthPct === "number" && Number.isFinite(sim.remainingHealthPct)) {
    parts.push(`${Math.round(sim.remainingHealthPct * 100)}%\u00A0hp`);
  }
  return parts.join(" · ");
}

function formatArmyPanel(state) {
  if (!state.hasObjective) return null;
  const action = formatArmyAction(state.movementPattern, state.moveType);
  let objective = state.objectiveId;
  if (!objective && action) objective = action.label;
  if (!objective && state.path) {
    objective = `(${state.path.target[0]}, ${state.path.target[1]})`;
  }
  if (!objective) objective = "main army";
  return {
    objective,
    action: action ? `${action.label} (${action.raw})` : null,
    eta: formatEta(state.path),
    sim: formatSim(state.sim),
    target: state.path ? state.path.target : null,
  };
}

// status: no-log | no-diagnostics | no-objective | ready
function mainArmyAt(classified, gameLoop) {
  if (!classified) return { status: "no-log" };
  if (!classified.sawMoveEvt) return { status: "no-diagnostics" };
  const panel = formatArmyPanel(armyStateAsOf(classified.events, gameLoop));
  if (!panel) return { status: "no-objective" };
  return { status: "ready", ...panel };
}
