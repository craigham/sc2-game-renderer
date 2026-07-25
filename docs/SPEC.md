# SC2 Replay → Tactical Video: Spec

Status: draft v1. Owner: Craig.

## Problem

The bot (`~/dev/starcraft/tbone`) plays on a ladder running Blizzard's Linux headless
SC2 build. That build has no renderer, so no real game video can be produced from
ladder games, and recent macOS changes broke watching those replays locally. Debugging
army movement, engagements, and pathing currently means reading log lines.

## Goal

A headless 2D tactical renderer: step a replay, draw a top-down schematic view of
**what the bot could see**, overlay the bot's own logged reasoning, encode to MP4.

The core debugging payoff is separating **bad information** from **bad decisions**.
Frames are rendered from a fog-limited observation taken as the bot's player id, so
what appears on screen is what the bot actually knew at that game loop — not ground
truth.

## Non-goals (explicit)

1. **Not** a replacement for watching a real replay. No unit models, animations,
   effects, portraits, or sound. Schematic shapes only.
2. **No GPU, no Windows, no retail-client video capture.** The s2client `render`
   interface and GPU-passthrough approach are rejected for v1.
3. **No ground-truth / omniscient view in v1.** Fog-limited only. (A `--disable-fog`
   comparison mode is a plausible v2, deliberately deferred.)
4. **No live/real-time viewing.** Batch: replay in, MP4 out.
5. **No interactivity.** No scrubbing, seeking, clicking units. It's a video file.
6. **No Proxmox / remote execution in v1.** Local Mac only.
   **Superseded**: `extract` now also runs on `test_lab` (192.168.1.15), driven by
   `sc_bot_test_lab`'s replay-render view, so the vs-Blizzard-AI matches run there can
   be inspected without copying files back to this Mac. Still Docker-contained, never
   installed on that host directly — consistent with how `test_lab` already runs every
   other SC2 process — so the "never on bare metal" spirit of this non-goal holds even
   though the "local Mac only" letter of it doesn't anymore.
7. **No changes to the tbone bot repo.** This tool consumes tbone's existing log
   output; it does not add instrumentation to it. If a needed field is missing, that
   is reported, not patched from here.
8. **Not a general SC2 analysis library.** Single-purpose: debugging this bot.
9. **No pixel-position assertions in tests.** The rendering layer is verified by
   looking at output frames, not by asserting coordinates.

## Architecture: two stages, one shared output, two consumers

Stepping a replay is slow and needs the SC2 client. Rendering is fast, pure, and is
what gets iterated on. These are separated so visual tweaks never re-step a replay.
The frame file `extract` produces is consumed by **two independent renderers** — the
batch MP4 pipeline and the interactive browser viewer — neither of which changes
what `extract` does.

```
                 [SC2 client required]            [pure, no SC2]
                                              ┌──── render ────► out.mp4
replay.SC2Replay ──── extract ────► frames.jsonl.gz
tbone logs ──────────────────────────────┘   └──── viewer ────► (browser, click-to-inspect)
                                              (joined at extract)
```

### Stage 1: `extract`

Steps the replay via python-sc2 with `start_replay(observed_id=<bot player id>)`,
fog **enabled**, pulling a full observation every `--sample-loops` game loops.

Internally split so the SC2 dependency is a thin shell:

- **Client adapter** — owns `SC2Process` / `start_replay` / `step`. Untested beyond a
  smoke run; this is the part that can break on macOS/Rosetta.
- **Frame mapper** (pure) — `observation proto → Frame`. All logic lives here and is
  unit-tested against checked-in captured observations.
- **Enemy memory tracker** (pure) — see below.
- **Log joiner** (pure) — see below.

### Stage 2a: `render` (batch, MP4)

Reads `frames.jsonl.gz`, draws each frame with Pillow, pipes raw RGB to `ffmpeg` over
stdin, out comes MP4. Never touches SC2 or the replay.

### Stage 2b: `viewer` (interactive, browser)

A static HTML+JS page — no server, no build step. Fetches `frames.jsonl.gz` directly
and decompresses it with the browser's native `DecompressionStream('gzip')`, so the
frame file format doesn't change or need a second export step. Renders on `<canvas>`
using the same world→pixel math as `coords.py`, ported to a few lines of JS. A
scrub bar drives playback; clicking a unit hit-tests its on-screen marker for the
current frame and shows a side panel with its full `UnitSnapshot` — health, shields,
energy, and current order(s) (ability + target).

Deliberately not built: a server, a build toolchain (webpack/vite/etc.), or state
shared across a second viewer. This is a personal debugging tool for one user on one
Mac — a single HTML file opened locally is the right amount of infrastructure.

## Fog and enemy memory

Critical detail confirmed against the vendored python-sc2:

- Enemy **structures** seen and then lost to fog remain in the observation with
  `display_type == Snapshot` (`unit.is_snapshot`).
