import pytest

from conftest import blank, paint
from prisonbot import vision

LAVENDER = (170, 170, 190)
RED = (200, 20, 20)
YELLOW = (240, 240, 20)


def test_health_from_buf_half_bar():
    w, h, cw = 200, 20, 2000
    buf = blank(w, h)
    full = int(vision.HEALTH_LEN * cw)
    paint(buf, w, 10, 8, 10 + full // 2, 11, RED)
    assert vision.health_from_buf(buf, w, h, cw) == pytest.approx(0.5, abs=0.05)


def test_health_from_buf_empty():
    assert vision.health_from_buf(blank(100, 10), 100, 10, 2000) == 0.0


def test_find_labels_finds_lavender_block_only():
    w, h = 400, 200
    buf = blank(w, h)
    paint(buf, w, 100, 50, 160, 60, LAVENDER)
    paint(buf, w, 300, 150, 303, 152, LAVENDER)  # too small: noise
    labels = vision.find_labels(buf, w, h, 1.0)
    assert len(labels) == 1
    x, y, _ = labels[0]
    assert x == pytest.approx(130 / w, abs=0.03)
    assert y == pytest.approx(55 / h, abs=0.05)


def test_sig_similar_same_and_different():
    a = frozenset((x, y) for x in range(0, 40, 2) for y in range(0, 8, 2))
    b = frozenset((x, y) for x in range(0, 40, 4) for y in range(0, 8, 4))
    assert vision.sig_similar(a, a)
    assert not vision.sig_similar(a, b)
    assert not vision.sig_similar(a, None)


def test_red_line_is_error_needs_a_long_red_line():
    w, h = 1000, 30
    long_line = blank(w, h)
    paint(long_line, w, 0, 5, 700, 25, (230, 10, 10))
    short_line = blank(w, h)
    paint(short_line, w, 0, 5, 80, 25, (230, 10, 10))
    assert vision.red_line_is_error(long_line, w, h, 1000)
    assert not vision.red_line_is_error(short_line, w, h, 1000)


class FakeScreen:
    """A 2000x1000 client area whose pixels come from a buffer; grab() cuts out the requested rectangle."""

    def __init__(self, monkeypatch, w=2000, h=1000):
        self.w, self.h = w, h
        self.buf = blank(w, h)
        monkeypatch.setattr(vision, "client_rect", lambda hw: (0, 0, w, h))
        monkeypatch.setattr(vision, "grab", self.grab)

    def grab(self, x, y, rw, rh):
        out = bytearray(rw * rh * 4)
        for j in range(rh):
            s = ((y + j) * self.w + x) * 4
            out[j * rw * 4:(j + 1) * rw * 4] = self.buf[s:s + rw * 4]
        return bytes(out)

    def paint(self, x0, y0, x1, y1, rgb):
        paint(self.buf, self.w, x0, y0, x1, y1, rgb)


def test_find_bars_returns_body_below_the_bar(monkeypatch):
    s = FakeScreen(monkeypatch)
    s.paint(900, 200, 990, 207, RED)  # an enemy bar, 90 px wide
    bars = vision.find_bars(0)
    assert len(bars) == 1
    x, y = bars[0]
    assert x == pytest.approx(0.4725, abs=0.01)
    assert y == pytest.approx(0.2035 + vision.BAR_DROP, abs=0.01)


def test_find_bars_ignores_own_bar(monkeypatch):
    s = FakeScreen(monkeypatch)
    s.paint(900, 200, 990, 207, RED)  # enemy
    s.paint(1100, 400, 1190, 407, RED)  # own bar ...
    s.paint(1110, 370, 1180, 385, YELLOW)  # ... under the yellow own label
    bars = vision.find_bars(0)
    assert len(bars) == 1 and bars[0][0] < 0.5


def test_find_bars_nothing_on_plain_screen(monkeypatch):
    FakeScreen(monkeypatch)
    assert vision.find_bars(0) == []


def test_detect_combat_banner(monkeypatch):
    s = FakeScreen(monkeypatch)
    fx, fy, fw, fh = vision.DETECT["combat"][:4]
    assert not vision.detect(0, "combat")[0]
    s.paint(int(fx * 2000), int(fy * 1000), int((fx + fw) * 2000), int((fy + fh) * 1000), (220, 40, 40))
    assert vision.detect(0, "combat")[0]


def test_snapshot_writes_a_png_and_keeps_only_the_latest(monkeypatch, tmp_path):
    monkeypatch.setattr(vision, "HERE", str(tmp_path))
    monkeypatch.setattr(vision, "client_rect", lambda h: (0, 0, 100, 100))
    monkeypatch.setattr(vision, "grab", lambda x, y, w, hh: blank(w, hh, (200, 30, 30)))
    monkeypatch.setattr(vision, "SNAP_KEEP", 2)
    for n in range(4):
        monkeypatch.setattr(vision.time, "strftime", lambda f, n=n: "2026010%d-000000" % n)
        vision.snapshot(1, "t")
    files = sorted((tmp_path / "snapshots").iterdir())
    assert len(files) == 2 and files[-1].name.startswith("20260103")
    assert files[-1].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_find_bars_sees_a_hurt_bot_whose_bar_is_mostly_dark_red(monkeypatch):
    s = FakeScreen(monkeypatch)
    s.paint(900, 200, 920, 207, (228, 10, 1))  # health left: bright red
    s.paint(920, 200, 990, 207, (141, 25, 8))  # health lost: dark red (seen on a real screenshot)
    bars = vision.find_bars(0)
    assert len(bars) == 1 and bars[0][0] == pytest.approx(0.4725, abs=0.01)


def test_find_bars_sees_a_bot_at_the_very_top_of_the_room(monkeypatch):
    s = FakeScreen(monkeypatch)
    s.paint(1000, 40, 1090, 47, (228, 10, 1))  # name and bar above the old scan area (it started at 10% of the height)
    bars = vision.find_bars(0)
    assert len(bars) == 1 and bars[0][1] < 0.12


def test_find_bars_ignores_the_hud_boxes_top_left(monkeypatch):
    s = FakeScreen(monkeypatch)
    s.paint(200, 30, 290, 37, (228, 10, 1))
    assert vision.find_bars(0) == []


def test_find_bars_sees_the_shaded_bar_at_the_top_of_the_screen(monkeypatch):
    s = FakeScreen(monkeypatch)
    s.paint(1000, 36, 1100, 48, (20, 18, 15))  # the dark frame of the bar
    s.paint(1002, 38, 1030, 46, (127, 0, 0))  # health left (shaded by the game there)
    s.paint(1030, 38, 1098, 46, (47, 0, 0))  # health lost
    bars = vision.find_bars(0)
    assert len(bars) == 1 and bars[0][0] == pytest.approx(0.525, abs=0.01)


def test_find_bars_ignores_a_big_red_area(monkeypatch):
    s = FakeScreen(monkeypatch)
    s.paint(1000, 300, 1100, 420, (141, 25, 8))  # red clothes / a tinted body: far too tall for a bar
    assert vision.find_bars(0) == []


def test_turn_line_is_the_short_yellow_text(monkeypatch):
    buf = blank(1200, 40, (30, 30, 30))
    paint(buf, 1200, 20, 10, 200, 16, (250, 230, 20))  # "El turno es tuyo."
    assert vision.turn_line_from_buf(buf, 1200, 40, 2000)
    other = blank(1200, 40, (30, 30, 30))
    paint(other, 1200, 20, 10, 700, 16, (230, 30, 30))  # an enemy attack line: red
    assert not vision.turn_line_from_buf(other, 1200, 40, 2000)
    assert not vision.turn_line_from_buf(blank(1200, 40, (30, 30, 30)), 1200, 40, 2000)
