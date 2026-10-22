"""The optional Ollama helper, against a fake local server (no real model, no network)."""
import base64, json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from prisonbot import hunt, llm


class Fake:
    answer = '{"weakest": 2, "attacks_left": 2}'
    models = [{"name": "m:1b"}]
    requests = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.reply({"models": Fake.models})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.requests.append(body)
        self.reply({"message": {"role": "assistant", "content": Fake.answer}})


@pytest.fixture
def server(monkeypatch):
    Fake.answer, Fake.models, Fake.requests = '{"weakest": 2, "attacks_left": 2}', [{"name": "m:1b"}], []
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    llm.reset()
    monkeypatch.setattr(llm, "client_rect", lambda h: (0, 0, 400, 300))
    monkeypatch.setattr(llm, "grab", lambda x, y, w, h: bytes((40, 80, 120, 255)) * (w * h))
    yield {"llm_enabled": True, "ollama_url": "http://127.0.0.1:%d" % srv.server_address[1], "ollama_model": "m:1b",
           "llm_timeout": 5, "llm_max_width": 200}
    srv.shutdown()
    llm.reset()


def test_the_screenshot_sent_is_a_png_with_numbered_markers(server):
    png = llm.screen_png(1, server, points=[(0.25, 0.5), (0.75, 0.5)])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    plain = llm.screen_png(1, server)
    assert png != plain  # the markers were drawn


def test_fight_advice_returns_the_marker_and_the_attacks(server):
    idx, left = llm.fight_advice(server, 1, [(0.2, 0.5), (0.7, 0.5)])
    assert (idx, left) == (1, 2)
    req = Fake.requests[0]
    assert req["model"] == "m:1b" and req["stream"] is False and req["format"] == "json"
    assert base64.b64decode(req["messages"][0]["images"][0])[:4] == b"\x89PNG"


def test_a_marker_outside_the_list_is_ignored(server):
    Fake.answer = '{"weakest": 7, "attacks_left": 9}'
    assert llm.fight_advice(server, 1, [(0.2, 0.5), (0.7, 0.5)]) == (None, None)


def test_the_answer_may_come_wrapped_in_text(server):
    Fake.answer = 'Sure! {"attacks_left": 3} hope it helps'
    assert llm.read_attacks(server, 1) == 3


def test_nothing_is_sent_when_the_helper_is_off(server):
    server["llm_enabled"] = False
    assert llm.fight_advice(server, 1, [(0.2, 0.5)]) == (None, None)
    assert Fake.requests == []


def test_bad_answers_give_no_hint_and_three_failures_switch_it_off(server):
    Fake.answer = "I cannot see anything"
    for _ in range(3):
        assert llm.fight_advice(server, 1, [(0.2, 0.5), (0.7, 0.5)]) == (None, None)
    assert not llm.active(server)
    n = len(Fake.requests)
    llm.fight_advice(server, 1, [(0.2, 0.5)])
    assert len(Fake.requests) == n  # left alone until restart


def test_unreachable_server_is_not_an_error(server):
    server["ollama_url"] = "http://127.0.0.1:9"
    assert llm.fight_advice(server, 1, [(0.2, 0.5), (0.7, 0.5)]) == (None, None)


def test_connection_test_reports_a_missing_model(server):
    assert llm.test_connection(server)[0]
    server["ollama_model"] = "other"
    ok, text = llm.test_connection(server)
    assert not ok and "ollama pull other" in text


# --- how the fight uses it
class Bot(hunt.HuntMixin):
    def __init__(self, cfg):
        self.cfg = cfg


def advice(monkeypatch, idx):
    monkeypatch.setattr(hunt.llm, "fight_advice", lambda cfg, h, pts: (idx, None))


CFG = {"llm_enabled": True, "llm_mode": "assist"}


def test_assist_follows_the_model_when_the_bars_cannot_tell(monkeypatch):
    advice(monkeypatch, 1)
    cands = [(0.3, 0.3), (0.6, 0.3)]
    assert Bot(CFG).llm_pick(1, cands, {(0.3, 0.3): 0.50, (0.6, 0.3): 0.46})[0] == (0.6, 0.3)
    assert Bot(CFG).llm_pick(1, cands, {})[0] == (0.6, 0.3)  # nothing measured


def test_assist_keeps_a_clear_bar_reading(monkeypatch):
    advice(monkeypatch, 1)
    cands = [(0.3, 0.3), (0.6, 0.3)]
    assert Bot(CFG).llm_pick(1, cands, {(0.3, 0.3): 0.2, (0.6, 0.3): 0.9})[0] == (0.3, 0.3)


def test_decide_mode_lets_the_model_win(monkeypatch):
    advice(monkeypatch, 1)
    cands = [(0.3, 0.3), (0.6, 0.3)]
    cfg = dict(CFG, llm_mode="decide")
    assert Bot(cfg).llm_pick(1, cands, {(0.3, 0.3): 0.2, (0.6, 0.3): 0.9})[0] == (0.6, 0.3)


def test_a_bot_being_hit_is_not_changed_in_assist_mode(monkeypatch):
    advice(monkeypatch, 1)
    cands = [(0.3, 0.3), (0.6, 0.3)]
    assert Bot(CFG).llm_pick(1, cands, {}, locked=(0.3, 0.3))[0] == (0.3, 0.3)


def test_no_helper_no_change(monkeypatch):
    advice(monkeypatch, 1)
    assert Bot({}).llm_pick(1, [(0.3, 0.3), (0.6, 0.3)], {})[0] == (0.3, 0.3)
