"""The opening attack (Ctrl+A + click): how fast a missed click is noticed and how a walking bot is chased."""
from prisonbot import hunt


class Bot(hunt.HuntMixin):
    def __init__(self, fight_at=None):
        self.clock = 1000.0
        self.fight_at = fight_at  # clock time at which the fight starts (None = never)
        self.keys = []
        self.cfg = {}

    def wait(self, s):
        self.clock += s
        return True

    def hunt_say(self, t):
        pass

    def hunt_loot_leftover(self, h):
        return False

    def hunt_aim(self, h, spot):
        return spot

    def hunt_in_combat(self, h):
        on = self.fight_at is not None and self.clock >= self.fight_at
        return on, 0.05 if on else 0.0, 0.0


def setup(monkeypatch, bot, me, bots=()):
    """`me`: function(clock) -> own position."""
    monkeypatch.setattr(hunt.time, "time", lambda: bot.clock)
    monkeypatch.setattr(hunt.time, "sleep", lambda s: None)
    monkeypatch.setattr(hunt, "key_combo", lambda a, b: bot.keys.append(b))
    monkeypatch.setattr(hunt, "mouse_click", lambda b="L": bot.keys.append("click"))
    monkeypatch.setattr(hunt, "find_self", lambda h: me(bot.clock))
    monkeypatch.setattr(hunt, "find_bots", lambda h: list(bots))
    monkeypatch.setattr(hunt, "grab_minimap", lambda h: ())
    monkeypatch.setattr(hunt, "read_minimap", lambda *a: (None, []))
    monkeypatch.setattr(hunt, "snapshot", lambda *a, **k: None)
    monkeypatch.setattr(hunt.diagnostic, "save_marked", lambda *a, **k: None)
    monkeypatch.setattr(hunt.u32, "SetCursorPos", lambda x, y: None)
    monkeypatch.setattr(hunt.HuntMixin, "hunt_px", staticmethod(lambda h, p: (int(p[0] * 1000), int(p[1] * 1000))))
    monkeypatch.setattr(hunt.HuntMixin, "marked", 0)


def test_a_click_that_makes_nothing_happen_is_given_up_after_two_seconds(monkeypatch):
    b = Bot()
    setup(monkeypatch, b, me=lambda t: (0.5, 0.5))
    assert not b.hunt_attack(1, (0.3, 0.3))
    assert b.attack_quick_miss is True
    assert b.clock - 1000.0 < 3.0  # it used to wait 6.6 s
    assert b.keys.count("click") == 1


def test_a_walking_character_gets_more_time_and_chases_a_bot_that_moves_away(monkeypatch):
    b = Bot(fight_at=1012.0)
    bots = [(0.31, 0.32)]
    setup(monkeypatch, b, me=lambda t: (0.3 + (t - 1000.0) * 0.03, 0.5), bots=bots)
    assert b.hunt_attack(1, (0.3, 0.3))
    assert b.keys.count("click") >= 3  # the first click, then a new click every few seconds while it chases
    assert b.attack_quick_miss is False


def test_a_walk_that_ends_without_a_fight_is_not_a_quick_miss(monkeypatch):
    b = Bot()
    setup(monkeypatch, b, me=lambda t: (0.3 + min(t - 1000.0, 2.0) * 0.05, 0.5))  # walks for 2 s, then stops
    assert not b.hunt_attack(1, (0.3, 0.3))
    assert b.attack_quick_miss is False
    assert b.clock - 1000.0 >= 4.5  # the usual 3 s of standing still after the walk


def test_failed_attacks_save_a_marked_screenshot_a_few_times(monkeypatch):
    b = Bot()
    setup(monkeypatch, b, me=lambda t: (0.5, 0.5))
    saved = []
    monkeypatch.setattr(hunt.diagnostic, "save_marked", lambda h, name, pts: saved.append((name, pts)))
    for _ in range(12):
        b.hunt_attack(1, (0.3, 0.3))
    assert len(saved) == 8 and saved[0][0] == "no-fight" and len(saved[0][1]) == 2


class Engager(hunt.HuntMixin):
    def __init__(self, quick):
        self.attack_quick_miss = quick
        self.approached = 0
        self.tried = []

    def hunt_attack(self, h, spot, variant=0):
        self.tried.append(variant)
        return False

    def alive(self):
        return True

    def hunt_say(self, t):
        pass

    def hunt_approach(self, h, bot):
        self.approached += 1
        return True


def test_after_a_quick_miss_it_clicks_again_without_walking_first(monkeypatch):
    monkeypatch.setattr(hunt, "find_bots", lambda h: [(0.5, 0.5)])
    monkeypatch.setattr(hunt, "find_self", lambda h: (0.4, 0.8))
    e = Engager(quick=True)
    assert not e.hunt_engage(1, (0.5, 0.5))
    assert len(e.tried) == 4 and e.approached == 1  # steps 0 and 1 skip the walk; step 2 walks; step 3 is the last try


def test_a_refused_click_still_walks_closer_first(monkeypatch):
    monkeypatch.setattr(hunt, "find_bots", lambda h: [(0.5, 0.5)])
    monkeypatch.setattr(hunt, "find_self", lambda h: (0.4, 0.8))
    e = Engager(quick=False)
    e.hunt_engage(1, (0.5, 0.5))
    assert e.approached == 3
