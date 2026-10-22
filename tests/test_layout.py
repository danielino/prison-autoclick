"""The vision model proposes where the sections of the screen are; the colour detectors judge the proposal."""
import json

import pytest

from conftest import blank, paint
from prisonbot import hunt, layout, llm, minimap, vision
from test_llm import server, Fake  # the fake Ollama server (fixture)
from test_vision import FakeScreen

W, H = 2000, 1000
BRIGHT = (228, 10, 1)
ORANGE = (250, 170, 30)


@pytest.fixture(autouse=True)
def clean():
    vision.AREAS.clear()
    layout.REPORT.clear()
    minimap._map_cache.clear()
    yield
    vision.AREAS.clear()
    layout.REPORT.clear()
    minimap._map_cache.clear()


# ---------------------------------------------------------------- reading the model's boxes
def test_boxes_in_fractions_in_a_1000_scale_and_in_pixels_are_understood():
    assert llm._norm_box([0.1, 0.2, 0.5, 0.6], 1024, 576) == pytest.approx((0.1, 0.2, 0.5, 0.6))
    assert llm._norm_box([100, 200, 500, 600], 1024, 576) == pytest.approx((0.1, 0.2, 0.5, 0.6))  # 0..1000 scale
    assert llm._norm_box([512, 288, 1024, 576], 1024, 576) == pytest.approx((0.5, 0.5, 1.0, 1.0))  # pixels (max > 1000? no)
    assert llm._norm_box([512, 288, 1500, 576], 1024, 576) == pytest.approx((0.5, 0.5, 1.0, 1.0))  # pixels of the image
    assert llm._norm_box([0.5, 0.5, 0.1, 0.1], 1024, 576) == pytest.approx((0.1, 0.1, 0.5, 0.5))  # corners swapped
    assert llm._norm_box("nonsense", 1024, 576) is None
    assert llm._norm_box([0.1, 0.1, 0.1, 0.1], 1024, 576) is None  # no area


def test_the_model_is_asked_for_the_sections(server, monkeypatch):
    Fake.answer = json.dumps({"health_bar": [0.62, 0.74, 0.69, 0.76], "minimap": [800, 80, 990, 390], "chat": None})
    server["llm_enabled"] = True
    boxes = llm.analyze_layout(server, 1)
    assert boxes["health_bar"] == pytest.approx((0.62, 0.74, 0.69, 0.76))
    assert boxes["minimap"] == pytest.approx((0.8, 0.08, 0.99, 0.39))  # a 0..1000 answer
    assert "chat" not in boxes
    assert "SALUD" in Fake.requests[-1]["messages"][0]["content"]


def test_no_answer_means_none(server):
    server["llm_enabled"] = True
    Fake.answer = "I cannot see anything"
    assert llm.analyze_layout(server, 1) is None


# ---------------------------------------------------------------- judging them
def scene(monkeypatch):
    s = FakeScreen(monkeypatch, W, H)
    monkeypatch.setattr(layout, "client_rect", lambda h: (0, 0, W, H))
    monkeypatch.setattr(layout, "grab", s.grab)
    monkeypatch.setattr(minimap, "client_rect", lambda h: (0, 0, W, H))
    monkeypatch.setattr(minimap, "grab", s.grab)
    return s


def ask_with(monkeypatch, boxes):
    monkeypatch.setattr(layout.llm, "analyze_layout", lambda cfg, h: boxes)


def test_a_health_bar_the_colours_cannot_find_is_taken_from_the_model(monkeypatch):
    s = scene(monkeypatch)
    # a bar in a place the usual searches do not cover (a very odd layout): only inside the model's box
    full = int(vision.HEALTH_LEN * W)
    s.paint(int(0.62 * W), int(0.50 * H), int(0.62 * W) + full, int(0.50 * H) + 6, BRIGHT)
    monkeypatch.setattr(layout, "read_health", lambda h: None)  # the colour scan failed
    ask_with(monkeypatch, {"health_bar": (0.60, 0.48, 0.70, 0.53)})
    out = layout.analyze_and_apply({}, 1, "start")
    assert vision.HUD["bar_y"] == pytest.approx(0.503, abs=0.01)
    assert any("using y=" in l for l in out)


def test_a_wrong_box_does_not_move_the_hud(monkeypatch):
    s = scene(monkeypatch)
    monkeypatch.setattr(layout, "read_health", lambda h: None)
    ask_with(monkeypatch, {"health_bar": (0.1, 0.1, 0.2, 0.15)})  # nothing red there
    before = vision.HUD["bar_y"]
    out = layout.analyze_and_apply({}, 1, "start")
    assert vision.HUD["bar_y"] == before and any("neither" in l for l in out)


