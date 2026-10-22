"""The detectors were calibrated on one window size (2360x1328, 16:9). These tests draw the same scene at other 16:9 sizes
(everything scaled with the window) and check that the results do not change with the size."""
import pytest

from conftest import paint
from prisonbot import vision
from test_vision import FakeScreen

SIZES = [(1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2000, 1125), (2560, 1440), (3840, 2160)]
BRIGHT, DARK = (228, 10, 1), (141, 25, 8)
ORANGE = (250, 170, 30)


@pytest.mark.parametrize("w,h", SIZES)
def test_a_health_bar_is_found_and_measured_at_any_size(monkeypatch, w, h):
    s = FakeScreen(monkeypatch, w, h)
    bw, bh = int(0.045 * w), max(int(0.0055 * h), 3)
    x0, y0 = int(0.45 * w), int(0.20 * h)
    s.paint(x0, y0, x0 + bw, y0 + bh, DARK)
    s.paint(x0, y0, x0 + int(bw * 0.4), y0 + bh, BRIGHT)  # 40% health left
    bars = vision.find_bars(0)
    assert len(bars) == 1
    assert bars[0][0] == pytest.approx((x0 + bw / 2) / w, abs=0.01)
    assert vision.LAST_BARS[0][1] == pytest.approx(0.4, abs=0.1)


@pytest.mark.parametrize("w,h", SIZES)
def test_the_hud_digit_is_read_at_any_size(monkeypatch, w, h):
    s = FakeScreen(monkeypatch, w, h)
    k = w / 2000.0
    ax, ay = int(vision.ATTACKS_AREA[0] * w), int(vision.ATTACKS_AREA[1] * h)
    gx, gy = ax + int(17 * k), ay + int(35 * k)  # where the digit sits in the box (measured at 2000 px)
    cw, ch = 14 * k / 8, 27 * k / 12
    for n in (1, 2, 3):
        s.paint(0, 0, w, h, (40, 40, 40))
        for j, row in enumerate(vision.ATTACK_GLYPHS[n]):
            for i, c in enumerate(row):
                if c == "#":
                    s.paint(gx + int(i * cw), gy + int(j * ch), gx + int((i + 1) * cw) + 1, gy + int((j + 1) * ch) + 1, ORANGE)
        assert vision.read_attacks(0) == n, "digit %d at %dx%d" % (n, w, h)


@pytest.mark.parametrize("w,h", SIZES)
def test_a_name_label_is_found_and_noise_ignored_at_any_size(monkeypatch, w, h):
    s = FakeScreen(monkeypatch, w, h)
    k = w / 2000.0
    lx, ly = int(0.40 * w), int(0.30 * h)
    for row in range(int(8 * k) or 1):  # a few text-like strokes
        s.paint(lx, ly + row * int(2 * k + 1), lx + int(60 * k), ly + row * int(2 * k + 1) + max(int(k), 1), (170, 170, 190))
    s.paint(int(0.6 * w), int(0.5 * h), int(0.6 * w) + 2, int(0.5 * h) + 2, (170, 170, 190))  # noise
    bots = vision.find_bots(0)
    assert len(bots) == 1
    assert bots[0][0] == pytest.approx((lx + 30 * k) / w, abs=0.02)


@pytest.mark.parametrize("w,h", SIZES)
def test_the_health_bar_length_follows_the_window_width(w, h):
    from conftest import blank
    gw, gh = 200, 20
    buf = blank(gw, gh)
    full = int(vision.HEALTH_LEN * w)
    if full + 20 > gw:
        pytest.skip("bar longer than the test strip")
    paint(buf, gw, 10, 8, 10 + full // 2, 11, (200, 20, 20))
    assert vision.health_from_buf(buf, gw, gh, w) == pytest.approx(0.5, abs=0.06)
