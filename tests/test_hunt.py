from prisonbot import hunt


class Bot(hunt.HuntMixin):
    def __init__(self):
        self.moves = []

    def hunt_move(self, h, fx, fy):
        self.moves.append((fx, fy))


def patch(monkeypatch, bots, bars, works=lambda n: True, me=None):
    """works(n): did the n-th click (1-based) produce a new chat line?"""
    clicks = []
    monkeypatch.setattr(hunt, "find_bots", lambda h: bots)
    monkeypatch.setattr(hunt, "find_bars", lambda h: bars)
    monkeypatch.setattr(hunt, "mouse_click", lambda b="L": clicks.append(b))
    monkeypatch.setattr(hunt, "find_self", lambda h: me)
    monkeypatch.setattr(hunt, "grab_chat", lambda h: b"")
    monkeypatch.setattr(hunt, "changed", lambda a, b, **k: bool(clicks) and works(len(clicks)))
    monkeypatch.setattr(hunt.time, "sleep", lambda s: None)
    return clicks


def test_manual_attack_clicks_the_label_bot(monkeypatch):
    clicks = patch(monkeypatch, [(0.4, 0.3)], [])
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


def test_manual_attack_tries_the_next_candidate_when_the_click_did_nothing(monkeypatch):
    clicks = patch(monkeypatch, [(0.2, 0.7)], [(0.5, 0.3)], works=lambda n: n >= 2)
    b = Bot()
    assert b.hunt_manual_attack(1, (0.5, 0.3))
    assert b.moves == [(0.5, 0.3), (0.2, 0.7)] and len(clicks) == 2


def test_manual_attack_fails_when_no_click_has_an_effect(monkeypatch):
    clicks = patch(monkeypatch, [(0.2, 0.7)], [(0.5, 0.3)], works=lambda n: False)
    assert not Bot().hunt_manual_attack(1, None)
    assert len(clicks) == 6  # 2 candidates + 4 shifted clicks around the nearest


def test_label_and_bar_of_the_same_bot_are_one_candidate(monkeypatch):
    clicks = patch(monkeypatch, [(0.47, 0.29)], [(0.475, 0.292)], works=lambda n: False)
    Bot().hunt_manual_attack(1, None)
    assert len(clicks) == 6  # one candidate, then its five shifted variants


def test_second_attack_keeps_hitting_the_first_bot(monkeypatch):
    patch(monkeypatch, [(0.47, 0.39), (0.35, 0.33)], [])
    b = Bot()
    b.hunt_manual_attack(1, None)  # nearest to the centre: (0.47, 0.39)
    b.hunt_manual_attack(1, None)
    assert b.moves == [(0.47, 0.39), (0.47, 0.39)]


def test_own_character_is_never_a_candidate(monkeypatch):
    patch(monkeypatch, [], [(0.566, 0.546), (0.47, 0.39)], me=(0.566, 0.43))  # own body = label + BODY_DROP
    b = Bot()
    b.hunt_manual_attack(1, None)
    assert b.moves == [(0.47, 0.39)]


def test_seg_dist():
    assert hunt.HuntMixin.seg_dist((0.5, 0.5), (0, 0), (1, 0)) == 0.5
    assert hunt.HuntMixin.seg_dist((2, 0), (0, 0), (1, 0)) == 1.0


def test_health_bars_are_tried_before_name_labels(monkeypatch):
    patch(monkeypatch, [(0.5, 0.5)], [(0.2, 0.2)], works=lambda n: True)  # the label is nearer to the centre
    b = Bot()
    b.hunt_manual_attack(1, None)
    assert b.moves == [(0.2, 0.2)]


def test_the_bot_hit_first_stays_the_target_even_if_only_its_label_is_seen(monkeypatch):
    # the bar of the first bot is hidden, the other bot's bar shows: the label next to the last hit still wins
    patch(monkeypatch, [(0.53, 0.076)], [(0.472, 0.204)])
    b = Bot()
    b.fight_spot = (0.476, 0.192)
    b.hunt_manual_attack(1, None)
    assert b.moves == [(0.472, 0.204)]


def test_a_shifted_click_is_tried_when_the_lone_bot_is_missed(monkeypatch):
    # one candidate whose centre does nothing (diamond room: the feet are what counts)
    clicks = patch(monkeypatch, [], [(0.42, 0.574)], works=lambda n: n >= 3)
    b = Bot()
    assert b.hunt_manual_attack(1, None)
    assert len(clicks) == 3 and b.moves[0] == (0.42, 0.574) and b.moves[2] != b.moves[0]
    assert b.fight_spot == b.moves[2]


def test_the_last_hit_spot_is_clicked_when_no_bot_is_seen(monkeypatch):
    clicks = patch(monkeypatch, [], [])
    b = Bot()
    b.fight_spot = (0.52, 0.10)
    assert b.hunt_manual_attack(1, None)
    assert b.moves == [(0.52, 0.10)] and clicks == ["L"]
