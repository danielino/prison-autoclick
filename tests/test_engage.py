from prisonbot import hunt


class Bot(hunt.HuntMixin):
    def __init__(self, works_on):
        self.works_on = works_on
        self.tried = []

    def hunt_attack(self, h, spot, variant=0):
        self.tried.append(variant)
        return variant == self.works_on

    def alive(self):
        return True

    def hunt_approach(self, h, bot):
        return True


def test_engage_tries_another_aim_point_on_each_retry(monkeypatch):
    monkeypatch.setattr(hunt, "find_bots", lambda h: [])
    b = Bot(works_on=2)
    assert b.hunt_engage(1, (0.5, 0.5))
    assert b.tried == [0, 1, 2]


def test_working_variant_is_tried_first_next_time(monkeypatch):
    monkeypatch.setattr(hunt, "find_bots", lambda h: [])
    b = Bot(works_on=2)
    b.hunt_engage(1, (0.5, 0.5))
    b.tried.clear()
    assert b.hunt_engage(1, (0.5, 0.5))
    assert b.tried == [2]


def test_engage_gives_up_after_four_steps(monkeypatch):
    monkeypatch.setattr(hunt, "find_bots", lambda h: [])
    b = Bot(works_on=99)
    assert not b.hunt_engage(1, (0.5, 0.5))
    assert len(b.tried) == 4
