import itertools

import pytest

from prisonbot import hunt


class Bot(hunt.HuntMixin):
    pass


def fake_scans(monkeypatch, positions, step=0.3):
    """find_bots answers with the next position each time; the clock advances `step` s per call."""
    it = iter(positions)
    clock = itertools.count(0, step)
    monkeypatch.setattr(hunt, "find_bots", lambda h: [next(it)] if True else [])
    monkeypatch.setattr(hunt.time, "time", lambda: next(clock) / 2)  # two time() calls per scan


def test_standing_bot_is_clicked_where_it_is(monkeypatch):
    fake_scans(monkeypatch, [(0.5, 0.4), (0.5, 0.4)])
    p = Bot().hunt_aim(1, (0.5, 0.4))
    assert p == pytest.approx((0.5, 0.4), abs=0.001)


def test_walking_bot_is_aimed_ahead(monkeypatch):
    fake_scans(monkeypatch, [(0.50, 0.4), (0.53, 0.4)])
    p = Bot().hunt_aim(1, (0.5, 0.4))
    assert p[0] > 0.53 and p[0] <= 0.53 + Bot.MAX_LEAD + 1e-9
    assert p[1] == pytest.approx(0.4, abs=0.001)


def test_lead_is_capped(monkeypatch):
    fake_scans(monkeypatch, [(0.40, 0.4), (0.60, 0.4)])
    p = Bot().hunt_aim(1, (0.45, 0.4))
    assert p[0] - 0.60 <= Bot.MAX_LEAD + 1e-9


def test_bot_not_seen_keeps_the_old_spot(monkeypatch):
    monkeypatch.setattr(hunt, "find_bots", lambda h: [])
    assert Bot().hunt_aim(1, (0.5, 0.4)) == (0.5, 0.4)


def test_only_the_bot_near_the_spot_counts(monkeypatch):
    monkeypatch.setattr(hunt, "find_bots", lambda h: [(0.9, 0.9)])
    assert Bot().hunt_aim(1, (0.5, 0.4)) == (0.5, 0.4)
