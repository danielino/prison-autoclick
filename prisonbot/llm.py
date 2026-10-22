"""Optional vision helper: an Ollama server (on this PC or on the network) looks at the fight screen and gives a second
opinion (which enemy has the least health, how many attacks are left). Everything it says is a hint: the colour detectors
stay in charge, and any error, timeout or odd answer just means "no hint". Screenshots are sent only to the address the
user typed in the settings, and only while the option is on."""
import base64, json, re, struct, urllib.request, zlib
from .config import log
from .vision import client_rect, grab

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3-vl:8b-instruct"
MAX_FAILS = 3  # consecutive failures after which the helper is left alone until the next start
_fails = 0

# 3x5 digits for the numbered markers drawn on the screenshot
FONT = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "001", "001", "001"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
}


def active(cfg):
    """True if the helper is switched on and has not given up."""
    return bool(cfg.get("llm_enabled")) and _fails < MAX_FAILS


def reset():
    global _fails
    _fails = 0


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


def ask(cfg, prompt, png):
    """One question about one image -> the JSON object the model answered (dict), or None. Never raises."""
    global _fails
    body = {"model": cfg.get("ollama_model") or DEFAULT_MODEL, "stream": False, "format": "json",
            "options": {"temperature": 0},
            "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(png).decode("ascii")]}]}
    try:
        req = urllib.request.Request(_url(cfg, "/api/chat"), json.dumps(body).encode("utf8"),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=float(cfg.get("llm_timeout", 20))) as r:
            text = json.loads(r.read().decode("utf8"))["message"]["content"]
        m = re.search(r"\{.*\}", text, re.S)
        answer = json.loads(m.group(0)) if m else None
        if not isinstance(answer, dict):
            raise ValueError("no JSON object in the answer: %r" % text[:80])
        _fails = 0
        return answer
    except Exception as e:
        _fails += 1
        log("LLM request failed (%d/%d): %s%s" % (_fails, MAX_FAILS, e, "; helper switched off until restart" if _fails >= MAX_FAILS else ""))
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
    answer = ask(cfg, FIGHT_PROMPT, screen_png(h, cfg, points))
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
    answer = ask(cfg, ATTACKS_PROMPT, screen_png(h, cfg, area=(0.0, 0.0, 0.30, 0.16)))
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
    import time
    t0 = time.time()
    answer = ask(cfg, ATTACKS_PROMPT, screen_png(h, cfg, area=(0.0, 0.0, 0.30, 0.16)))
    if answer is None:
        return False, "The model did not give a usable answer (see autoprison.log)."
    return True, "Answered in %.1f s: attacks left = %s (the box is empty during the enemy's turn)." % (
        time.time() - t0, answer.get("attacks_left"))
