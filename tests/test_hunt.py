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


def test_manual_attack_tries_the_next_candidate_after_shifting_the_first(monkeypatch):
    clicks = patch(monkeypatch, [(0.2, 0.7)], [(0.5, 0.3)], works=lambda n: n >= 5)
    b = Bot()
    assert b.hunt_manual_attack(1, (0.5, 0.3))
    assert b.moves[0] == (0.5, 0.3) and b.moves[-1] == (0.2, 0.7) and len(clicks) == 5


def test_manual_attack_fails_when_no_click_has_an_effect(monkeypatch):
    clicks = patch(monkeypatch, [(0.2, 0.7)], [(0.5, 0.3)], works=lambda n: False)
    assert not Bot().hunt_manual_attack(1, None)
    assert len(clicks) == 5  # four clicks around the chosen bot, then the other one


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


def test_a_new_target_is_the_bot_with_the_least_health(monkeypatch):
    patch(monkeypatch, [], [(0.34, 0.14), (0.47, 0.27), (0.53, 0.11)])
    monkeypatch.setattr(hunt, "LAST_BARS", [((0.34, 0.14), 0.97), ((0.47, 0.27), 0.19), ((0.53, 0.11), 0.99)])
    b = Bot()
    b.hunt_manual_attack(1, (0.34, 0.14))  # the opening attack was on the full one on the left
    assert b.moves == [(0.47, 0.27)]
    assert b.fight_spot == (0.47, 0.27)


def test_the_weakest_bot_stays_the_target_until_it_dies_then_the_next_weakest(monkeypatch):
    patch(monkeypatch, [], [(0.34, 0.14), (0.47, 0.27), (0.53, 0.11)])
    monkeypatch.setattr(hunt, "LAST_BARS", [((0.34, 0.14), 0.97), ((0.47, 0.27), 0.19), ((0.53, 0.11), 0.9)])
    b = Bot()
    b.hunt_manual_attack(1, None)
    b.hunt_manual_attack(1, None)
    assert b.moves == [(0.47, 0.27)] * 2
    # it dies: its bar is gone, the other two are far away
    patch(monkeypatch, [], [(0.34, 0.14), (0.53, 0.11)])
    monkeypatch.setattr(hunt, "LAST_BARS", [((0.34, 0.14), 0.97), ((0.53, 0.11), 0.9)])
    b.hunt_manual_attack(1, None)
    assert b.moves[-1] == (0.53, 0.11)


def test_a_missed_click_is_shifted_on_the_same_bot_before_trying_another(monkeypatch):
    # the body point under the bar of the weak bot does not register (the feet do): never fall to the full bot on the right
    patch(monkeypatch, [], [(0.47, 0.25), (0.53, 0.08)], works=lambda n: n == 4)
    monkeypatch.setattr(hunt, "LAST_BARS", [((0.47, 0.25), 0.36), ((0.53, 0.08), 1.0)])
    b = Bot()
    assert b.hunt_manual_attack(1, None)
    assert all(abs(p[0] - 0.47) < 0.05 for p in b.moves) and len(b.moves) == 4
    assert b.manual_pref == 3  # (0, +0.045): the feet; the next attack starts there
    b.hunt_manual_attack(1, None)
    assert b.moves[4] == (0.47, 0.25 + 0.045)