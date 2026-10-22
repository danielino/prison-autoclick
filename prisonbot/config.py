"""Paths, defaults, saved data and the rotating log."""
import json, os, re, sys, time


HERE = os.environ.get("AUTOPRISON_HOME") or os.path.dirname(
    os.path.abspath(sys.executable if getattr(sys, "frozen", False) else os.path.dirname(__file__)))
try:  # folder not writable (e.g. Program Files): use the user profile
    with open(os.path.join(HERE, ".w"), "w"):
        pass
    os.remove(os.path.join(HERE, ".w"))
except OSError:
    HERE = os.path.join(os.environ.get("APPDATA", HERE), "AutoPrison")
    os.makedirs(HERE, exist_ok=True)
DATA = os.path.join(HERE, "autoprison_data.json")
TITLE_RE = re.compile(r"Prison Legacy \(\d+ x \d+\)")
VK = {"TAB": 0x09, "F8": 0x77, "F9": 0x78, "F10": 0x79, "F12": 0x7B, "CAPSLOCK": 0x14}


DEFAULTS = {"hotkey": "TAB", "speed": 1.0, "click_interval": 0.10, "repeat_command": "/repetir",
            "repeat_interval": 5.0, "loot_command": "/loot", "hunt_area": None, "hunt_gap": 0.07, "hunt_map_gap": 0.10, "hunt_walk": False, "hunt_home": True, "hunt_patrol": True, "hunt_min_health": 0.70, "hunt_destroy_unique": True, "hunt_tour": 5, "hunt_forbidden": [], "heal_item": None, "seq_pause": 0.5, "jitter": 0.2, "background": False, "bg_settle": 0.15, "sequences": {},
            "stats_interval": 5, "auto_heal": True, "llm_layout": True, "web_enabled": True, "web_port": 8080, "web_lan": False, "llm_enabled": False, "llm_mode": "assist", "ollama_url": "http://localhost:11434", "ollama_model": "qwen3-vl:8b-instruct", "llm_timeout": 12, "llm_max_width": 1024,
            "names": {}, "library": {}}


LOG = os.path.join(HERE, "autoprison.log")


HOOKS = []  # functions called with every log line (the live web page listens here)


def log(msg):
    try:
        with open(LOG, "a", encoding="utf8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except OSError:
        pass
    for hook in HOOKS:
        try:
            hook(msg)
        except Exception:
            pass


LOG_KEEP = 5  # rotated logs kept: autoprison.log.1 (newest) ... autoprison.log.5


def rotate_log(keep=LOG_KEEP):
    """Start every run with a fresh log: autoprison.log -> .1 -> .2 ... the oldest one is dropped."""
    try:
        if not (os.path.exists(LOG) and os.path.getsize(LOG) > 0):
            return
        for i in range(keep, 0, -1):
            src = LOG if i == 1 else "%s.%d" % (LOG, i - 1)
            if os.path.exists(src):
                os.replace(src, "%s.%d" % (LOG, i))  # overwrites the previous .i (the oldest at i == keep)
    except OSError:
        pass  # a log that cannot be rotated (e.g. open elsewhere) is simply appended to


# ---------------------------------------------------------------- data
def load():
    cfg = dict(DEFAULTS)
    try:
        with open(DATA, encoding="utf8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    if cfg.get("hunt_gap") == 0.12:  # the old default was too wide: bots 10% apart were never attacked
        cfg["hunt_gap"] = DEFAULTS["hunt_gap"]
    return cfg


def save(cfg):
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(cfg, f, indent=1)
    os.replace(tmp, DATA)  # atomic write: no sequences lost if the PC restarts


__all__ = [n for n in list(globals()) if not n.startswith("__")]
