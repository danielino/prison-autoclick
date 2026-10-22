"""Tests run offline: no game, no screen. Data and log go to a temp folder (set before prisonbot is imported)."""
import os
import sys
import tempfile

os.environ["AUTOPRISON_HOME"] = tempfile.mkdtemp(prefix="autoprison_test_")
with open(os.path.join(os.environ["AUTOPRISON_HOME"], "autoprison_data.json"), "w") as f:
    f.write('{"web_enabled": false}')  # the tests must not open the live page on port 8080
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def paint(buf, w, x0, y0, x1, y1, rgb):
    """Fill a rectangle of a BGRA buffer (as returned by winapi.grab) with an RGB colour."""
    r, g, b = rgb
    for y in range(y0, y1):
        for x in range(x0, x1):
            i = (y * w + x) * 4
            buf[i], buf[i + 1], buf[i + 2], buf[i + 3] = b, g, r, 255


def blank(w, h, rgb=(40, 40, 40)):
    buf = bytearray(w * h * 4)
    paint(buf, w, 0, 0, w, h, rgb)
    return buf


import pytest


@pytest.fixture(autouse=True)
def reset_hud_position():
    from prisonbot import vision
    vision.HUD["bar_y"] = vision.NOMINAL_BAR_Y
    vision.AREAS.clear()
    yield
    vision.HUD["bar_y"] = vision.NOMINAL_BAR_Y
    vision.AREAS.clear()



@pytest.fixture(autouse=True)
def no_settings_written_by_the_hunt(monkeypatch):
    """The hunt saves what it learns (door spots, label texts): never into a real file during the tests."""
    from prisonbot import hunt
    monkeypatch.setattr(hunt, "save", lambda cfg: None)
