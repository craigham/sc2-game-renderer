"""Dev preview for slice 5 — no CLI yet (that's slice 9's `render`).

    uv run python scripts/preview_terrain.py out/4891371.frames.jsonl.gz preview.png
"""

import sys
from pathlib import Path

from sc2_game_renderer.frame_file import FrameFileReader
from sc2_game_renderer.render_terrain import render_terrain

frame_file, out = Path(sys.argv[1]), Path(sys.argv[2])

with FrameFileReader(frame_file) as reader:
    header = reader.header

print(f"map: {header.map_name}  playable_area: {header.playable_area}  start_locations: {header.start_locations}")
img = render_terrain(header)
img.save(out)
print(f"wrote {out} ({img.width}x{img.height})")