def test_when_the_colours_find_the_bar_they_win_over_the_model(monkeypatch):
    s = scene(monkeypatch)
    full = int(vision.HEALTH_LEN * W)
    s.paint(int(0.62 * W), int(0.83 * H), int(0.62 * W) + full, int(0.83 * H) + 6, BRIGHT)
    s.paint(int(0.62 * W), int(0.62 * H), int(0.62 * W) + full, int(0.62 * H) + 6, BRIGHT)  # something else that is red
    ask_with(monkeypatch, {"health_bar": (0.60, 0.60, 0.70, 0.65)})  # the model points at that
    out = layout.analyze_and_apply({}, 1, "start")
    assert vision.HUD["bar_y"] == pytest.approx(0.83, abs=0.01)
    assert any("colours win" in l for l in out)


def test_a_minimap_in_another_place_is_adopted_when_the_player_arrow_is_there(monkeypatch):
    s = scene(monkeypatch)
    s.paint(int(0.20 * W), int(0.20 * H), int(0.20 * W) + 14, int(0.20 * H) + 14, (20, 120, 240))  # the blue arrow
    ask_with(monkeypatch, {"minimap": (0.12, 0.12, 0.32, 0.42)})
    out = layout.analyze_and_apply({}, 1, "start")
    assert vision.AREAS["minimap"] == pytest.approx((0.12, 0.12, 0.20, 0.30))
    assert any("using it" in l for l in out)
    assert minimap.map_area(1)[0] == pytest.approx(0.12)


def test_the_calibrated_minimap_is_kept_when_it_works(monkeypatch):
    s = scene(monkeypatch)
    ax, ay = int(0.88 * W), int(0.2 * H)
    s.paint(ax, ay, ax + 14, ay + 14, (20, 120, 240))  # the arrow, inside the calibrated place
    ask_with(monkeypatch, {"minimap": (0.12, 0.12, 0.32, 0.42)})  # a model that is wrong
    out = layout.analyze_and_apply({}, 1, "start")
    assert "minimap" not in vision.AREAS and any("calibrated place works" in l for l in out)


def test_the_attacks_box_is_adopted_in_a_fight_when_the_digit_is_there(monkeypatch):
    s = scene(monkeypatch)
    k = W / 2000.0
    gx, gy, cw, ch = int(0.30 * W), int(0.30 * H), 14 * k / 8, 27 * k / 12
    for j, row in enumerate(vision.ATTACK_GLYPHS[2]):
        for i, c in enumerate(row):
            if c == "#":
                s.paint(gx + int(i * cw), gy + int(j * ch), gx + int((i + 1) * cw) + 1, gy + int((j + 1) * ch) + 1, ORANGE)
    monkeypatch.setattr(layout, "read_attacks", lambda h: None)
    ask_with(monkeypatch, {"attacks_box": (0.29, 0.28, 0.33, 0.36)})
    layout.analyze_and_apply({}, 1, "fight")
    assert vision.AREAS["attacks"] == pytest.approx((0.29, 0.28, 0.04, 0.08))
    assert vision.read_attacks(0) == 2  # the reader now looks there


def test_without_an_answer_the_colour_scan_stays(monkeypatch):
    scene(monkeypatch)
    ask_with(monkeypatch, None)
    out = layout.analyze_and_apply({}, 1, "start")
    assert "colour scan" in out[0] and not vision.AREAS


def test_overlap_of_boxes():
    assert layout.iou((0, 0, 1, 1), (0, 0, 1, 1)) == 1.0
    assert layout.iou((0, 0, 0.5, 0.5), (0.5, 0.5, 1, 1)) == 0.0
    assert layout.iou((0, 0, 0.6, 1), (0.4, 0, 1, 1)) == pytest.approx(0.2)


# ---------------------------------------------------------------- when it is asked
class Fighter(hunt.HuntMixin):
    def __init__(self, cfg):
        self.cfg = cfg
        self.calls = []

    def hunt_fight_loop(self, h, spot=None):
        return True


def test_the_model_is_asked_once_in_the_first_fight_only(monkeypatch):
    monkeypatch.setattr(hunt.layout, "analyze_and_apply", lambda cfg, h, phase: Fighter.calls_log.append(phase) or ["x"])
    Fighter.calls_log = []
    f = Fighter({"llm_enabled": True, "llm_layout": True})
    f.hunt_fight(1)
    f.hunt_fight(1)
    assert Fighter.calls_log == ["fight"]


def test_nothing_is_asked_when_the_helper_or_the_option_is_off(monkeypatch):
    monkeypatch.setattr(hunt.layout, "analyze_and_apply", lambda cfg, h, phase: Fighter.calls_log.append(phase) or [])
    Fighter.calls_log = []
    Fighter({"llm_enabled": False, "llm_layout": True}).hunt_fight(1)
    Fighter({"llm_enabled": True, "llm_layout": False}).hunt_fight(1)
    assert Fighter.calls_log == []
