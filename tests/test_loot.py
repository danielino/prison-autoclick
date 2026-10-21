from prisonbot import hunt


class Bot(hunt.HuntMixin):
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0
        self.cfg = {"loot_command": "/loot"}

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
