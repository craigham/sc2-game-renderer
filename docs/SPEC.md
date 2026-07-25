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
6. **No Proxmox / remote execution in v1.** Local Mac only. If it later moves to that
   server it goes in a VM or LXC — never installed on the host.
7. **No changes to the tbone bot repo.** This tool consumes tbone's existing log
   output; it does not add instrumentation to it. If a needed field is missing, that
   is reported, not patched from here.
8. **Not a general SC2 analysis library.** Single-purpose: debugging this bot.
9. **No pixel-position assertions in tests.** The rendering layer is verified by
   looking at output frames, not by asserting coordinates.

## Architecture: two stages

Stepping a replay is slow and needs the SC2 client. Rendering is fast, pure, and is
what gets iterated on. These are separated so visual tweaks never re-step a replay.

```
                 [SC2 client required]            [pure, no SC2]
replay.SC2Replay ──── extract ────► frames.jsonl.gz ──── render ────► out.mp4
tbone logs ──────────────────────────────┘ (joined at extract)
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

### Stage 2: `render`

Reads `frames.jsonl.gz`, draws each frame with Pillow, pipes raw RGB to `ffmpeg` over
stdin, out comes MP4. Never touches SC2 or the replay.

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

- Own units: position, type, health/shields fraction, energy.
- Enemy units: the three categories above.
- Resources: minerals, vespene, income rates.
- Supply used / cap, worker count, army value.
- Terrain, drawn once as a static background layer from `game_info`:
  `pathing_grid`, `placement_grid`, `terrain_height`, `playable_area`,
  `start_locations`.

Derived per frame:

- Supply-blocked (and running block duration).
- Idle worker count.
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

## Chief risk

Whether python-sc2 can step a replay headlessly on this Mac at all.

This got **materially less risky**: the fixture replay is build `4.10.0.75689`, and
`/Applications/StarCraft II/Versions/Base75689` is installed locally — an exact match.
`tbone/watch_replay.py` also already works around the Apple Silicon/Rosetta crash by
launching SC2 without `base_build`/`data_hash` overrides. Still unproven for *headless*
stepping, so slice 0 remains a timeboxed spike. It also produces the
captured-observation fixture that makes every later slice testable without SC2.
