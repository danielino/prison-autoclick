"""Optional vision helper: an Ollama server (on this PC or on the network) looks at the fight screen and gives a second
opinion (which enemy has the least health, how many attacks are left). Everything it says is a hint: the colour detectors
stay in charge, and any error, timeout or odd answer just means "no hint". Screenshots are sent only to the address the
user typed in the settings, and only while the option is on."""
import base64, json, re, struct, threading, time, urllib.request, zlib
from .config import log
from .vision import client_rect, grab

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3-vl:8b-instruct"
MAX_FAILS = 3  # consecutive failures after which the helper is left alone until the next start
FIGHT_TIMEOUT = 15  # seconds: a turn is short, a slow answer is worth nothing (the model is loaded beforehand)
KEEP_ALIVE = "30m"  # how long Ollama keeps the model in memory after a request
_fails = 0
_state = "cold"  # cold -> warming -> ready (or failed): the first request makes Ollama load the model
STATS = {"asks": 0, "ok": 0, "seconds": 0.0, "agree": 0, "differ": 0, "attacks_same": 0, "attacks_differ": 0}

# 3x5 digits for the numbered markers drawn on the screenshot
FONT = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "001", "001", "001"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
}


def active(cfg):
    """True if the helper is switched on, has not given up and the model is loaded. If it is not loaded yet, loading
    starts in the background and the fight goes on without the helper meanwhile."""
    if not cfg.get("llm_enabled") or _fails >= MAX_FAILS:
        return False
    if _state == "cold":
        start_warm_up(cfg)
    return _state == "ready"


def reset():
    global _fails, _state
    _fails, _state = 0, "cold"


def mark_ready():
    global _state
    _state = "ready"


