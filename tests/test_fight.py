from prisonbot import hunt


class Fight(hunt.HuntMixin):
    """hunt_fight with a scripted screen: `turns` gives the turn-button fraction on every look (None = no combat)."""

    def __init__(self, turns, hp):
        self.turns, self.hp = list(turns), hp
        self.events = []
        self.cfg = {"repeat_interval": 5.0}
        self.clock = 1000.0

    def wait(self, s):
        self.clock += 6.0  # longer than the minimum pause between commands
        return True

    def hunt_in_combat(self, h):
        ft = self.turns.pop(0) if self.turns else None
        return ft is not None, 0.05, ft or 0.0

    def hunt_say(self, t):
        pass

    def hunt_manual_attack(self, h, spot):
        self.events.append("A")
        return True


def run(monkeypatch, turns, hp, attacks=()):
    """`attacks`: what the ATAQUES number of the HUD shows on each read (None once the list is used up)."""
    f = Fight(turns, hp)
    reads = iter(attacks)
    monkeypatch.setattr(hunt, "read_attacks", lambda h: next(reads, None))
    monkeypatch.setattr(hunt.time, "time", lambda: f.clock)
    monkeypatch.setattr(hunt, "read_health", lambda h: f.hp)
    monkeypatch.setattr(hunt, "key_combo", lambda a, b: f.events.append({0x14: "T", 0x13: "R"}[b]))
    assert f.hunt_fight(1)
    return "".join(f.events)


MINE, OTHER = 0.012, 0.0


def test_healthy_fight_two_attacks_then_end_turn_then_repeat(monkeypatch):
    # my turn x3 (two attacks, then Ctrl+T), the bot plays, my turn again (Ctrl+R), fight over
    assert run(monkeypatch, [MINE, MINE, MINE, OTHER, MINE, None, None, None], hp=0.9) == "AATR"


def test_below_half_health_a_turn_with_three_attacks_is_played_by_hand(monkeypatch):
    # the third attack is only in the hand-played turn: Ctrl+R repeats that one afterwards
    events = run(monkeypatch, [MINE, MINE, MINE, MINE, OTHER, MINE, None, None, None], hp=0.4)
    assert events == "AAATR"


def test_three_attack_turn_is_played_only_once(monkeypatch):
    # (two "other" looks after Ctrl+R: that is how the program sees that the repeat passed the turn)
    events = run(monkeypatch, [MINE] * 4 + [OTHER, MINE, OTHER, OTHER, MINE, None, None, None], hp=0.4)
    assert events == "AAATRR"


def test_health_dropping_under_half_in_a_later_turn_triggers_it(monkeypatch):
    f = Fight([MINE, MINE, MINE, OTHER, MINE, OTHER, MINE, MINE, MINE, MINE, OTHER, MINE, None, None, None], 0.9)
    monkeypatch.setattr(hunt.time, "time", lambda: f.clock)
    levels = iter([0.9, 0.9, 0.9, 0.9, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4])
    monkeypatch.setattr(hunt, "read_health", lambda h: next(levels, 0.4))
    monkeypatch.setattr(hunt, "key_combo", lambda a, b: f.events.append({0x14: "T", 0x13: "R"}[b]))
    assert f.hunt_fight(1)
    ev = "".join(f.events)
    assert ev.startswith("AATR") and "AAAT" in ev


def test_hud_with_three_attacks_plays_all_three_then_ends_the_turn(monkeypatch):
    # healthy (no hint from the health), but the HUD says 3: read at the start, then after every attack
    events = run(monkeypatch, [MINE] * 4 + [OTHER, OTHER, MINE, None, None, None], hp=0.9,
                 attacks=[3, 2, 2, 1, 1, 0, 0])
    assert events == "AAAT" + "R"  # then the next turn is repeated with Ctrl+R


def test_hud_with_two_attacks_leaves_it_to_ctrl_r_afterwards(monkeypatch):
    events = run(monkeypatch, [MINE] * 3 + [OTHER, OTHER, MINE, None, None, None], hp=0.9,
                 attacks=[2, 1, 1, 0, 0])
    assert events == "AAT" + "R"


def test_hud_attacks_at_zero_ends_the_turn_even_if_our_count_says_more(monkeypatch):
    events = run(monkeypatch, [MINE, MINE, OTHER, OTHER, None, None, None], hp=0.9, attacks=[2, 0, 0])
    assert events == "AT"


def test_three_attacks_on_a_later_ctrl_r_turn_trigger_one_manual_turn(monkeypatch):
    # turn 1: 2 attacks by hand + Ctrl+T; turn 2 shows ATAQUES 3 (health fell below 50%): by hand again with three
    events = run(monkeypatch,
                 [MINE, MINE, MINE, OTHER, OTHER, MINE, MINE, MINE, MINE, OTHER, OTHER, None, None, None], hp=0.9,
                 attacks=[2, 1, 1, 0, 0, 3, 2, 2, 1, 1, 0, 0])
    assert events.startswith("AAT") and "AAAT" in events
