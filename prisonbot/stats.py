"""What the bot did in this session: counters (written to the log every few minutes and shown in the Stats tab)."""
import threading, time
from .config import log

# key -> label, in the order they are shown; groups are separated in the window
GROUPS = [
    ("Fights", [
        ("fights_started", "Fights started (the opening attack worked)"),
        ("opening_failed", "Opening attacks that started no fight"),
        ("fights_done", "Fights finished"),
        ("fight_avg", "Average fight length (s)"),
    ]),
    ("Attacks", [
        ("attacks_manual", "Attacks by hand (clicks that worked)"),
        ("attack_misses", "Attack clicks that did nothing"),
        ("third_attacks", "Third attacks (below 50% health)"),
        ("weaker_switch", "Changed to a weaker bot"),
        ("clicks_refused", "Clicks not made: a door or exit label was under the pointer"),
    ]),
    ("Turns", [
        ("repeats", "Ctrl+R sent (repeat the last turn)"),
        ("repeats_ok", "  ... that worked"),
        ("repeats_failed", "  ... that were refused"),
        ("end_turns", "Ctrl+T sent (turn ended)"),
    ]),
    ("Loot and health", [
        ("loot_windows", "Loot windows emptied"),
        ("heals", "Meals eaten to heal"),
        ("heal_failed", "Heals that did not work"),
    ]),
]
RATE = ("fights_done", "attacks_manual", "loot_windows")  # also shown per hour

_lock = threading.Lock()
_count = {}
_run = 0.0  # seconds of hunting already counted
_since = None  # when the current hunt started
_last_log = 0.0


def add(name, n=1):
    with _lock:
        _count[name] = _count.get(name, 0) + n


def get(name):
    with _lock:
        return _count.get(name, 0)


def start():
    global _since, _last_log
    with _lock:
        if _since is None:
            _since = _last_log = time.time()


def stop():
    global _since, _run
    with _lock:
        if _since is not None:
            _run += time.time() - _since
            _since = None


def reset():
    global _run, _since, _last_log
    with _lock:
        _count.clear()
        _run = 0.0
        _since = time.time() if _since is not None else None
        _last_log = time.time()


def seconds():
    with _lock:
        return _run + (time.time() - _since if _since is not None else 0.0)


def clock(secs):
    secs = int(secs)
    return "%d:%02d:%02d" % (secs // 3600, secs % 3600 // 60, secs % 60)


def value(key):
    """Number for a counter (the average fight length is computed)."""
    if key == "fight_avg":
        done = get("fights_done")
        return round(get("fight_seconds") / done) if done else 0
    return get(key)


def llm_rows():
    """The vision model's own counters (empty if it was never asked)."""
    try:
        from . import llm
        s = llm.STATS
    except Exception:
        return []
    if not s["asks"]:
        return []
    avg = s["seconds"] / s["ok"] if s["ok"] else 0.0
    return [("Vision model (Ollama)", [
        ("Questions asked / answered", "%d / %d" % (s["asks"], s["ok"])),
        ("Average answer time (s)", "%.1f" % avg),
        ("Weakest bot: agreed with the bars / differed", "%d / %d" % (s["agree"], s["differ"])),
        ("Attacks left: same as the colour reader / different", "%d / %d" % (s["attacks_same"], s["attacks_differ"])),
    ])]


def rows():
    """[(group title, [(label, text, per hour text)])] for the window and the log."""
    hours = seconds() / 3600.0
    out = []
    for title, items in GROUPS:
        part = []
        for key, label in items:
            v = value(key)
            rate = "%.1f" % (v / hours) if key in RATE and hours > 0.02 else ""
            part.append((label, str(v), rate))
        out.append((title, part))
    for title, items in llm_rows():
        out.append((title, [(a, b, "") for a, b in items]))
    return out


def summary_line():
    return ("STATS session %s | fights %d (avg %d s) | attacks by hand %d, missed clicks %d, third attacks %d | "
            "Ctrl+R %d (worked %d, refused %d), Ctrl+T %d | loots %d | heals %d" % (
                clock(seconds()), get("fights_done"), value("fight_avg"), get("attacks_manual"), get("attack_misses"),
                get("third_attacks"), get("repeats"), get("repeats_ok"), get("repeats_failed"), get("end_turns"),
                get("loot_windows"), get("heals")))


def tick(cfg):
    """Called often while the bot runs: writes the summary to the log every `stats_interval` minutes (0 = never)."""
    global _last_log
    minutes = float(cfg.get("stats_interval", 5) or 0)
    if minutes <= 0 or _since is None:
        return
    now = time.time()
    if now - _last_log >= minutes * 60:
        _last_log = now
        log(summary_line())


def as_dict():
    """The counters as plain data for the web page: seconds, every counter, and the groups with labels and rates."""
    hours = seconds() / 3600.0
    groups = []
    for title, items in GROUPS:
        part = []
        for key, label in items:
            v = value(key)
            part.append({"key": key, "label": label.strip(), "value": v,
                         "rate": round(v / hours, 1) if key in RATE and hours > 0.02 else None})
        groups.append({"title": title, "items": part})
    return {"seconds": int(seconds()), "running": _since is not None, "groups": groups}
