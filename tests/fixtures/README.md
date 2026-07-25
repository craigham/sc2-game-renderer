# Test fixtures

Captured SC2 observations, so the data-layer tests run on the Mac with **no SC2 and no
Docker**. Local SC2 cannot open these replays at all (see `docs/SPEC.md` § Chief risk),
which is exactly why these exist.

## 4891371/

Captured from `replays/4891371/` — the ladder loss on UltraloveAIE — by
`scripts/spike_step_replay.py --dump-fixture`.

| File | Contents |
| --- | --- |
| `observations.pb.gz` | 51 `ResponseObservation` messages, every 76th sampled frame: loops 0 → 15200, step 304 (~13.5s of game time apart) |
| `game_info.pb.gz` | 1 `ResponseGameInfo` — terrain grids, playable area, start locations |

Both are **length-delimited gzip**: repeated `<uint32 little-endian length><message bytes>`.

```python
import gzip, struct
from s2clientprotocol import sc2api_pb2 as sc_pb

def read_records(path, msg_type):
    with gzip.open(path, "rb") as f:
        while (hdr := f.read(4)):
            yield msg_type.FromString(f.read(struct.unpack("<I", hdr)[0]))

obs = list(read_records("observations.pb.gz", sc_pb.ResponseObservation))
```

## Known values, for asserting against

Observed as **player 2** (the bot) with fog **on**, so enemy data is deliberately partial.

Frame 42, game loop 12768 (570s) — mid-collapse:

| Alliance / display_type | Count |
| --- | --- |
| Self, Visible `(1, 1)` | 108 |
| Enemy, Visible `(4, 1)` | 42 |
| Enemy, **Snapshot** `(4, 2)` | 27 |
| Neutral, Visible `(3, 1)` | 27 |
| Neutral, Snapshot `(3, 2)` | 125 |

minerals 125, supply 81/118. Map `Ultralove AIE`, 184×184, playable area (26, 26, 132, 132).

The enemy Snapshot entries are remembered **structures** — proof the fog-limited view
works. Mobile enemy units have no snapshot equivalent; they vanish from the observation
entirely, which is why the extractor needs its own memory tracker (slice 2).

Whole-game shape, useful for picking test frames — the defeat is clearly visible:

| Loop | Own | Enemy vis | Supply |
| --- | --- | --- | --- |
| 12400 | 127 | 0 | 99/110 |
| 12800 | 104 | 42 | 77/118 |
| 13200 | 53 | 45 | 23/118 |
| 14000 | 19 | 70 | 0/56 |
| 15200 | 1 | 16 | 0/0 |
