from prisonbot import hunt


class Bot(hunt.HuntMixin):
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0
        self.cfg = {"loot_command": "/loot"}

    def wait(self, s):
        return True

    def hunt_loot_once(self, h):
        self.calls += 1
        return self.results.pop(0) if self.results else False


def test_loot_is_sent_again_after_an_emptied_window():
    b = Bot([True, False])  # first corpse looted, then /loot finds nothing
    b.hunt_loot(1)
    assert b.calls == 2


def test_loot_stops_at_once_when_no_window_opens():
    b = Bot([False])
    b.hunt_loot(1)
    assert b.calls == 1


def test_loot_repeat_is_capped():
    b = Bot([True] * 10)
    b.hunt_loot(1)
    assert b.calls == 4


def test_extra_delay_before_the_second_loot(monkeypatch):
    waits = []
    b = Bot([True, False])
    b.cfg["loot_again_delay"] = 2.0
    b.wait = lambda s: waits.append(s) or True
    b.hunt_loot(1)
    assert waits == [2.0]


def test_leftover_window_is_emptied(monkeypatch):
    taken = []
    b = Bot([])
    b.hunt_say = lambda t: None
    b.hunt_loot_items = lambda h, top: taken.append(top) or True
    monkeypatch.setattr(hunt, "find_loot", lambda h: 0.33)
    assert b.hunt_loot_leftover(1)
    assert taken == [0.33]


def test_no_leftover_window_means_nothing_to_do(monkeypatch):
    b = Bot([])
    monkeypatch.setattr(hunt, "find_loot", lambda h: None)
    assert not b.hunt_loot_leftover(1)
