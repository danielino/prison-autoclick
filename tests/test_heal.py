from conftest import blank, paint
from prisonbot import heal


def test_text_state_white_red_and_none():
    w, h = 150, 34
    white = blank(w, h, (20, 20, 20))
    paint(white, w, 10, 10, 100, 24, (250, 250, 250))
    red = blank(w, h, (20, 20, 20))
    paint(red, w, 10, 10, 100, 24, (230, 20, 20))
    assert heal.heal_text_state(white, w, h) == "white"
    assert heal.heal_text_state(red, w, h) == "red"
    assert heal.heal_text_state(blank(w, h, (20, 20, 20)), w, h) is None


class FakeApp(heal.HealMixin):
    def __init__(self, states, item=(0.1, 0.5)):
        self.cfg = {"heal_item": item}
        self.states = list(states)
        self.log = []

    def hunt_move(self, h, fx, fy):
        self.log.append(("move", (fx, fy)))

    def hunt_say(self, t):
        pass

    def wait(self, s):
        return True

    def heal_state(self, h):
        return self.states.pop(0) if self.states else None


def setup(monkeypatch, app, health=(0.4, 0.95)):
    hp = list(health)
    monkeypatch.setattr(heal, "read_health", lambda h: hp.pop(0) if len(hp) > 1 else hp[0])
    monkeypatch.setattr(heal, "key_combo", lambda *k: app.log.append(("keys", k)))
    monkeypatch.setattr(heal, "mouse_click", lambda b="L": app.log.append(("click", b)))
    monkeypatch.setattr(heal, "_area", lambda h, r: (b"", 0, 0))
    monkeypatch.setattr(heal, "changed", lambda *a, **k: True)
    monkeypatch.setattr(heal.time, "sleep", lambda s: None)


def moves(app):
    return [p for kind, p in app.log if kind == "move"]


def test_heal_presses_plus_until_red_then_minus_then_ok(monkeypatch):
    # reads: dialog seen, initial text, then after each +: white, red
    app = FakeApp(["white", "white", "white", "red"])
    setup(monkeypatch, app)
    assert app.hunt_heal(1)
    seq = [p for p in moves(app)[1:]]  # the first move is the food item
    assert seq == [heal.BTN_PLUS, heal.BTN_PLUS, heal.BTN_MINUS, heal.BTN_OK]
    keys = [k for kind, k in app.log if kind == "keys"]
    assert keys == [(0x1D, 0x02), (0x1D, 0x02)]  # opened and closed the sheet


def test_heal_double_clicks_the_food(monkeypatch):
    app = FakeApp(["red"])
    setup(monkeypatch, app)
    app.hunt_heal(1)
    assert app.log[:4][1:] == [("move", (0.1, 0.5)), ("click", "L"), ("click", "L")]


def test_heal_cancels_when_one_portion_is_already_too_much(monkeypatch):
    app = FakeApp(["red", "red"])
    setup(monkeypatch, app)
    assert not app.hunt_heal(1)
    assert heal.BTN_CANCEL in moves(app) and heal.BTN_OK not in moves(app)


def test_heal_does_nothing_without_a_saved_food(monkeypatch):
    app = FakeApp([], item=None)
    setup(monkeypatch, app)
    assert not app.hunt_heal(1)
    assert app.log == []
