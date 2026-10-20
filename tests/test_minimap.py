from conftest import blank, paint
from prisonbot import minimap


def test_set_forbidden_builds_a_grid_covering_the_rect():
    minimap.set_forbidden([[0.2, 0.2, 0.4, 0.4]])
    assert len(minimap.FORBIDDEN_SPOTS) > 4
    xs = [s[0] for s in minimap.FORBIDDEN_SPOTS]
    ys = [s[1] for s in minimap.FORBIDDEN_SPOTS]
    assert min(xs) == 0.2 and max(xs) == 0.4 and min(ys) == 0.2 and max(ys) == 0.4
    minimap.set_forbidden([])
    assert minimap.FORBIDDEN_SPOTS == []


def test_forbidden_spots_are_part_of_the_deadly_list():
    minimap.set_forbidden([[0.2, 0.2, 0.3, 0.3]])
    try:
        deadly = minimap.read_minimap(blank(357, 100), 357, 100)[3]
        assert len(deadly) == len(minimap.FORBIDDEN_SPOTS) > 0
    finally:
        minimap.set_forbidden([])


def test_read_minimap_all_red_diamond_is_deadly_and_half_red_is_a_bot():
    w, h = 357, 100
    buf = blank(w, h, (200, 200, 200))
    paint(buf, w, 50, 40, 60, 50, (230, 20, 20))   # all red
    paint(buf, w, 200, 40, 210, 50, (230, 20, 20))  # red border, light fill
    paint(buf, w, 202, 42, 208, 48, (230, 230, 230))
    player, bots, dots, deadly = minimap.read_minimap(buf, w, h)
    assert len(deadly) == 1 and abs(deadly[0][0] - 55 / w) < 0.03
    assert len(bots) == 1 and abs(bots[0][0] - 205 / w) < 0.03


def test_read_minimap_finds_player_arrow():
    w, h = 357, 100
    buf = blank(w, h, (200, 200, 200))
    paint(buf, w, 100, 30, 112, 42, (20, 120, 250))
    player = minimap.read_minimap(buf, w, h)[0]
    assert player and abs(player[0] - 106 / w) < 0.03


def _fingerprint(buf, w=300, h=200):
    minimap.grab_minimap = lambda hw: (bytes(buf), w, h)
    return minimap.grab_zone(0)


def test_grab_zone_is_none_for_a_uniform_map():
    assert _fingerprint(blank(300, 200, (200, 200, 200))) is None


def test_zone_differs_same_shifted_and_other_map():
    w, h = 300, 200
    a = blank(w, h, (30, 30, 30))
    paint(a, w, 50, 40, 200, 140, (210, 210, 220))
    shifted = blank(w, h, (30, 30, 30))
    paint(shifted, w, 53, 42, 203, 142, (210, 210, 220))
    other = blank(w, h, (30, 30, 30))
    paint(other, w, 150, 100, 290, 190, (210, 210, 220))
    fa, fs, fo = _fingerprint(a), _fingerprint(shifted), _fingerprint(other)
    assert minimap.zone_differs(fa, fa) == 0
    assert minimap.zone_differs(fa, fs) < 0.1
    assert minimap.zone_differs(fa, fo) > 0.25


def test_zone_differs_none_when_unusable():
    assert minimap.zone_differs(None, [0] * 784) is None
