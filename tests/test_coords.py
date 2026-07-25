"""Pure geometry tests for the world<->pixel transform. Per docs/SPEC.md non-goal 9,
the *rendering* layer (what render_terrain.py actually draws) is verified by looking
at output images, not asserted here — but this transform is ordinary math with a
south/north flip that's easy to get backwards, and every later rendering slice
depends on it, so it gets real unit tests.
"""

from sc2_game_renderer.coords import WorldToPixel

# A stand-in for the real fixture's playable_area (26, 26, 158, 158) -> 132x132, but
# kept small and round here so expected pixel values are easy to hand-verify.
PLAYABLE_AREA = (10, 20, 50, 60)  # x0, y0, x1, y1 -> 40 wide, 40 tall


def test_extent_and_pixel_size():
    t = WorldToPixel.for_playable_area(PLAYABLE_AREA, scale=2.0)
    assert (t.extent_width, t.extent_height) == (40, 40)
    assert (t.pixel_width, t.pixel_height) == (80, 80)


def test_southwest_corner_maps_to_bottom_left():
    # (origin_x, origin_y) is the map's south-west corner (lowest x, lowest y).
    t = WorldToPixel.for_playable_area(PLAYABLE_AREA, scale=1.0)
    px, py = t.to_pixel(10, 20)
    assert (px, py) == (0, 40)  # x=0 (left); y=bottom of a 40-tall canvas


def test_northwest_corner_maps_to_top_left():
    # Highest y (north) must land at pixel row 0 (top) — this is the flip that
    # matters: get it backwards and the whole map renders upside down.
    t = WorldToPixel.for_playable_area(PLAYABLE_AREA, scale=1.0)
    px, py = t.to_pixel(10, 60)
    assert (px, py) == (0, 0)


def test_southeast_corner_maps_to_bottom_right():
    t = WorldToPixel.for_playable_area(PLAYABLE_AREA, scale=1.0)
    px, py = t.to_pixel(50, 20)
    assert (px, py) == (40, 40)


def test_center_maps_to_canvas_center():
    t = WorldToPixel.for_playable_area(PLAYABLE_AREA, scale=1.0)
    px, py = t.to_pixel(30, 40)  # midpoint of both axes
    assert (px, py) == (20, 20)


def test_scale_multiplies_pixel_distance():
    t1 = WorldToPixel.for_playable_area(PLAYABLE_AREA, scale=1.0)
    t4 = WorldToPixel.for_playable_area(PLAYABLE_AREA, scale=4.0)
    p1 = t1.to_pixel(30, 40)
    p4 = t4.to_pixel(30, 40)
    assert p4 == (p1[0] * 4, p1[1] * 4)


def test_point_outside_playable_area_is_not_clamped():
    # A unit near the map edge can legitimately fall just outside the playable
    # rectangle; to_pixel must not clamp it back in.
    t = WorldToPixel.for_playable_area(PLAYABLE_AREA, scale=1.0)
    px, py = t.to_pixel(5, 20)  # 5 world units west of origin_x
    assert px == -5
