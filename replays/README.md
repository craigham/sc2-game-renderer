# Where to put replays and their logs

One directory per ladder match, named with the **aiarena match id**, containing the two
files exactly as downloaded — no renaming:

```
replays/
  4891371/
    4891371_StarK234_0001_t-bone_UltraloveAIE_v2.SC2Replay
    stderr.log
  <next-match-id>/
    ...
```

The replay filename encodes everything needed, so nothing has to be configured:

```
4891371_StarK234_0001_t-bone_UltraloveAIE_v2.SC2Replay
   │        │      │      │        │        └─ bot version
   │        │      │      │        └─ map
   │        │      │      └─ our bot
   │        │      └─ game number in the match
   │        └─ opponent
   └─ aiarena match id (= directory name)
```

Both files come from the match page on aiarena.net for that match id. Only the
`.SC2Replay` is required; without `stderr.log` the renderer still produces video, just
with no bot-state overlay.

Local (non-ladder) games can go here too — a directory with a `.SC2Replay` and
optionally a log from `~/dev/starcraft/tbone/match_logs/`. Those carry the richer
structured streams; ladder games do not (see below).

## What's in stderr.log — and what isn't

Ladder `stderr.log` is the **sharpy text log**, already keyed by game loop:

```
06:06 8200  104ms   655M 1033G  74/102U INFO terranbot...zone_defense:1062 Pulling worker
 clock  loop  step   min   gas   supply    level  logger:line  message
```

It does **not** contain `MOVE_EVT`, `MOVE_ANOM`, `engagement_mode_snapshot`,
`army_geometry_snapshot`, or the encounter JSONL. The encounter sink writes to
`/bot/data/encounters/` *inside the match container*, and that file isn't in the
download. See `docs/SPEC.md` § "Getting the structured streams onto the ladder".

## meta.json (optional override)

The bot's player id is normally read from the log (`Player 2 - Bot T2(Terran)`). Add
this only if that fails:

```json
{
  "bot_player_id": 2,
  "note": "free text, e.g. 'lost to the 2-base timing at 6:30'"
}
```

## The test fixture

**`4891371/` is the checked-in fixture** — 11:19, 15,228 loops, UltraloveAIE, build
4.10.0.75689, a loss worth debugging. It is committed despite the ignore rules below.

`tests/fixtures/` additionally holds a small **captured observation dump** taken from
this replay, so the extractor's unit tests run without SC2 installed.

## Git

Replays and logs are not committed by default — only the fixture set above, which is
force-added. See `.gitignore`.
