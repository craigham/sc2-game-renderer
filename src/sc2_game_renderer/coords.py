"""World (SC2 game units) <-> pixel coordinate transform for the rendered map pane.

Cropped to the map's playable_area — typically ~70% of the full grid; the rest is an
unpathable border not worth spending canvas on — and flipped so pixel row 0 is north,
matching how the game is normally viewed.

The flip direction is confirmed against the vendored python-sc2 `PixelMap`, not
guessed: its own `.plot()` uses `origin="lower"`, meaning row 0 of the raw grid is
y=0 (south). Image rows increase downward, so producing a north-up image means row 0
of the *output* must be the highest-y row of the input — the flip below.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorldToPixel:
    origin_x: float
    origin_y: float
    extent_width: float
    extent_height: float
    scale: float

    @classmethod
    def for_playable_area(cls, playable_area: tuple[int, int, int, int], scale: float) -> "WorldToPixel":
        x0, y0, x1, y1 = playable_area
        return cls(origin_x=x0, origin_y=y0, extent_width=x1 - x0, extent_height=y1 - y0, scale=scale)

    @property
    def pixel_width(self) -> int:
        return round(self.extent_width * self.scale)

    @property
    def pixel_height(self) -> int:
        return round(self.extent_height * self.scale)

    def to_pixel(self, x: float, y: float) -> tuple[float, float]:
        """World position -> pixel position in the cropped, north-up canvas.

        Not clamped to the canvas — a unit near the playable-area edge legitimately
        projects just outside it, and callers may want that (e.g. a remembered-enemy
        marker drawn at the map border).
        """
        px = (x - self.origin_x) * self.scale
        py = (self.origin_y + self.extent_height - y) * self.scale
        return px, py