- Enemy **mobile units** are simply absent from the observation once vision is lost.
  SC2 gives us nothing to render.

So last-known enemy positions are **our** responsibility. The extractor keeps a memory
map, `enemy_tag → (last_seen_loop, pos, unit_type, was_snapshot)`, updated every
sampled frame. Each frame emits three enemy categories:

| Category | Source | Rendered as |
| --- | --- | --- |
| `visible` | in observation, `is_visible` | solid marker |
| `snapshot` | in observation, `is_snapshot` (structures) | hollow marker |
| `remembered` | absent from observation, in memory tracker | dashed marker + age `Xs ago` |

Memory entries expire after `--memory-ttl` seconds of game time (default 60) so stale
ghosts don't accumulate across the whole map. Age is drawn on the marker so a stale
belief is visually obvious — that is the whole point of the view.

## Frame contents

Free from the observation, per frame:

- Own units: position, type, health/shields fraction, energy, current order(s)
  (`unit.orders`: ability id, target — a unit tag or a world position, mutually
  exclusive — and progress). **Only ever populated for own units** — confirmed
  against the fixture (0 of 69 enemy units had any order, vs. 81 of 108 own units).
  SC2 doesn't leak an opponent's queued actions through fog, same story as the
  single `start_locations` entry found in slice 5.
- Enemy units: the three categories above (never orders, per the above).
- Resources: minerals, vespene, income rates.
- Supply used / cap, worker count, idle worker count (`player_common.idle_worker_count`
  — turned out to be a direct field, not derived as originally assumed).