def warm_up(cfg):
    """Make Ollama load the model now (an empty request, like `ollama run` does), so that the first question in a fight
    is answered at full speed. Loading a model of several GB can take half a minute. (True, text) or (False, text)."""
    global _state
    _state = "warming"
    name = cfg.get("ollama_model") or DEFAULT_MODEL
    t0 = time.time()
    log("LLM warm-up: asking Ollama to load %s (this can take a while the first time)" % name)
    try:
        req = urllib.request.Request(_url(cfg, "/api/generate"), json.dumps({"model": name, "prompt": "", "stream": False,
                                     "keep_alive": KEEP_ALIVE}).encode("utf8"), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            r.read()
        _state = "ready"
        text = "Model %s loaded in %.1f s." % (name, time.time() - t0)
        log("LLM warm-up: " + text)
        return True, text
    except Exception as e:
        _state = "failed"
        text = "Could not load %s: %s" % (name, e)
        log("LLM warm-up failed after %.1f s: %s" % (time.time() - t0, e))
        return False, text


def start_warm_up(cfg):
    """warm_up in a thread (once); the fight does not wait for it."""
    global _state
    if _state in ("warming", "ready"):
        return
    _state = "warming"
    threading.Thread(target=warm_up, args=(dict(cfg),), daemon=True).start()


# ---------------------------------------------------------------- images
def to_rgb(buf, w, h, max_w):
    """Grabbed BGRA buffer -> (rows of RGB bytes, width, height), shrunk (every n-th pixel) to at most max_w wide."""
    step = max(1, -(-w // max_w))  # ceil
    w2, h2 = w // step, h // step
    stride = w * 4
    rows = []
    for y in range(h2):
        row = buf[y * step * stride:(y * step + 1) * stride]
        out = bytearray(w2 * 3)
        out[0::3] = row[2::4 * step][:w2]
        out[1::3] = row[1::4 * step][:w2]
        out[2::3] = row[0::4 * step][:w2]
        rows.append(out)
    return rows, w2, h2


def draw_marker(rows, w, h, cx, cy, n, scale):
    """A black box with a yellow frame and the number `n` (1-99) centred on (cx, cy) pixels."""
    text = str(n)
    tw, th = (len(text) * 4 - 1) * scale, 5 * scale
    x0, y0 = int(cx - tw / 2) - scale, int(cy - th / 2) - scale
    x1, y1 = x0 + tw + 2 * scale, y0 + th + 2 * scale
    for y in range(max(y0, 0), min(y1, h)):
        for x in range(max(x0, 0), min(x1, w)):
            edge = x < x0 + 1 or x >= x1 - 1 or y < y0 + 1 or y >= y1 - 1
            rows[y][x * 3:x * 3 + 3] = bytes((255, 220, 0)) if edge else bytes((0, 0, 0))
    for k, ch in enumerate(text):
        for j, line in enumerate(FONT[ch]):
            for i, c in enumerate(line):
                if c != "1":
                    continue
                for yy in range(scale):
                    for xx in range(scale):
                        x, y = x0 + scale + (k * 4 + i) * scale + xx, y0 + scale + j * scale + yy
                        if 0 <= x < w and 0 <= y < h:
                            rows[y][x * 3:x * 3 + 3] = bytes((255, 220, 0))


def png_bytes(rows, w, h):
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    raw = b"".join(b"\0" + bytes(r) for r in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 3)) + chunk(b"IEND", b""))


def screen_png(h, cfg, points=(), area=(0.0, 0.0, 1.0, 1.0)):
    """PNG of `area` of the game window (client fractions) with a numbered marker on each of `points` (client fractions)."""
    fx, fy, fw, fh = area
    x, y, w, hh = client_rect(h)
    pw, ph = int(fw * w), int(fh * hh)
    rows, w2, h2 = to_rgb(grab(x + int(fx * w), y + int(fy * hh), pw, ph), pw, ph, int(cfg.get("llm_max_width", 1024)))
    scale = max(2, w2 // 220)
    for n, (px, py) in enumerate(points, 1):
        draw_marker(rows, w2, h2, (px - fx) / fw * w2, (py - fy) / fh * h2, n, scale)
    return png_bytes(rows, w2, h2)


# ---------------------------------------------------------------- the server
def _url(cfg, path):
    return (cfg.get("ollama_url") or DEFAULT_URL).rstrip("/") + path


def ask(cfg, prompt, png, kind="question"):
    """One question about one image -> the JSON object the model answered (dict), or None. Never raises."""
    global _fails
    body = {"model": cfg.get("ollama_model") or DEFAULT_MODEL, "stream": False, "format": "json", "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0},
            "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(png).decode("ascii")]}]}
    STATS["asks"] += 1
    t0 = time.time()
    log("LLM ask [%s]: model %s at %s, image %d KB" % (kind, body["model"], cfg.get("ollama_url") or DEFAULT_URL, len(png) // 1024))
    try:
        req = urllib.request.Request(_url(cfg, "/api/chat"), json.dumps(body).encode("utf8"),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=min(float(cfg.get("llm_timeout", 12)), FIGHT_TIMEOUT)) as r:
            text = json.loads(r.read().decode("utf8"))["message"]["content"]
        m = re.search(r"\{.*\}", text, re.S)
        answer = json.loads(m.group(0)) if m else None
        if not isinstance(answer, dict):
            raise ValueError("no JSON object in the answer: %r" % text[:80])
        _fails = 0
        STATS["ok"] += 1
        STATS["seconds"] += time.time() - t0
        log("LLM answer in %.1f s: %s" % (time.time() - t0, " ".join(text.split())[:100]))
        return answer
    except Exception as e:
        _fails += 1
        log("LLM request failed after %.1f s (%d/%d): %s%s" % (time.time() - t0, _fails, MAX_FAILS, e, "; helper switched off until restart" if _fails >= MAX_FAILS else ""))
        return None


def test_connection(cfg):
    """(ok, text) for the settings window: is the server there and does it have the model?"""
    try:
        with urllib.request.urlopen(_url(cfg, "/api/tags"), timeout=5) as r:
            names = [m.get("name", "") for m in json.loads(r.read().decode("utf8")).get("models", [])]
    except Exception as e:
        return False, "No answer from %s: %s" % (cfg.get("ollama_url") or DEFAULT_URL, e)
    want = cfg.get("ollama_model") or DEFAULT_MODEL
    if want in names or (":" not in want and any(n.split(":")[0] == want for n in names)):
        return True, "Connected. Model %s is installed." % want
    return False, "Connected, but model %s is not installed (have: %s). Run: ollama pull %s" % (
        want, ", ".join(names) or "none", want)


# ---------------------------------------------------------------- questions
FIGHT_PROMPT = (
    "This is a screenshot of a turn-based fighting game. Yellow numbered markers (1, 2, ...) are drawn over the enemies. "
    "Every enemy has a health bar above it: bright red = health left, dark red = health lost. "
    "The box ATAQUES at the top left shows how many attacks the player has left this turn (a big digit). "
    "Answer ONLY with JSON: {\"weakest\": <number of the marker of the enemy with the LEAST health left, or null>, "
    "\"attacks_left\": <the digit in the ATAQUES box, or null if there is none>}.")
ATTACKS_PROMPT = (
    "This is the top left corner of a game screen. The box labelled ATAQUES contains one big digit (the attacks left this "
    "turn; red 0 means none). Answer ONLY with JSON: {\"attacks_left\": <the digit as a number, or null if there is none>}.")


def _int(v, lo, hi):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


def fight_advice(cfg, h, points):
    """Ask which of `points` (client fractions, up to 9) is the enemy with the least health. -> index into `points` or
    None, and the ATAQUES digit or None."""
    if not active(cfg) or not points:
        return None, None
    points = list(points)[:9]
    answer = ask(cfg, FIGHT_PROMPT, screen_png(h, cfg, points), "weakest bot, %d markers" % len(points))
    if not answer:
        return None, None
    n = _int(answer.get("weakest"), 1, len(points))
    left = _int(answer.get("attacks_left"), 0, 5)
    log("LLM says: weakest marker %s, attacks left %s" % (n, left))
    return (n - 1 if n else None), left


def read_attacks(cfg, h):
    """The ATAQUES digit read by the model from the top left corner, or None."""
    if not active(cfg):
        return None
    answer = ask(cfg, ATTACKS_PROMPT, screen_png(h, cfg, area=(0.0, 0.0, 0.30, 0.16)), "attacks left")
    left = _int((answer or {}).get("attacks_left"), 0, 5)
    log("LLM reads attacks left: %s" % left)
    return left


# ---------------------------------------------------------------- settings window helpers
def list_models(cfg):
    """(True, [installed model names]) or (False, error text)."""
    try:
        with urllib.request.urlopen(_url(cfg, "/api/tags"), timeout=5) as r:
            return True, sorted(m.get("name", "") for m in json.loads(r.read().decode("utf8")).get("models", []))
    except Exception as e:
        return False, "No answer from %s: %s" % (cfg.get("ollama_url") or DEFAULT_URL, e)


def pull_model(cfg, on_progress):
    """Download the configured model (like `ollama pull`). on_progress(text, fraction or None) is called as it goes.
    (True, text) or (False, error text)."""
    name = cfg.get("ollama_model") or DEFAULT_MODEL
    try:
        req = urllib.request.Request(_url(cfg, "/api/pull"), json.dumps({"model": name, "stream": True}).encode("utf8"),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            for line in r:
                if not line.strip():
                    continue
                msg = json.loads(line.decode("utf8"))
                if msg.get("error"):
                    return False, str(msg["error"])
                done, total = msg.get("completed"), msg.get("total")
                on_progress(msg.get("status", ""), (done / total) if done and total else None)
        return True, "Model %s is ready." % name
    except Exception as e:
        return False, "Download failed: %s" % e


def test_on_screen(cfg, h):
    """Send the top left corner of the game (the HUD) and report what the model reads, and how long it took."""
    if _state != "ready":
        ok, text = warm_up(cfg)  # the first request loads the model: report that time apart from the answer
        if not ok:
            return False, text
    t0 = time.time()
    answer = ask(cfg, ATTACKS_PROMPT, screen_png(h, cfg, area=(0.0, 0.0, 0.30, 0.16)), "screen test")
    if answer is None:
        return False, "The model did not give a usable answer (see autoprison.log)."
    return True, "Answered in %.1f s: attacks left = %s (the box is empty during the enemy's turn)." % (
        time.time() - t0, answer.get("attacks_left"))


def stats_line():
    """One line for the log: how often the model was asked, how fast, and how often it agreed with the colour detectors."""
    s = STATS
    avg = s["seconds"] / s["ok"] if s["ok"] else 0.0
    return ("LLM stats: %d asked, %d answered (avg %.1f s); weakest bot: agreed with the bars %d, differed %d; "
            "attacks left: same as the colour reader %d, different %d") % (
        s["asks"], s["ok"], avg, s["agree"], s["differ"], s["attacks_same"], s["attacks_differ"])


HOVER_PROMPT = (
    "This is a crop of a game screen around the mouse pointer (the pointer itself is not drawn). The game may show a text "
    "label over what is under the pointer: the name of a door, an exit or a zone to go to (often with an arrow), or the "
    "name of a character or object. Read the label. Answer ONLY with JSON: {\"text\": <the label text, or empty if there "
    "is none>, \"is_exit\": <true if it names a door, exit, stairs, zone or place you would walk to; false if it names a "
    "character, a bot or an item>}.")


def read_hover(cfg, h, p):
    """Read the label shown near the pointer at `p` (client fractions): (text, is_exit) or None if the model did not
    answer. Used before a click in the scene, to be sure it is not a door."""
    if not active(cfg):
        return None
    fx0, fy0 = max(p[0] - 0.16, 0.0), max(p[1] - 0.25, 0.0)
    area = (fx0, fy0, min(0.32, 1 - fx0), min(0.35, 1 - fy0))
    answer = ask(cfg, HOVER_PROMPT, screen_png(h, cfg, area=area), "label under the pointer")
    if not answer:
        return None
    text = str(answer.get("text") or "").strip()
    is_exit = answer.get("is_exit")
    log("LLM reads the label under the pointer: %r exit=%s" % (text[:60], is_exit))
    return text, (is_exit is True or str(is_exit).lower() == "true")


LAYOUT_PROMPT = (
    "This is a screenshot of a game window. Locate these interface elements. Answer ONLY with JSON in which every value is "
    "a box [x0, y0, x1, y1] given as fractions of the image width and height (0 to 1), or null if the element is not "
    "visible: "
    "\"health_bar\": the red bar next to the label SALUD in the bottom toolbar; "
    "\"bottom_bar\": the whole bottom toolbar strip (the GENERAL or COMBATE banner is in its middle); "
    "\"chat\": the chat text panel under the bottom toolbar; "
    "\"minimap\": the minimap panel at the top right, frame included; "
    "\"top_bar\": the toolbar along the top edge; "
    "\"attacks_box\": the small box labelled ATAQUES at the top left (only shown in a fight); "
    "\"turn_buttons\": the group of round buttons R, T, H, F (only shown in a fight).")
LAYOUT_KEYS = ("health_bar", "bottom_bar", "chat", "minimap", "top_bar", "attacks_box", "turn_buttons")


def wait_ready(cfg, timeout=90.0):
    """Wait (up to `timeout` s) for the model to be loaded; loads it if nobody did. True if it is ready."""
    if _state == "cold":
        start_warm_up(cfg)
    end = time.time() + timeout
    while _state == "warming" and time.time() < end:
        time.sleep(0.3)
    return _state == "ready"


def _norm_box(box, w, h):
    """A box as the model gave it -> (x0, y0, x1, y1) fractions, or None. Accepts fractions, a 0..1000 scale (what some
    models use for boxes) and pixels of the image sent."""
    try:
        x0, y0, x1, y1 = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    top = max(x0, y0, x1, y1)
    if top > 1.5:
        if top <= 1000:
            x0, y0, x1, y1 = x0 / 1000.0, y0 / 1000.0, x1 / 1000.0, y1 / 1000.0
        else:
            x0, y0, x1, y1 = x0 / w, y0 / h, x1 / w, y1 / h
    x0, x1, y0, y1 = max(min(x0, x1), 0.0), min(max(x0, x1), 1.0), max(min(y0, y1), 0.0), min(max(y0, y1), 1.0)
    if x1 - x0 < 0.01 or y1 - y0 < 0.005:
        return None
    return (x0, y0, x1, y1)


def analyze_layout(cfg, h):
    """Ask the model where the sections of the screen are. -> {name: (x0, y0, x1, y1) fractions} for the ones it found
    (possibly empty), or None if it did not answer."""
    if not cfg.get("llm_enabled"):
        return None
    if not wait_ready(cfg):
        log("LLM layout: the model is not ready")
        return None
    x, y, w, hh = client_rect(h)
    max_w = int(cfg.get("llm_max_width", 1024))
    iw, ih = min(w, max_w), int(hh * min(w, max_w) / float(w))
    answer = ask(cfg, LAYOUT_PROMPT, screen_png(h, cfg), "screen sections")
    if not answer:
        return None
    boxes = {}
    for key in LAYOUT_KEYS:
        b = _norm_box(answer.get(key), iw, ih) if answer.get(key) else None
        if b:
            boxes[key] = b
    log("LLM layout: " + ", ".join("%s=(%.2f,%.2f,%.2f,%.2f)" % ((k,) + v) for k, v in boxes.items()))
    return boxes
