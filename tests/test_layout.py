from sc2_game_renderer.layout import compute_layout


def test_square_map_fills_a_matching_square_pane_with_no_letterbox():
    layout = compute_layout(output_width=1000, output_height=800, sidebar_width=200, extent_width=132, extent_height=132)
    assert layout.map_pane_width == 800
    assert (layout.rendered_width, layout.rendered_height) == (800, 800)
    assert (layout.map_offset_x, layout.map_offset_y) == (0, 0)


def test_wide_map_in_a_square_pane_letterboxes_top_and_bottom():
    layout = compute_layout(output_width=1000, output_height=800, sidebar_width=200, extent_width=200, extent_height=100)
    assert layout.map_scale == 4.0  # min(800/200, 800/100) = min(4, 8)
    assert (layout.rendered_width, layout.rendered_height) == (800, 400)
    assert layout.map_offset_x == 0
    assert layout.map_offset_y == 200  # (800 - 400) / 2


def test_tall_map_in_a_square_pane_letterboxes_left_and_right():
    layout = compute_layout(output_width=1000, output_height=800, sidebar_width=200, extent_width=100, extent_height=200)
    assert layout.map_scale == 4.0  # min(800/100, 800/200) = min(8, 4)
    assert (layout.rendered_width, layout.rendered_height) == (400, 800)
    assert layout.map_offset_x == 200  # (800 - 400) / 2
    assert layout.map_offset_y == 0


def test_square_map_in_the_default_1280x720_resolution_letterboxes_left_and_right():
    # Matches the real fixture's shape (playable_area is square) at the spec's
    # documented default resolution and sidebar width.
    layout = compute_layout(output_width=1280, output_height=720, sidebar_width=280, extent_width=132, extent_height=132)
    assert layout.map_pane_width == 1000
    assert (layout.rendered_width, layout.rendered_height) == (720, 720)
    assert layout.map_offset_y == 0
    assert layout.map_offset_x == 140  # (1000 - 720) / 2


def test_output_width_equals_map_pane_plus_sidebar():
    layout = compute_layout(output_width=1280, output_height=720, sidebar_width=280, extent_width=132, extent_height=132)
    assert layout.map_pane_width + layout.sidebar_width == layout.output_width
