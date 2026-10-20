from prisonbot import hunt


class Bot(hunt.HuntMixin):
    def __init__(self):
        self.moves = []

    def hunt_move(self, h, fx, fy):
        self.moves.append((fx, fy))


def patch(monkeypatch, bots, bars):
    clicks = []
    monkeypatch.setattr(hunt, "find_bots", lambda h: bots)
    monkeypatch.setattr(hunt, "find_bars", lambda h: bars)
    monkeypatch.setattr(hunt, "mouse_click", lambda b="L": clicks.append(b))
    monkeypatch.setattr(hunt.time, "sleep", lambda s: None)
    return clicks


def test_manual_attack_clicks_the_label_bot(monkeypatch):
    clicks = patch(monkeypatch, [(0.4, 0.3)], [(0.9, 0.9)])
    b = Bot()
    assert b.hunt_manual_attack(1, None)
    assert b.moves == [(0.4, 0.3)] and clicks == ["L"]


def test_manual_attack_falls_back_to_the_health_bar(monkeypatch):
    clicks = patch(monkeypatch, [], [(0.47, 0.29)])
    b = Bot()
    assert b.hunt_manual_attack(1, None)  # a fight the bot started: there is no known spot
    assert b.moves == [(0.47, 0.29)] and clicks == ["L"]


def test_manual_attack_uses_the_known_spot_when_nothing_is_visible(monkeypatch):
    clicks = patch(monkeypatch, [], [])
    b = Bot()
    assert b.hunt_manual_attack(1, (0.5, 0.4))
    assert b.moves == [(0.5, 0.4)] and clicks == ["L"]


def test_manual_attack_reports_failure_when_there_is_nothing_to_click(monkeypatch):
    clicks = patch(monkeypatch, [], [])
    b = Bot()
    assert not b.hunt_manual_attack(1, None)
    assert clicks == []


def test_manual_attack_picks_the_bot_nearest_to_the_spot(monkeypatch):
    patch(monkeypatch, [(0.2, 0.3), (0.7, 0.3)], [])
    b = Bot()
    b.hunt_manual_attack(1, (0.65, 0.3))
    assert b.moves == [(0.7, 0.3)]


def test_seg_dist():
    assert hunt.HuntMixin.seg_dist((0.5, 0.5), (0, 0), (1, 0)) == 0.5
    assert hunt.HuntMixin.seg_dist((2, 0), (0, 0), (1, 0)) == 1.0
