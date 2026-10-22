import os

import pytest

from prisonbot import diagnostic, vision
from test_vision import FakeScreen


def patch_window(monkeypatch, w, h):
    s = FakeScreen(monkeypatch, w, h)
    monkeypatch.setattr(diagnostic, "client_rect", lambda hw: (0, 0, w, h))
    monkeypatch.setattr(diagnostic, "find_bars", vision.find_bars)
    return s


def test_the_calibrated_shape_is_fine_at_any_16_9_size(monkeypatch):
    for w, h in ((1280, 720), (1920, 1080), (2360, 1328), (2560, 1440)):
        monkeypatch.setattr(diagnostic, "client_rect", lambda hw, w=w, h=h: (0, 0, w, h))
        text, ok = diagnostic.window_info(1)
        assert ok and "%dx%d" % (w, h) in text


def test_another_shape_is_flagged(monkeypatch):
    for w, h in ((1920, 1200), (3440, 1440), (1024, 768)):
        monkeypatch.setattr(diagnostic, "client_rect", lambda hw, w=w, h=h: (0, 0, w, h))
        assert diagnostic.window_info(1)[1] is False


def test_the_window_size_is_logged_with_a_warning_for_another_shape(monkeypatch):
    lines = []
    monkeypatch.setattr(diagnostic, "log", lines.append)
    monkeypatch.setattr(diagnostic, "client_rect", lambda hw: (0, 0, 3440, 1440))
    assert diagnostic.log_window(1) is False
    assert lines[0].startswith("WINDOW window 3440x1440") and "warning" in lines[1]


def test_the_report_has_a_screenshot_and_what_the_detectors_see(monkeypatch):
    s = patch_window(monkeypatch, 800, 450)
    s.paint(360, 90, 396, 93, (228, 10, 1))
    folder = diagnostic.save_report(1, {"hunt_area": None, "hunt_gap": 0.07})
    png = open(os.path.join(folder, "screen.png"), "rb").read()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    report = open(os.path.join(folder, "report.txt"), encoding="utf-8").read()
    assert "window 800x450" in report and "attacks left" in report and "health bars" in report
