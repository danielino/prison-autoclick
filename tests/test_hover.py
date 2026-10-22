"""Never click on a door or an exit: the pointer rests on the spot first and a label that appears (the game names doors and
exits under the pointer) stops the click."""
import pytest

from conftest import blank, paint
from prisonbot import hunt, llm

W, H = 2000, 1000


@pytest.fixture(autouse=True)
def forget_spots():
    hunt.HuntMixin.hover_memo.clear()
    yield
    hunt.HuntMixin.hover_memo.clear()


class Bot(hunt.HuntMixin):
    HOVER_WAIT = 0.0

    def __init__(self, label_near=None):
        self.cfg = {}
        self.moves = []
        self.label_near = label_near  # a function(point) -> True if a label shows when the pointer rests there
        self.at = None

    def hunt_move(self, h, fx, fy):
        self.moves.append((fx, fy))
        self.at = (fx, fy)

    def hunt_say(self, t):
        pass


def screen(monkeypatch, bot):
    """grab(): a dark scene; once the pointer rests on a 'door' spot, a white text block shows above it."""
    monkeypatch.setattr(hunt, "client_rect", lambda h: (0, 0, W, H))
    monkeypatch.setattr(hunt.time, "sleep", lambda s: None)
    monkeypatch.setattr(hunt, "snapshot", lambda *a, **k: None)

    def grab(x, y, w, h):
        buf = blank(w, h, (60, 60, 60))
        paint(buf, w, 0, 0, 60, 8, (255, 255, 255))  # something white that is always there (a sign), not new
        if bot.at and bot.label_near and bot.label_near(bot.at):
            px, py = int(bot.at[0] * W) - x, int(bot.at[1] * H) - y
            for row in range(3):  # three lines of big white text above the pointer
                x0, x1 = max(px - 90, 0), min(px + 90, w)
                y0, y1 = max(py - 100 + row * 22, 0), min(py - 100 + row * 22 + 14, h)
                if x0 < x1 and y0 < y1:
                    paint(buf, w, x0, y0, x1, y1, (255, 255, 255))
        return bytes(buf)
    monkeypatch.setattr(hunt, "grab", grab)


DOOR = lambda p: abs(p[0] - 0.7) < 0.06 and abs(p[1] - 0.3) < 0.06


def test_a_label_under_the_pointer_is_detected(monkeypatch):
    b = Bot(DOOR)
    screen(monkeypatch, b)
    found, n = b.hunt_hover_label(1, (0.7, 0.3))
    assert found and n > 500
    assert b.moves == [(0.7, 0.3)]  # the pointer went there, and nothing was clicked


def test_plain_floor_and_always_visible_labels_are_not_a_door(monkeypatch):
    b = Bot(DOOR)
    screen(monkeypatch, b)
    assert b.hunt_hover_label(1, (0.3, 0.7))[0] is False


def test_hover_ok_refuses_a_door_and_counts_it(monkeypatch):
    from prisonbot import stats
    stats.reset()
    b = Bot(DOOR)
    screen(monkeypatch, b)
    assert b.hunt_hover_ok(1, (0.3, 0.7), "attack") is True
    assert b.hunt_hover_ok(1, (0.7, 0.3), "attack") is False
    assert stats.get("clicks_refused") == 1


def test_the_vision_model_can_clear_a_label_that_is_a_character(monkeypatch):
    b = Bot(DOOR)
    b.cfg = {"llm_enabled": True}
    screen(monkeypatch, b)
    monkeypatch.setattr(hunt.llm, "active", lambda cfg: True)
    monkeypatch.setattr(hunt.llm, "read_hover", lambda cfg, h, p: ("Wild Dog paria", False))
    assert b.hunt_hover_ok(1, (0.7, 0.3)) is True


def test_the_vision_model_confirms_an_exit(monkeypatch):
    b = Bot(DOOR)
    b.cfg = {"llm_enabled": True}
    screen(monkeypatch, b)
    monkeypatch.setattr(hunt.llm, "active", lambda cfg: True)
    monkeypatch.setattr(hunt.llm, "read_hover", lambda cfg, h, p: ("CELDAS DE SEGURIDAD NORESTE", True))
    assert b.hunt_hover_ok(1, (0.7, 0.3)) is False


def test_a_model_that_does_not_answer_leaves_the_refusal(monkeypatch):
    b = Bot(DOOR)
    b.cfg = {"llm_enabled": True}
    screen(monkeypatch, b)
    monkeypatch.setattr(hunt.llm, "active", lambda cfg: True)
    monkeypatch.setattr(hunt.llm, "read_hover", lambda cfg, h, p: None)
    assert b.hunt_hover_ok(1, (0.7, 0.3)) is False


# ---------------------------------------------------------------- the attack and the walk
class Attacker(Bot):
    def __init__(self, label_near):
        super().__init__(label_near)
        self.clicks = 0
        self.keys = []

    def hunt_loot_leftover(self, h):
        return False

    def hunt_aim(self, h, spot, lead=None):
        return spot


def test_the_attack_is_not_made_on_a_door(monkeypatch):
    b = Attacker(DOOR)
    screen(monkeypatch, b)
    monkeypatch.setattr(hunt, "key_combo", lambda a, c: b.keys.append(c))
    monkeypatch.setattr(hunt, "mouse_click", lambda *a: setattr(b, "clicks", b.clicks + 1))
    assert not b.hunt_attack(1, (0.7, 0.3 - 0.02))  # the bot stands next to the door: the aim point is on it
    assert b.clicks == 0 and b.keys == []  # no Ctrl+A, no click
    assert b.attack_refused is True and b.attack_quick_miss is True