- Army value: `score.score_details.used_minerals/vespene.army` — SC2's own running
  spent-minus-lost tally (the same figure the client's built-in graphs use), not a
  recomputation from unit type costs. Also free, also not derived.
- Terrain, drawn once as a static background layer from `game_info`:
  `pathing_grid`, `placement_grid`, `terrain_height`, `playable_area`,
  `start_locations`.

Derived per frame:

- `supply_blocked: bool` (`supply_used >= supply_cap` below the 200 hard cap) —
  computable from a single observation.
- Supply-block **duration** — needs the frame sequence, not a single observation, so
  it's computed at render time by scanning consecutive frames, not in the frame file.
- Movement trails: last N sampled positions per own unit, faded by age.

## Bot-state overlay

The bot's internal state is not in the replay. It comes from the bot's log.

**What the ladder actually returns is `stderr.log`, not the structured JSONL.** This
was verified against the real ladder match in `replays/4891371/`, and it corrects an
earlier assumption in this spec. That log contains **zero** `MOVE_EVT`, `MOVE_ANOM`,
`engagement_mode_snapshot`, `army_geometry_snapshot`, or encounter JSONL records. The
encounter sink does run on ladder — the log shows it writing to
`/bot/data/encounters/encounters_UltraloveAIE_<ts>.jsonl` — but that path is inside the
match container and the file is not part of the downloadable artifacts. The rich
streams in `tbone/docs/structured_logging_contract.md` are, in practice, **local-match
only**. See "Getting the structured streams onto the ladder" below.

### The format we do get

Every in-game line is prefixed by the sharpy log manager, already keyed by game loop:

```
06:06 8200  104ms   655M 1033G  74/102U INFO terranbot...zone_defense:1062 Pulling worker [...]
 │      │      │      │     │      │
 │      │      │      │     │      └─ supply used / cap
 │      │      │      │     └─ vespene          └─ minerals (CAN BE NEGATIVE: "-100M")
 │      │      │      └─ step duration ms
 │      │      └─ game loop          └─ game clock MM:SS
```

Measured on the fixture: **99.7% of lines parse** (2987/2997). The 10 failures are the
container preamble (matplotlib warnings, loguru-formatted sc2 startup lines) — not
in-game data. Bot step size is 4 loops, which conveniently matches the default frame
sampling interval.

### v1 overlay content, in priority order

1. **Resource/supply strip from the log prefix** — free on every line, and valuable as
   a *cross-check*: the log's minerals/gas/supply are what the bot believed; the
   observation is truth. A divergence is itself a bug signal. Negative minerals appear
   in real logs and must not crash the parser.
2. **Positioned events** — these carry map coordinates and can be drawn in the world:
   `[TrainSCV]` / `[TerranUnit]` / `[BuildAddon]` / `[BuildGas]` / `[PlanCancelBuilding]`
   at `(x, y)`, and `pathing_manager` `No path found (x, y), (x, y)` failures.
3. **State-change banners** — `[GameAnalyzer] Income advantage is now <X>`,
   `zone_defense` "High working danger, should evacuate mining zone",
   "Workers in danger: N", `terry2` `ActionError(ability_id=…)`.
4. **End-of-game summary** — `[GameAnalyzerEnd]` unit totals/alive/dead and resource
   averages, usable as a closing card.

Deferred to v2: anything requiring the structured JSONL streams.

**Noise warning.** `zone_defense:1062 "Pulling worker"` is 2243 of 2997 lines (75%) in
the fixture. The parser keeps a whitelist of interesting events rather than rendering
everything, or the overlay is unreadable.

**Join rule.** Each log record attaches to the nearest sampled frame at or after its
game loop, within a tolerance of one sample interval. Records outside tolerance are
dropped and counted, and the count is reported at the end of extraction so a mismatched
replay/log pairing is loud rather than invisible. The overlay is optional — with no log
supplied, the renderer still produces video.

### Getting the structured streams onto the ladder (decision, not v1 work)

The high-value streams exist but never leave the container. Options, all requiring a
change in the tbone repo, which v1 does not make:

- Echo encounter JSONL records to stderr as well as the file, so they ride back in
  `stderr.log`. Simplest; costs log volume.
- Write to whatever directory the ladder returns as bot artifacts, if one exists.
- Accept local-only richness: full overlay for local matches, thin overlay for ladder.

This tool is built so the joiner is pluggable — if those records start appearing in
`stderr.log`, it's a new parser, not a redesign.

## Inputs and layout

Replays and their logs are dropped in `replays/<aiarena-match-id>/` as downloaded; see
[replays/README.md](../replays/README.md).

The bot's player id is **inferred from the log**, not configured: the fixture's
`Player 2 - Bot T2(Terran)` / `Result for player 2 … Defeat` lines give both the
observed player id and the game outcome. `meta.json` is only needed as an override.

## Output defaults (proposed — say if you want different)

| Setting | Default | Note |
| --- | --- | --- |
| `--sample-loops` | 4 | 22.4 loops/game-sec, so 5.6 samples per game second |
| `--fps` | 30 | 30 fps × 4 loops = **~5.4× real time**; 15-min game → ~2.8-min video |
| `--resolution` | 1280×720 | map pane + HUD sidebar |
| `--memory-ttl` | 60s | game time |

A `--realtime` preset (`--sample-loops 2 --fps 11`) plays at ~1× for close inspection.
Frame count at defaults for a 15-min game: ~5,000.

## Environment

- Local Mac (arm64), Python 3.12, `uv` for deps.
- `ffmpeg` **is not currently installed** — `brew install ffmpeg` is a prerequisite.
- SC2 at `/Applications/StarCraft II`, base builds 75689 / 93333 / 94137 / 95248 /
  95299 / 95841. `Base75689` matches the classic ladder build.

## Fixture

`replays/4891371/` — a real aiarena ladder match, and the fixture for all tests.

| | |
| --- | --- |
| Match | aiarena 4891371, t-bone (player 2) vs StarK234 |
| Map | UltraloveAIE |
| Length | 11:19 — 15,228 loops |
| Result | Defeat for the bot |
| SC2 build | **4.10.0.75689** |
| Log | 2,997 lines, 99.7% parseable |

At default sampling that's ~3,800 frames — a good size: long enough to be a real game,
short enough to iterate on.

## Chief risk — RESOLVED

**Local Mac stepping is dead. Extraction runs in a linux/amd64 Docker container.**

SC2 4.10 (75689) aborts on launch on macOS 26.5.1 — `EXC_CRASH / SIGABRT`, translated
x86-64, confirmed from the crash report. Rosetta is installed and running, so this is
the old build being incompatible with current macOS, not a missing translator. That is
the same breakage that stopped local replay watching. Newer SC2 builds launch, but
cannot open a 4.10 replay.

The container path works and is fast enough that no Docker settings change is needed:

| | |
| --- | --- |
| Image | `sc2-extract:4.10`, from `docker/Dockerfile` |
| Base | `stephanzlatarev/starcraft` — carries Blizzard's public `SC2.4.10.zip` at `/StarCraftII` (Base75689) |
| Emulation | QEMU (Docker Desktop Rosetta is **off**; enabling it would only make this faster) |
| Full extract | 3,809 frames in **218s** stepping, 4m28s wall including SC2 boot |
| Throughput | 48.6 frames/s early game, 17.4 frames/s sustained (late frames carry ~250 units) |

Two container gotchas, both handled:

- **The map must be mounted.** `UltraloveAIE_v2.SC2Map` comes from the local
  `/Applications/StarCraft II/Maps`.
- **python-sc2's `start_replay()` rewrites the path to a basename on Linux**
  (`sc2/controller.py`), and the client then fails with "Unable to open replay". We
  issue `RequestStartReplay` ourselves with an absolute path, falling back to
  `replay_data` bytes.

The two-stage split absorbs all of this: only `extract` needs Docker. `render` stays
local, pure, and fast to iterate — which is the stage that actually gets iterated.
