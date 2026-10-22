import pytest

from prisonbot import hunt, stats
from test_hunt import Bot, patch


@pytest.fixture(autouse=True)
def fresh():
    stats.stop()
    stats.reset()
    yield
    stats.stop()
    stats.reset()


def test_counters_and_average(monkeypatch):
    stats.add("fights_done", 2)
    stats.add("fight_seconds", 90)
    assert stats.get("fights_done") == 2 and stats.value("fight_avg") == 45
    assert stats.value("nothing_yet") == 0


def test_time_counts_only_while_hunting(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(stats.time, "time", lambda: now[0])
    stats.start()
    now[0] += 120
    stats.stop()
    now[0] += 500  # not hunting
    assert stats.seconds() == 120
    stats.start()
    now[0] += 30
    assert stats.seconds() == 150
    assert stats.clock(3725) == "1:02:05"


def test_the_summary_goes_to_the_log_at_the_interval(monkeypatch):
    now = [1000.0]
    lines = []
    monkeypatch.setattr(stats.time, "time", lambda: now[0])
    monkeypatch.setattr(stats, "log", lines.append)
    stats.start()
    stats.add("fights_done")
    stats.tick({"stats_interval": 5})
    assert lines == []
    now[0] += 301
    stats.tick({"stats_interval": 5})
    assert len(lines) == 1 and lines[0].startswith("STATS session 0:05:01") and "fights 1" in lines[0]
    stats.tick({"stats_interval": 5})
    assert len(lines) == 1  # not again until the next interval
    now[0] += 1000
    stats.tick({"stats_interval": 0})
    assert len(lines) == 1  # 0 = never


def test_rows_have_rates_per_hour(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(stats.time, "time", lambda: now[0])
    stats.start()
    stats.add("fights_done", 10)
    now[0] += 1800  # half an hour
    flat = {label: (v, r) for _, items in stats.rows() for label, v, r in items}
    assert flat["Fights finished"] == ("10", "20.0")


def test_reset_clears_the_counters(monkeypatch):
    stats.add("heals", 3)
    stats.reset()
    assert stats.get("heals") == 0


def test_an_attack_by_hand_is_counted_and_logged_with_the_bot_and_its_health(monkeypatch):
    patch(monkeypatch, [], [(0.34, 0.14), (0.47, 0.27)])
    monkeypatch.setattr(hunt, "LAST_BARS", [((0.34, 0.14), 0.97), ((0.47, 0.27), 0.19)])
    lines = []
    monkeypatch.setattr(hunt, "log", lines.append)
    Bot().hunt_manual_attack(1, None)
    action = [l for l in lines if "ACTION attack #1 by hand" in l]
    assert len(action) == 1
    assert "on the bot at (0.470,0.270)" in action[0] and "health 19%" in action[0] and "(0.340,0.140) 97%" in action[0]
    assert stats.get("attacks_manual") == 1


def test_missed_clicks_are_counted(monkeypatch):
    patch(monkeypatch, [], [(0.47, 0.27)], works=lambda n: n >= 3)
    Bot().hunt_manual_attack(1, None)
    assert stats.get("attack_misses") == 2 and stats.get("attacks_manual") == 1
