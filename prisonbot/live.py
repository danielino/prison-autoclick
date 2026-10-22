"""What the bot is doing right now, for the live web page: status, the fight in progress, a short health history and the
latest events (taken from the log lines). Read-only data: nothing here can make the bot do anything."""
import collections, threading, time
from . import config, stats

_cond = threading.Condition()
_version = 0
_events = collections.deque(maxlen=200)
_series = collections.deque(maxlen=300)  # (time, my health, target health) samples, 0..1 or None


def _fresh():
    return {"running": False, "status": "", "in_fight": False, "fight_no": 0, "fight_t0": None, "turn": None,
            "attacks_left": None, "my_health": None, "bots": [], "target": None, "last_action": "",
            "last_action_t": None, "last_fight_seconds": None, "since": None}


_state = _fresh()


def _bump():
    global _version
    _version += 1
    _cond.notify_all()


def update(**kw):
    """Set fields of the live state (running, status, turn, attacks_left, my_health, bots, target...)."""
    with _cond:
        _state.update(kw)
        _bump()


def sample(my=None, target=None):
    """One point of the health history (fractions 0..1 or None)."""
    with _cond:
        _series.append((round(time.time(), 1), None if my is None else round(my, 3),
                        None if target is None else round(target, 3)))
        _bump()


def event(kind, text):
    with _cond:
        _events.append({"t": round(time.time(), 1), "kind": kind, "text": text})
        _bump()


def fight_start():
    with _cond:
        _state.update(in_fight=True, fight_no=_state["fight_no"] + 1, fight_t0=time.time(), turn="mine",
                      attacks_left=None, bots=[], target=None)
        _bump()


def fight_end():
    with _cond:
        t0 = _state["fight_t0"]
        _state.update(in_fight=False, turn=None, attacks_left=None, bots=[], target=None, fight_t0=None,
                      last_fight_seconds=round(time.time() - t0) if t0 else None)
        _bump()


def reset():
    """Forget everything (a new run, or the tests)."""
    global _state
    with _cond:
        _state = _fresh()
        _events.clear()
        _series.clear()
        _bump()


def version():
    return _version


def wait_change(version, timeout):
    """Block until something changed since `version` (or the timeout); returns the current version."""
    with _cond:
        if _version == version:
            _cond.wait(timeout)
        return _version


# ---------------------------------------------------------------- log lines -> events
def classify(msg):
    """(kind, text) for the log lines worth showing on the page, else None."""
    if msg.startswith("HUNT ACTION"):
        return "action", msg[len("HUNT ACTION"):].strip()
    if msg.startswith("HUNT FIGHT over") or msg.startswith("HUNT fight detected"):
        return "fight", msg[5:]
    if msg.startswith("HUNT bots="):
        return "target", "Target chosen: " + msg[5:]
    if msg.startswith("STATS"):
        return "stats", msg
    if msg.startswith("LLM says") or msg.startswith("LLM warm-up") or msg.startswith("LLM request failed"):
        return "llm", msg
    if msg.startswith("HUNT the vision model"):
        return "llm", msg[5:]
    if msg.startswith("HUNT attempt") or msg.startswith("HUNT chasing") or msg.startswith("HUNT no fight started"):
        return "attack", msg[5:]
    if msg.startswith("HUNT loot") or msg.startswith("HUNT unique item"):
        return "loot", msg[5:]
    if msg.startswith("HUNT heal"):
        return "heal", msg[5:]
    if (msg.startswith("WINDOW warning") or "Ctrl+R did not work" in msg or "zone changed" in msg
            or "fight longer than" in msg or "stopped" in msg.lower()):
        return "warn", msg
    return None


def _on_log(msg):
    hit = classify(msg)
    if hit:
        kind, text = hit
        event(kind, text)
        if kind == "action":
            with _cond:
                _state.update(last_action=text, last_action_t=time.time())
                _bump()


config.HOOKS.append(_on_log)


# ---------------------------------------------------------------- the data the page shows
def snapshot(events=60):
    now = time.time()
    with _cond:
        s = dict(_state)
        ev = list(_events)[-events:]
        ser = list(_series)
    fight = {"in_fight": s["in_fight"], "number": s["fight_no"], "turn": s["turn"], "attacks_left": s["attacks_left"],
             "my_health": s["my_health"], "bots": s["bots"], "target": s["target"],
             "seconds": round(now - s["fight_t0"]) if s["fight_t0"] else None,
             "last_seconds": s["last_fight_seconds"]}
    out = {"now": round(now, 1), "running": s["running"], "status": s["status"], "fight": fight,
           "last_action": s["last_action"], "last_action_age": round(now - s["last_action_t"]) if s["last_action_t"] else None,
           "series": ser, "events": ev, "stats": stats.as_dict()}
    try:
        from . import llm
        if llm.STATS["asks"]:
            out["llm"] = dict(llm.STATS)
    except Exception:
        pass
    return out