def test_the_walk_towards_a_bot_picks_a_point_without_a_label(monkeypatch):
    b = Bot(lambda p: abs(p[0] - 0.55) < 0.04 and abs(p[1] - 0.6) < 0.08)  # the first point (60% of the way) is a door
    screen(monkeypatch, b)
    clicks = []
    monkeypatch.setattr(hunt, "find_self", lambda h: (0.5, 0.2))
    monkeypatch.setattr(hunt, "mouse_click", lambda *a: clicks.append(b.at))
    monkeypatch.setattr(hunt.HuntMixin, "wait", lambda self, s: True, raising=False)
    b.wait = lambda s: True
    b.hunt_approach(1, (0.6, 0.7))
    assert len(clicks) == 1 and not DOOR(clicks[0]) and abs(clicks[0][0] - 0.55) > 0.0  # one click, on a clean point
    assert len(b.moves) >= 2  # it looked at more than one point first


def test_the_walk_is_not_made_when_every_point_has_a_label(monkeypatch):
    b = Bot(lambda p: True)
    screen(monkeypatch, b)
    clicks = []
    monkeypatch.setattr(hunt, "find_self", lambda h: (0.5, 0.2))
    monkeypatch.setattr(hunt, "mouse_click", lambda *a: clicks.append(1))
    b.wait = lambda s: True
    assert b.hunt_approach(1, (0.6, 0.7)) is False
    assert clicks == []


def test_read_hover_reads_the_label_with_the_model(monkeypatch):
    monkeypatch.setattr(llm, "active", lambda cfg: True)
    monkeypatch.setattr(llm, "screen_png", lambda h, cfg, points=(), area=None: b"png")
    monkeypatch.setattr(llm, "ask", lambda cfg, prompt, png, kind="q": {"text": "SALIDA", "is_exit": "true"})
    monkeypatch.setattr(llm, "log", lambda m: None)
    assert llm.read_hover({}, 1, (0.5, 0.5)) == ("SALIDA", True)
    monkeypatch.setattr(llm, "ask", lambda cfg, prompt, png, kind="q": {"text": "Wild Dog", "is_exit": False})
    assert llm.read_hover({}, 1, (0.5, 0.5)) == ("Wild Dog", False)
    monkeypatch.setattr(llm, "ask", lambda cfg, prompt, png, kind="q": None)
    assert llm.read_hover({}, 1, (0.5, 0.5)) is None


def test_a_refused_spot_stays_refused_without_waiting_again(monkeypatch):
    b = Bot(DOOR)
    screen(monkeypatch, b)
    assert b.hunt_hover_ok(1, (0.7, 0.3)) is False
    moves = len(b.moves)
    assert b.hunt_hover_ok(1, (0.701, 0.301)) is False  # the same spot (within 2%): no new look
    assert len(b.moves) == moves


def test_a_clean_spot_is_not_checked_twice_in_a_row(monkeypatch):
    b = Bot(DOOR)
    screen(monkeypatch, b)
    assert b.hunt_hover_ok(1, (0.3, 0.7)) is True
    moves = len(b.moves)
    assert b.hunt_hover_ok(1, (0.3, 0.7)) is True
    assert len(b.moves) == moves


# ---------------------------------------------------------------- doors learned from a zone change
class Learner(Bot):
    def __init__(self):
        super().__init__(None)
        self.cfg = {}
        self.zone0 = "map-A"


def test_the_last_clicks_are_remembered_as_doors_when_the_zone_changes(monkeypatch):
    saved = []
    monkeypatch.setattr(hunt, "save", lambda cfg: saved.append(1))
    b = Learner()
    b.note_click((0.2, 0.2))
    b.note_click((0.65, 0.3))
    b.note_click((0.7, 0.31))
    b.remember_doors("map-A")
    assert [(s["x"], s["y"]) for s in b.cfg["door_spots"]] == [(0.2, 0.2), (0.65, 0.3), (0.7, 0.31)] and saved


def test_old_clicks_are_not_blamed(monkeypatch):
    monkeypatch.setattr(hunt, "save", lambda cfg: None)
    b = Learner()
    now = [1000.0]
    monkeypatch.setattr(hunt.time, "time", lambda: now[0])
    b.note_click((0.2, 0.2))
    now[0] += 120
    b.remember_doors("map-A")
    assert "door_spots" not in b.cfg


def test_a_remembered_door_is_refused_in_that_zone_only(monkeypatch):
    b = Learner()
    b.cfg = {"door_spots": [{"map": "map-A", "x": 0.7, "y": 0.31}]}
    monkeypatch.setattr(hunt, "zone_differs", lambda a, b_: 0.0 if a == b_ else 0.9)
    screen(monkeypatch, b)
    assert b.hunt_hover_ok(1, (0.71, 0.3)) is False  # next to the door, in the same zone
    assert b.moves == []  # refused without even moving the pointer
    assert b.hunt_hover_ok(1, (0.3, 0.7)) is True  # elsewhere in the zone
    b.zone0 = "map-B"
    hunt.HuntMixin.hover_memo.clear()
    assert b.hunt_hover_ok(1, (0.71, 0.3)) is True  # another zone: the spot means nothing
