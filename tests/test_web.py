"""The live web page: state published by the bot, the server and its event stream."""
import http.client
import json
import time

import pytest

from prisonbot import config, live, stats, webstats


@pytest.fixture(autouse=True)
def clean():
    live.reset()
    stats.stop()
    stats.reset()
    yield
    webstats.stop()
    live.reset()
    stats.stop()
    stats.reset()


def serve(**cfg):
    ok, where = webstats.start(dict({"web_enabled": True, "web_port": 0}, **cfg))
    assert ok, where
    port = int(where.rsplit(":", 1)[1].strip("/"))
    return port


def get(port, path, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path, headers={"Host": host} if host else {})
    r = c.getresponse()
    return r.status, r.getheader("Content-Type"), r.read()


# ---------------------------------------------------------------- the state
def test_log_lines_become_events():
    config.log("HUNT ACTION attack #3 by hand: clicked (0.4,0.3) on the bot at (0.4,0.3), its health 20%; bots seen: ")
    config.log("HUNT waiting for the enemy")  # not interesting
    config.log("HUNT FIGHT over after 42 s")
    kinds = [e["kind"] for e in live.snapshot()["events"]]
    assert kinds == ["action", "fight"]
    assert live.snapshot()["last_action"].startswith("attack #3 by hand")


def test_classify_keeps_warnings_and_ignores_noise():
    assert live.classify("HUNT Ctrl+R did not work: 2 manual attacks, then Ctrl+T")[0] == "warn"
    assert live.classify("HUNT my turn, waiting 3s") is None
    assert live.classify("STATS session 0:05:00 | fights 1")[0] == "stats"


def test_fight_state_and_history():
    live.fight_start()
    live.update(turn="enemy", attacks_left=2, my_health=0.8, bots=[{"x": .4, "y": .3, "health": .3}], target=0)
    live.sample(my=0.8, target=0.3)
    f = live.snapshot()["fight"]
    assert f["in_fight"] and f["number"] == 1 and f["turn"] == "enemy" and f["attacks_left"] == 2
    assert live.snapshot()["series"][-1][1:] == (0.8, 0.3) or list(live.snapshot()["series"][-1][1:]) == [0.8, 0.3]
    live.fight_end()
    f = live.snapshot()["fight"]
    assert not f["in_fight"] and f["bots"] == [] and f["last_seconds"] is not None


def test_snapshot_carries_the_session_counters():
    stats.add("fights_done", 2)
    groups = live.snapshot()["stats"]["groups"]
    flat = {i["key"]: i["value"] for g in groups for i in g["items"]}
    assert flat["fights_done"] == 2


def test_wait_change_wakes_up_on_an_update_and_times_out_otherwise():
    v = live.version()
    t0 = time.time()
    assert live.wait_change(v, 0.2) == v and time.time() - t0 >= 0.15
    live.update(status="x")
    assert live.wait_change(v, 5) != v


# ---------------------------------------------------------------- the server
def test_the_page_and_the_json_are_served():
    port = serve()
    code, ctype, body = get(port, "/")
    assert code == 200 and "text/html" in ctype and b"EventSource" in body and b"AutoPrison live" in body
    assert b"http://" not in body and b"https://" not in body  # nothing is loaded from the internet
    code, ctype, body = get(port, "/api/state")
    data = json.loads(body)
    assert code == 200 and {"fight", "stats", "events", "series", "running"} <= set(data)
    assert get(port, "/healthz")[2] == b"ok"
    assert get(port, "/nothing")[0] == 404


def test_the_event_stream_pushes_state_and_changes_quickly():
    port = serve()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", "/events")
    r = c.getresponse()
    assert r.status == 200 and r.getheader("Content-Type") == "text/event-stream"

    def frame():
        name = data = None
        while True:
            line = r.fp.readline().decode().rstrip("\n")
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:])
            elif line == "" and data is not None:
                return name, data

    name, data = frame()
    assert name == "state" and data["fight"]["in_fight"] is False
    live.update(status="attacking")
    live.event("action", "attack #1")
    t0 = time.time()
    while True:  # the next frames carry the change, well before the one-second timer is needed twice
        name, data = frame()
        if data["status"] == "attacking" and data["events"]:
            break
        assert time.time() - t0 < 4
    assert data["events"][-1]["text"] == "attack #1"
    c.close()


def test_a_foreign_host_name_is_refused_unless_the_network_is_allowed():
    port = serve()
    assert get(port, "/api/state", host="evil.example")[0] == 403
    assert get(port, "/api/state", host="localhost:%d" % port)[0] == 200
    webstats.stop()
    port = serve(web_lan=True)
    assert get(port, "/api/state", host="my-pc.lan")[0] == 200


def test_a_busy_port_is_reported_not_raised():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    busy = s.getsockname()[1]
    try:
        ok, why = webstats.start({"web_enabled": True, "web_port": busy})
        assert not ok and "Cannot listen" in why and webstats.error() == why and not webstats.running()
    finally:
        s.close()


def test_switched_off_means_no_server():
    assert webstats.start({"web_enabled": False, "web_port": 0}) == (False, "off")
    assert not webstats.running()
