"""AutoPrison: autoclick and click-sequence recorder for Prison Legacy (clean-room rewrite).

EXTERNAL program: it only simulates mouse and keyboard input (SendInput) and reads screen pixels.
It never opens, reads or modifies the game process (the window is found by its title only).
It acts only while the game window is in the foreground.

Usage: TAB opens the menu, then:
  1 autoclick   2 record (then 1-9)   3 play (then 1-9)   4 speed (1 up, 2 down, 0 exit)
  5 simple auto-fight (/repeat)   6 double-turn auto-fight (alternates sequences 8 and 9)
  7 auto-hunt (finds bots by their label, Ctrl+A, Ctrl+R each turn, /loot, next bot)   0 close menu
TAB stops everything. Sequences are saved immediately to autoprison_data.json.
"""
import copy, ctypes, json, os, random, re, sys, threading, time, tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from ctypes import wintypes

u32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    u32.SetProcessDPIAware()

HERE = os.environ.get("AUTOPRISON_HOME") or os.path.dirname(
    os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
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
LBTN, RBTN = 0x01, 0x02

DEFAULTS = {"hotkey": "TAB", "speed": 1.0, "click_interval": 0.10, "repeat_command": "/repetir",
            "repeat_interval": 5.0, "loot_command": "/loot", "hunt_area": None, "hunt_gap": 0.07, "hunt_map_gap": 0.10, "hunt_walk": False, "hunt_home": True, "hunt_patrol": True, "hunt_min_health": 0.70, "hunt_destroy_unique": True, "hunt_tour": 5, "hunt_forbidden": [], "seq_pause": 0.5, "jitter": 0.2, "background": False, "bg_settle": 0.15, "sequences": {},
            "names": {}, "library": {}}


# ---------------------------------------------------------------- Win32 helpers
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(inp):
    u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def mouse_click(button="L", hold=0.04):
    down, up = (0x0002, 0x0004) if button == "L" else (0x0008, 0x0010)
    _send(INPUT(0, mi=MOUSEINPUT(0, 0, 0, down, 0, 0)))
    time.sleep(hold)
    _send(INPUT(0, mi=MOUSEINPUT(0, 0, 0, up, 0, 0)))


def key_tap(vk=None, char=None):
    if char is not None:
        for fl in (0x0004, 0x0004 | 0x0002):  # UNICODE down / up
            _send(INPUT(1, ki=KEYBDINPUT(0, ord(char), fl, 0, 0)))
    else:
        for fl in (0, 0x0002):
            _send(INPUT(1, ki=KEYBDINPUT(vk, 0, fl, 0, 0)))
    time.sleep(0.01)


def key_scan(sc, hold=0.05):
    # hardware scancode (SCANCODE flag): games that ignore virtual-key Enter accept this
    _send(INPUT(1, ki=KEYBDINPUT(0, sc, 0x0008, 0, 0)))
    time.sleep(hold)
    _send(INPUT(1, ki=KEYBDINPUT(0, sc, 0x0008 | 0x0002, 0, 0)))
    time.sleep(0.02)


def key_combo(mod_sc, key_sc, hold=0.05):
    """Ctrl+key etc. as hardware scancodes (Ctrl 0x1D, A 0x1E, R 0x13)."""
    _send(INPUT(1, ki=KEYBDINPUT(0, mod_sc, 0x0008, 0, 0)))
    time.sleep(0.06)
    key_scan(key_sc, hold)
    _send(INPUT(1, ki=KEYBDINPUT(0, mod_sc, 0x0008 | 0x0002, 0, 0)))
    time.sleep(0.03)


def type_line(text):
    for ch in text:
        key_tap(char=ch)
    time.sleep(0.12)  # let the chat box take the last character
    key_scan(0x1C)  # Enter


def find_game():
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if u32.IsWindowVisible(h):
            n = u32.GetWindowTextLengthW(h)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(h, buf, n + 1)
                if TITLE_RE.search(buf.value):
                    found.append(h)
        return True
    u32.EnumWindowsProc = cb
    u32.EnumWindows(cb, 0)
    return found[0] if found else None


def client_rect(h):
    r = wintypes.RECT()
    u32.GetClientRect(h, ctypes.byref(r))
    p = wintypes.POINT(0, 0)
    u32.ClientToScreen(h, ctypes.byref(p))
    return p.x, p.y, r.right - r.left, r.bottom - r.top


gdi = ctypes.windll.gdi32
_P, _I = ctypes.c_void_p, ctypes.c_int
u32.GetDC.restype = _P
u32.GetDC.argtypes = [_P]
u32.ReleaseDC.argtypes = [_P, _P]
gdi.CreateCompatibleDC.restype = _P
gdi.CreateCompatibleDC.argtypes = [_P]
gdi.CreateCompatibleBitmap.restype = _P
gdi.CreateCompatibleBitmap.argtypes = [_P, _I, _I]
gdi.SelectObject.restype = _P
gdi.SelectObject.argtypes = [_P, _P]
gdi.BitBlt.argtypes = [_P, _I, _I, _I, _I, _P, _I, _I, wintypes.DWORD]
gdi.GetDIBits.argtypes = [_P, _P, wintypes.UINT, wintypes.UINT, _P, _P, wintypes.UINT]
gdi.DeleteObject.argtypes = [_P]
gdi.DeleteDC.argtypes = [_P]


class BMIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def grab(x, y, w, h):
    """Read screen pixels like a screenshot, from outside the game. The cursor is not included."""
    w, h = max(int(w), 1), max(int(h), 1)
    sdc = u32.GetDC(None)
    mdc = gdi.CreateCompatibleDC(sdc)
    bmp = gdi.CreateCompatibleBitmap(sdc, w, h)
    old = gdi.SelectObject(mdc, bmp)
    gdi.BitBlt(mdc, 0, 0, w, h, sdc, int(x), int(y), 0x00CC0020)
    bi = BMIH(40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi.SelectObject(mdc, old)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mdc)
    u32.ReleaseDC(None, sdc)
    return buf.raw


def changed(a, b, min_frac=0.03, tol=30):
    """True if at least min_frac of the sampled pixels changed visibly."""
    if len(a) != len(b):
        return True
    n = hit = 0
    for i in range(0, len(a) - 3, 16):  # un pixel ogni 4
        n += 1
        if abs(a[i] - b[i]) > tol or abs(a[i + 1] - b[i + 1]) > tol or abs(a[i + 2] - b[i + 2]) > tol:
            hit += 1
    return n > 0 and hit / n >= min_frac


# --- screen detectors for auto-hunt (colour heuristics measured on real game screenshots, 2360x1328 layout)
def _red(r, g, b):  # the "COMBATE" banner (it reads "GENERAL" in grey outside combat)
    return r > 170 and g < 110 and b < 90


def _green(r, g, b):  # the R/T/H/F turn buttons: green rings, only on your turn
    return g > 150 and r < 120 and b < 130


def _rust(r, g, b):  # header of the "REGISTRO" (loot) window
    return 45 < r < 135 and g < 40 and b < 15 and r > 3 * g


DETECT = {  # name: (fx, fy, fw, fh, colour test, minimum fraction of matching pixels)
    # taller zones: the bottom bar sits higher when the chat panel is taller (checked on screenshots 4, 20, 21)
    "combat": (0.43, 0.77, 0.14, 0.10, _red, 0.02),
    "turn": (0.43, 0.66, 0.17, 0.14, _green, 0.002),
}
LOOT_AREA = (0.42, 0.20, 0.16, 0.45)  # where the (vertically centred, variable height) REGISTRO window can be


def find_band(buf, w, hh):
    """Centre row (fraction of the area height) of the first wide rust-red band = REGISTRO header, else None."""
    run = []
    for r in range(0, hh, 2):
        base = r * w * 4
        n = hit = 0
        for i in range(base, base + w * 4, 8):
            n += 1
            if _rust(buf[i + 2], buf[i + 1], buf[i]):
                hit += 1
        if n and hit / n >= 0.35:
            run.append(r)
        elif len(run) >= 8:
            break
        else:
            run = []
    return (run[0] + run[-1]) / 2 / hh if len(run) >= 8 else None


def _label(r, g, b):  # lavender text of a living bot's name label (corpses and walls do not match this)
    return 140 <= r <= 205 and 7 <= b - r <= 32 and 0 <= g - r <= 8


LABEL_AREA = (0.08, 0.10, 0.70, 0.64)  # scene only: no minimap, no chat, no target panel; stops above the bottom bar
# (its "ABS 100%" text has the same colour as a bot label and used to be read as a bot at the bottom of the screen)
BODY_DROP = 0.11  # the body (where to click) is this fraction of the screen height below the label


def _mine(r, g, b):  # your own name label: pure yellow
    return r >= 200 and g >= 200 and b <= 60 and abs(r - g) <= 30


def find_labels(buf, w, hh, scale, test=None):
    """Clusters of label-coloured pixels -> [(x, y, samples)] as fractions of the area. Samples every 2nd pixel."""
    cw, ch = max(int(50 * scale), 8), max(int(30 * scale), 6)
    cells = {}
    for y in range(0, hh, 2):
        base = y * w * 4
        for x in range(0, w, 2):
            i = base + x * 4
            if (test or _label)(buf[i + 2], buf[i + 1], buf[i]):
                k = (x // cw, y // ch)
                c = cells.get(k)
                if c is None:
                    cells[k] = [1, x, y]
                else:
                    c[0] += 1
                    c[1] += x
                    c[2] += y
    seen, out = set(), []
    for k in cells:
        if k in seen:
            continue
        stack, n, sx, sy = [k], 0, 0, 0
        seen.add(k)
        while stack:
            a = stack.pop()
            v = cells[a]
            n, sx, sy = n + v[0], sx + v[1], sy + v[2]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    b = (a[0] + dx, a[1] + dy)
                    if b in cells and b not in seen:
                        seen.add(b)
                        stack.append(b)
        if n >= 14:
            out.append((sx / n / w, sy / n / hh, n))
    return out


def find_bots(h):
    """Living bots on screen, as client-area fractions of a point on their body, nearest to the player first."""
    fx, fy, fw, fh = LABEL_AREA
    x, y, w, hh = client_rect(h)
    rw, rh = int(fw * w), int(fh * hh)
    labels = find_labels(grab(x + int(fx * w), y + int(fy * hh), rw, rh), rw, rh, w / 2000.0)
    bots = [(fx + lx * fw, min(fy + ly * fh + BODY_DROP, 0.9)) for lx, ly, _ in labels]
    return sorted(bots, key=lambda p: (p[0] - 0.5) ** 2 + (p[1] - 0.65) ** 2)


# --- minimap (top right): bots are diamonds with a red border, the player is a blue arrow, orange dots are fixed
# points of the map (exits / usable objects) that we never click on
MAP_AREA = (0.804, 0.083, 0.18, 0.31)


def _diamond(r, g, b):
    return r >= 150 and g <= 65 and b <= 65 and r - g >= 100


def _arrow(r, g, b):
    return b > 200 and r < 90 and g > 90


def _cone(r, g, b):  # translucent green fan = a bot with a visor (yours is blue)
    return g > r + 25 and g > b + 15 and r < 170


def _dot(r, g, b):
    return r > 230 and 130 < g < 190 and b < 50


def _clusters(buf, w, hh, test, gap, minn):
    """Group pixels passing `test` that lie within `gap` px of a group -> [(x, y, count)] in area fractions."""
    groups = []
    for y in range(hh):
        base = y * w * 4
        for x in range(w):
            i = base + x * 4
            if test(buf[i + 2], buf[i + 1], buf[i]):
                for g in groups:
                    if abs(g[0] - x) <= gap and abs(g[1] - y) <= gap:
                        g[2] += 1
                        g[3] += x
                        g[4] += y
                        g[0], g[1] = g[3] / g[2], g[4] / g[2]
                        break
                else:
                    groups.append([x, y, 1, x, y])
    return [(g[0] / w, g[1] / hh, g[2]) for g in groups if g[2] >= minn]


FORBIDDEN_SPOTS = []  # the user's forbidden minimap zones, as keep-away spots (same shape as the deadly ones)


def set_forbidden(rects):
    """Zones drawn by the user on the minimap ([x0, y0, x1, y1] as fractions of the minimap area) become a grid of
    keep-away spots: walking, patrol and bot choice already avoid those, and being inside one triggers the retreat."""
    FORBIDDEN_SPOTS[:] = []
    for x0, y0, x1, y1 in rects or []:
        nx, ny = max(int((x1 - x0) / 0.05) + 1, 1), max(int((y1 - y0) / 0.05) + 1, 1)
        for i in range(nx + 1 if nx > 1 else 1):
            for j in range(ny + 1 if ny > 1 else 1):
                x = x0 + (x1 - x0) * (i / nx if nx > 1 else 0.5)
                y = y0 + (y1 - y0) * (j / ny if ny > 1 else 0.5)
                FORBIDDEN_SPOTS.append((x, y, 0.07, 0.035))


def read_minimap(buf, w, hh):
    """-> (player (x, y) or None, bots [(x, y)], dots [(x, y)], deadly [(x, y)]), as fractions of the minimap area.
    `deadly` = all-red diamonds (deadliest level) and visor fans: never go near them."""
    scale = w / 357.0
    gap = max(int(7 * scale), 3)
    arrow = _clusters(buf, w, hh, _arrow, gap, max(int(8 * scale), 4))
    player = max(arrow, key=lambda c: c[2])[:2] if arrow else None
    bots, deadly = [], []
    for x, y, _ in _clusters(buf, w, hh, _diamond, gap, max(int(10 * scale), 5)):
        cx, cy = int(x * w), int(y * hh)  # the fill of the diamond: all red = the deadliest level
        px = [buf[((cy + j) * w + cx + i) * 4 + k] for i in (-1, 0, 1) for j in (-1, 0, 1)
              if 0 <= cx + i < w and 0 <= cy + j < hh for k in (2, 1, 0)]
        n = len(px) // 3
        r, g, b = (sum(px[k::3]) / n for k in range(3)) if n else (0, 0, 0)
        if r >= 190 and g <= 95 and b <= 85:
            deadly.append((x, y, 0.20, 0.15))  # (x, y, keep-away radius for walking, alarm radius)
        else:
            bots.append((x, y))
    # the visor of a bot is a green fan next to its diamond: also forbidden (the small green "N" marker is too small)
    # radii measured on the user's "limit" screenshot: safe at 0.085 from the nearest fan pixel (0.106 from the fragment
    # centres); walking keeps 0.14 from the centres, the alarm fires below 0.095
    deadly += [(c[0], c[1], 0.14, 0.095) for c in _clusters(buf, w, hh, _cone, gap, max(int(80 * scale * scale), 25))]
    dots = [c[:2] for c in _clusters(buf, w, hh, _dot, gap, max(int(10 * scale), 5))]
    return player, bots, dots, deadly + FORBIDDEN_SPOTS


def grab_minimap(h):
    fx, fy, fw, fh = MAP_AREA
    x, y, w, hh = client_rect(h)
    rw, rh = int(fw * w), int(fh * hh)
    return grab(x + int(fx * w), y + int(fy * hh), rw, rh), rw, rh


FEET_DROP = 0.23  # your feet are about this fraction of the screen height below your name label


def find_self(h):
    """Your own character: (x, y) of the name label as client fractions, or None. Looks at the whole scene width."""
    fx, fy, fw, fh = 0.0, 0.08, 0.78, 0.72
    x, y, w, hh = client_rect(h)
    rw, rh = int(fw * w), int(fh * hh)
    labels = find_labels(grab(x + int(fx * w), y + int(fy * hh), rw, rh), rw, rh, w / 2000.0, _mine)
    if not labels:
        return None
    lx, ly, _ = max(labels, key=lambda c: c[2])
    return fx + lx * fw, fy + ly * fh


ZONE_AREA = (0.83, 0.02, 0.125, 0.045)  # zone name bar, top right (not the spinning globe next to it)


GRID = 28


def grab_zone(h):
    """Fingerprint of the zone: the SHAPE of its minimap (light floor vs dark walls), as a GRID x GRID bit grid.
    The name above it is no good: it moves a little and scrolls when it is too long. None if the map is not visible."""
    buf, rw, rh = grab_minimap(h)
    cells = []
    for j in range(GRID):
        base = int((j + 0.5) * rh / GRID) * rw
        for i in range(GRID):
            k = (base + int((i + 0.5) * rw / GRID)) * 4
            r, g, b = buf[k + 2], buf[k + 1], buf[k]
            cells.append(1 if (r + g + b) / 3 > 75 and b >= r - 5 else 0)
    return cells if 0.15 < sum(cells) / len(cells) < 0.85 else None


def zone_differs(a, b):
    """Fraction of cells of the two fingerprints that differ even looking at the neighbour cells (small shifts, the
    player's marker and the diamonds do not count). None if either is unusable."""
    if not a or not b:
        return None
    n = 0
    for j in range(GRID):
        for i in range(GRID):
            v = a[j * GRID + i]
            near = [b[jj * GRID + ii] for jj in range(max(j - 1, 0), min(j + 2, GRID))
                    for ii in range(max(i - 1, 0), min(i + 2, GRID))]
            if v not in near:
                n += 1
    return n / (GRID * GRID)


# --- health ("SALUD" bar, bottom right): a red fill growing from the left; measured on screenshots the bar is ~99 px long
# at a window width of 2000 and its fill is linear in the SALUD number
HEALTH_AREA = (0.62, 0.76, 0.08, 0.14)  # the bottom bar moves a little when the chat panel changes height
HEALTH_LEN = 0.0497  # full bar length as a fraction of the client width


def health_from_buf(buf, w, hh, client_w):
    """Fill fraction (0..1) of the health bar inside a grabbed region. The row with most red pixels is the bar."""
    best = (0, 0, 0)
    for y in range(hh):
        base = y * w * 4
        n, x0, x1 = 0, None, 0
        for x in range(w):
            i = base + x * 4
            if _diamond(buf[i + 2], buf[i + 1], buf[i]):  # same strong red as the minimap borders
                n += 1
                x0 = x if x0 is None else x0
                x1 = x
        if n > best[0]:
            best = (n, x0, x1)
    if best[0] < 3:
        return 0.0
    return min(1.0, (best[2] - best[1] + 1) / (HEALTH_LEN * client_w))


def read_health(h):
    fx, fy, fw, fh = HEALTH_AREA
    x, y, w, hh = client_rect(h)
    rw, rh = int(fw * w), int(fh * hh)
    return health_from_buf(grab(x + int(fx * w), y + int(fy * hh), rw, rh), rw, rh, w)


# --- UNIQUE items: the game refuses a second copy ("No puedes recoger eso porque es UNICO ...", a full red chat line).
# The item is then destroyed with right click -> "CONFIRMAR" dialog -> SI, and the list moves up one position.
CHAT_LINE = (0.0, 0.950, 0.62, 0.032)  # the newest chat line (bottom of the screen)
CHAT_TWO = (0.0, 0.925, 0.62, 0.057)  # the two newest lines: a new message moves everything up one line


def _chat_red(r, g, b):
    return r >= 200 and g <= 70 and b <= 70


def grab_chat(h):
    fx, fy, fw, fh = CHAT_TWO
    x, y, w, hh = client_rect(h)
    return grab(x + int(fx * w), y + int(fy * hh), int(fw * w), int(fh * hh))


def chat_unique_error(h):
    """True if the newest chat line is a long, fully red message (screenshots: ~2750 red px, 43% of the width wide;
    other players' lines only have a short red name)."""
    fx, fy, fw, fh = CHAT_LINE
    x, y, w, hh = client_rect(h)
    rw, rh = int(fw * w), int(fh * hh)
    return red_line_is_error(grab(x + int(fx * w), y + int(fy * hh), rw, rh), rw, rh, w)


def red_line_is_error(buf, w, hh, client_w):
    n, lo, hi = 0, w, 0
    for y in range(hh):
        base = y * w * 4
        for x in range(w):
            i = base + x * 4
            if _chat_red(buf[i + 2], buf[i + 1], buf[i]):
                n += 1
                lo, hi = min(lo, x), max(hi, x)
    scale = client_w / 2000.0
    return n >= 1200 * scale * scale and (hi - lo) >= 0.30 * client_w


def find_dialog(h, below):
    """Header band of the CONFIRMAR dialog (screen centre), looking from `below` (fraction of the height) down.
    Returns its centre as a fraction of the client height, or None."""
    fx, fw, fh = 0.30, 0.40, 0.30
    x, y, w, hh = client_rect(h)
    rw, rh = int(fw * w), int(fh * hh)
    c = find_band(grab(x + int(fx * w), y + int(below * hh), rw, rh), rw, rh)
    return None if c is None else below + c * fh


def find_loot(h):
    """Vertical position of the loot window header as a fraction of the client height, or None if it is closed."""
    fx, fy, fw, fh = LOOT_AREA
    x, y, w, hh = client_rect(h)
    rw, rh = int(fw * w), int(fh * hh)
    c = find_band(grab(x + int(fx * w), y + int(fy * hh), rw, rh), rw, rh)
    return None if c is None else fy + c * fh


def detect(h, name):
    fx, fy, fw, fh, test, need = DETECT[name]
    x, y, w, hh = client_rect(h)
    rw, rh = int(fw * w), int(fh * hh)
    buf = grab(x + int(fx * w), y + int(fy * hh), rw, rh)
    n = hit = 0
    for i in range(0, len(buf) - 3, 8):  # every 2nd pixel (BGRA)
        n += 1
        if test(buf[i + 2], buf[i + 1], buf[i]):
            hit += 1
    frac = hit / n if n else 0.0
    return frac >= need, frac


u32.PostMessageW.argtypes =[wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.PrintWindow.argtypes = [wintypes.HWND, _P, wintypes.UINT]


def post_click(h, button, px, py, hold=0.04, settle=0.15):
    """Background click: window messages sent to the game window, no cursor movement, no focus change.
    px, py are client-area pixels."""
    lp = ((py & 0xFFFF) << 16) | (px & 0xFFFF)
    post_click.n = getattr(post_click, "n", 0) + 1
    if post_click.n <= 5:
        log("background click #%d -> hwnd=%s client=(%d,%d) button=%s" % (post_click.n, h, px, py, button))
    down, up, mk = (0x0201, 0x0202, 0x0001) if button == "L" else (0x0204, 0x0205, 0x0002)
    u32.PostMessageW(h, 0x0200, 0, lp)  # WM_MOUSEMOVE: the game needs to see the pointer over the window
    time.sleep(settle)  # an unfocused game updates its hover state slowly: let it catch up before clicking
    u32.PostMessageW(h, 0x0200, 0, lp)
    time.sleep(0.03)
    u32.PostMessageW(h, down, mk, lp)
    time.sleep(hold)
    u32.PostMessageW(h, up, 0, lp)


def grab_window(h, rx, ry, rw, rh):
    """Read a region (client pixels) of the game window even if other windows cover it (PrintWindow)."""
    _, _, w, hh = client_rect(h)
    sdc = u32.GetDC(None)
    mdc = gdi.CreateCompatibleDC(sdc)
    bmp = gdi.CreateCompatibleBitmap(sdc, w, hh)
    old = gdi.SelectObject(mdc, bmp)
    u32.PrintWindow(h, mdc, 3)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT
    bi = BMIH(40, w, -hh, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * hh * 4)
    gdi.GetDIBits(mdc, bmp, 0, hh, buf, ctypes.byref(bi), 0)
    gdi.SelectObject(mdc, old)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mdc)
    u32.ReleaseDC(None, sdc)
    raw = buf.raw
    rx, ry = max(min(rx, w - 1), 0), max(min(ry, hh - 1), 0)
    rw, rh = max(min(rw, w - rx), 1), max(min(rh, hh - ry), 1)
    return b"".join(raw[((ry + r) * w + rx) * 4:((ry + r) * w + rx + rw) * 4] for r in range(rh))


u32.GetForegroundWindow.restype = ctypes.c_void_p
u32.GetAncestor.restype = ctypes.c_void_p
u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
LOG = os.path.join(HERE, "autoprison.log")


def log(msg):
    try:
        with open(LOG, "a", encoding="utf8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except OSError:
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


def game_focused():
    h = find_game()
    fg = u32.GetForegroundWindow()
    if h and fg and (fg == h or u32.GetAncestor(fg, 2) == h):
        return h
    return None


def cursor_pos():
    p = wintypes.POINT()
    u32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def down(vk):
    return bool(u32.GetAsyncKeyState(vk) & 0x8000)


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


# ---------------------------------------------------------------- app
class App:
    def __init__(self):
        self.cfg = load()
        self.hot = VK.get(self.cfg["hotkey"].upper(), 0x09)
        self.state = "IDLE"  # IDLE MENU REC_SLOT REC PLAY_SLOT SPEED RUN
        self.msg = ""
        self.rec, self.rec_slot, self.rec_t0 = [], None, 0.0
        self.stop = threading.Event()
        self.worker = None
        self.prev = {}
        self.root = tk.Tk()
        self.root.withdraw()
        self.ov = tk.Toplevel(self.root)
        self.ov.overrideredirect(True)
        self.ov.attributes("-topmost", True)
        self.ov.configure(bg="#0b1220", highlightthickness=2, highlightbackground="#ffe14d")
        self.ov.attributes("-alpha", 0.9)
        self.lbl = tk.Label(self.ov, text="", justify="left", anchor="nw", font=("Segoe UI", 15, "bold"),
                            fg="#ffffff", bg="#0b1220", padx=16, pady=12)
        self.lbl.pack()
        self.ov.update_idletasks()
        gw = self.ov.winfo_id()  # click-through and non-activating: never steals focus from the game
        hwnd = u32.GetParent(gw) or gw
        ex = u32.GetWindowLongW(hwnd, -20)
        u32.SetWindowLongW(hwnd, -20, ex | 0x80000 | 0x20 | 0x80 | 0x08000000)
        self.ov.withdraw()
        self.blink = True
        self.bg = False
        self.hunt_pts = {}
        self.hunt_counts = (0, 0)
        self.hunt_outside = []
        self.home = self.safe_pos = None
        self.gui = Gui(self)

    def slot_lines(self):
        seqs, names = self.cfg["sequences"], self.cfg["names"]
        return ["  %s  %s" % (s, names.get(s) or "(unnamed)") for s in sorted(seqs)]

    # -- input edge detection
    def pressed(self, vk):
        d = down(vk)
        was = self.prev.get(vk, False)
        self.prev[vk] = d
        return d and not was

    def digit(self):
        for n in range(10):
            if self.pressed(0x30 + n) | self.pressed(0x60 + n):
                return n
        return None

    # -- overlay
    def show(self, h):
        x, y, w, hgt = client_rect(h)
        lines = {
            "MENU": ["AUTOPRISON  [%s = stop]" % self.cfg["hotkey"],
                     "1 Autoclick On/Off", "2 Record", "3 Play", "4 Change speed (x%.2f)" % self.cfg["speed"],
                     "5 Simple auto-fight", "6 Double-turn auto-fight",
                     "7 Auto-hunt (finds bots by name label)", "0 Close menu"],
            "REC_SLOT": ["RECORD: press 1-9 to choose the sequence slot"] + self.slot_lines() + ["0 cancel"],
            "REC": ["RECORDING sequence %s  (%d clicks)" % (self.rec_slot, len(self.rec)),
                    "F9 = wait for a dialog window (screen center, e.g. MAQUINA)",
                    "F10 = wait for a menu next to the cursor",
                    "%s to finish and save" % self.cfg["hotkey"]],
            "PLAY_SLOT": ["PLAY: press 1-9"] + self.slot_lines() + ["0 cancel"],
            "HUNT_SETUP": ["AUTO-HUNT: choose the area where bots may be attacked",
                           "Put the mouse on the TOP-LEFT corner, press F9" + ("  [set]" if "tl" in self.hunt_pts else ""),
                           "Put the mouse on the BOTTOM-RIGHT corner, press F10" + ("  [set]" if "br" in self.hunt_pts else ""),
                           "1 start" + ("" if len(self.hunt_pts) == 2 else " (set both corners first)"),
                           "2 use the saved area" + ("" if self.cfg.get("hunt_area") else " (none saved)"),
                           "0 cancel"],
            "SPEED": ["SPEED x%.2f" % self.cfg["speed"], "1 faster   2 slower   0 exit"],
            "RUN": [self.msg, "%s to stop" % self.cfg["hotkey"]],
        }.get(self.state, [])
        if self.msg and self.state not in ("RUN",):
            lines = lines + ["", self.msg]
        if not lines:
            self.ov.withdraw()
            return
        if self.state in ("MENU", "SPEED", "REC_SLOT", "PLAY_SLOT", "HUNT_SETUP"):
            self.blink = not self.blink if int(time.time() * 2) % 2 == 0 else self.blink
        self.lbl.config(text="\n".join(lines))
        self.ov.geometry("+%d+%d" % (x + 12, y + 12))
        self.ov.deiconify()
        self.ov.attributes("-topmost", True)

    # -- state machine, runs every 15 ms on the Tk thread
    def tick(self):
        try:
            h = game_focused()
            seen = (bool(h), self.state)
            if seen != getattr(self, "_seen", None):
                self._seen = seen
                log("focus=%s state=%s fg=%s game=%s" % (bool(h), self.state, u32.GetForegroundWindow(), find_game()))
            if self.state == "RUN" and self.worker and not self.worker.is_alive():
                self.state = "IDLE"
            bg = self.state == "RUN" and self.bg
            if bg and self.pressed(VK["F12"]):  # global stop while running in the background
                self.halt("Stopped (F12)")
                bg = False
            if not h:
                if self.state != "IDLE" and not bg:
                    self.halt("Game not in foreground: stopped")
                self.ov.withdraw()
                if not bg:
                    self.prev = {}
                return
            if self.pressed(self.hot):
                self.on_hotkey()
            elif self.state == "REC":
                self.record_clicks(h)
            elif self.state in ("MENU", "REC_SLOT", "PLAY_SLOT", "SPEED", "HUNT_SETUP"):
                if self.state == "HUNT_SETUP":
                    self.hunt_corners(h)
                d = self.digit()
                if d is not None:
                    key_scan(0x0E, hold=0.02)  # the game also typed the digit into its chat box: erase it (Backspace)
                    getattr(self, "on_" + self.state.lower())(d)
            self.show(h)
        except Exception:
            import traceback
            log(traceback.format_exc())
        finally:
            self.root.after(15, self.tick)

    def halt(self, msg=""):
        self.stop.set()
        if self.state == "REC":
            self.finish_rec()
        self.state, self.msg = "IDLE", msg

    def on_hotkey(self):
        log("hotkey in state %s" % self.state)
        if self.state == "IDLE":
            self.state, self.msg = "MENU", ""
        elif self.state == "REC":
            self.finish_rec()
            self.state = "IDLE"
        else:
            self.halt("")

    def on_menu(self, d):
        s = self.cfg
        if d == 0:
            self.state = "IDLE"
        elif d == 2:
            self.state = "REC_SLOT"
        elif d == 3:
            self.state = "PLAY_SLOT"
        elif d == 4:
            self.state = "SPEED"
        elif d == 1:
            self.run("Autoclick running", self.w_autoclick, bg=True)
        elif d == 5:
            self.run("Simple auto-fight running (%s)" % s["repeat_command"], self.w_repeat)
        elif d == 6:
            self.run("Double-turn auto-fight (sequences 8 and 9)", self.w_double, bg=True)
        elif d == 7:
            self.state, self.msg, self.hunt_pts = "HUNT_SETUP", "", {}

    def on_rec_slot(self, d):
        if d == 0:
            self.state = "IDLE"
            return
        self.rec_slot, self.rec, self.rec_t0, self.state = str(d), [], time.time(), "REC"
        self.prev[LBTN] = self.prev[RBTN] = True  # ignore the click already held down

    def on_play_slot(self, d):
        if d == 0:
            self.state = "IDLE"
        elif str(d) not in self.cfg["sequences"]:
            self.msg = "Sequence %d is empty" % d
        else:
            self.run("Playing sequence %d" % d, lambda: self.w_play([str(d)]), bg=True)

    def hunt_corners(self, h):
        x, y, w, hh = client_rect(h)
        cx, cy = cursor_pos()
        pt = (min(max((cx - x) / max(w, 1), 0.0), 1.0), min(max((cy - y) / max(hh, 1), 0.0), 1.0))
        for vk, key in ((VK["F9"], "tl"), (VK["F10"], "br")):
            if self.pressed(vk):
                self.hunt_pts[key] = pt
                log("HUNT corner %s = (%.3f, %.3f)" % (key, pt[0], pt[1]))

    def on_hunt_setup(self, d):
        if d == 0:
            self.state = "IDLE"
        elif d == 1:
            if len(self.hunt_pts) < 2:
                self.msg = "Set both corners first (F9 and F10)"
                return
            (ax, ay), (bx, by) = self.hunt_pts["tl"], self.hunt_pts["br"]
            area = [min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)]
            if area[2] - area[0] < 0.03 or area[3] - area[1] < 0.03:
                self.msg = "Area too small: pick two opposite corners"
                return
            self.cfg["hunt_area"] = [round(v, 4) for v in area]
            save(self.cfg)
            self.run("Auto-hunt running", self.w_hunt)
        elif d == 2:
            if self.cfg.get("hunt_area"):
                self.run("Auto-hunt running (saved area)", self.w_hunt)
            else:
                self.msg = "No saved area yet"

    def on_speed(self, d):
        if d == 1:
            self.cfg["speed"] = min(8.0, round(self.cfg["speed"] * 1.25, 3))
        elif d == 2:
            self.cfg["speed"] = max(0.1, round(self.cfg["speed"] / 1.25, 3))
        elif d == 0:
            save(self.cfg)
            self.state = "IDLE"

    # -- recording
    def record_clicks(self, h):
        for key, kind in ((VK["F9"], "dialog"), (VK["F10"], "near")):
            if self.hot == key or not self.pressed(key):
                continue
            if self.rec and "wait" not in self.rec[-1]:
                c = self.rec[-1]
                if kind == "dialog":  # dialog windows (e.g. MAQUINA) appear in the screen center
                    fx, fy, fw, fh = 0.30, 0.46, 0.60, 0.20
                else:  # context menus appear next to the click
                    fw, fh = 0.16, 0.28
                    fx = round(min(max(c["fx"] - fw / 2, 0), 1 - fw), 5)
                    fy = round(min(max(c["fy"] - fh / 2, 0), 1 - fh), 5)
                self.rec.append({"dt": 0, "wait": 1, "timeout": 3.0, "fx": fx, "fy": fy, "fw": fw, "fh": fh})
                self.msg = "Wait (%s) added after click %d" % (kind, len(self.rec) - 1)
            else:
                self.msg = "Click the thing that opens the window first"
        for vk, name in ((LBTN, "L"), (RBTN, "R")):
            if self.pressed(vk):
                x, y, w, hh = client_rect(h)
                cx, cy = cursor_pos()
                log("REC click %s screen=(%d,%d) client_origin=(%d,%d) client_size=(%d,%d) -> px=(%d,%d)" % (
                    name, cx, cy, x, y, w, hh, cx - x, cy - y))
                now = time.time()
                self.rec.append({"dt": round(now - self.rec_t0, 3), "b": name,
                                 "fx": round((cx - x) / max(w, 1), 5), "fy": round((cy - y) / max(hh, 1), 5)})
                self.rec_t0 = now

    def finish_rec(self):
        if self.rec:
            self.cfg["sequences"][self.rec_slot] = self.rec
            save(self.cfg)
            self.msg = "Sequence %s saved (%d clicks)" % (self.rec_slot, len(self.rec))
            self.gui.refresh()
        self.rec = []

    # -- workers (thread): always interrupted by stop or by losing focus
    def run(self, msg, fn, bg=False):
        self.stop.clear()
        self.bg = bg and bool(self.cfg["background"])
        self.state, self.msg = "RUN", msg + (" [background, F12 stops]" if self.bg else "")
        self.worker = threading.Thread(target=fn, daemon=True)
        self.worker.start()

    def game(self):
        """The game window if it can currently receive our clicks, else None."""
        if self.bg:
            h = find_game()
            return h if h and not u32.IsIconic(h) else None
        return game_focused()

    def alive(self):
        return not self.stop.is_set() and self.game() is not None

    def click_at(self, h, button, px, py):
        """Click at client pixels (px, py): by messages in background mode, else with the real mouse."""
        if self.bg:
            post_click(h, button, px, py, settle=self.cfg["bg_settle"])
        else:
            x, y, _, _ = client_rect(h)
            u32.SetCursorPos(x + px, y + py)
            time.sleep(0.01)
            mouse_click(button)

    def snap(self, h, ev):
        x, y, w, hh = client_rect(h)
        rx, ry, rw, rh = int(ev["fx"] * w), int(ev["fy"] * hh), int(ev["fw"] * w), int(ev["fh"] * hh)
        return grab_window(h, rx, ry, rw, rh) if self.bg else grab(x + rx, y + ry, rw, rh)

    def wait(self, secs):
        end = time.time() + secs
        while time.time() < end:
            if not self.alive():
                return False
            time.sleep(min(0.02, max(end - time.time(), 0)))
        return self.alive()

    def w_autoclick(self):
        target = None
        if self.bg:  # remember where the cursor was over the game when started; the real mouse is then free
            h = find_game()
            x, y, w, hh = client_rect(h)
            cx, cy = cursor_pos()
            target = (min(max(cx - x, 0), w - 1), min(max(cy - y, 0), hh - 1))
        while self.alive():
            if target:
                post_click(self.game(), "L", *target, settle=self.cfg["bg_settle"])
            else:
                mouse_click("L")
            j = self.cfg["jitter"]  # delay set in the window, in ms; independent of the sequence speed
            if not self.wait(max(self.cfg["click_interval"] * (1 + random.uniform(-j, j)), 0.01)):
                break

    def w_repeat(self):
        while self.alive():
            type_line(self.cfg["repeat_command"])
            if not self.wait(max(self.cfg["repeat_interval"], 5.0)):  # never below 5 s, independent of speed
                break

    def jit(self, secs):
        j = self.cfg["jitter"]
        return secs * (1 + random.uniform(-j, j)) / self.cfg["speed"]

    def region(self, h, ev):
        x, y, w, hh = client_rect(h)
        return int(x + ev["fx"] * w), int(y + ev["fy"] * hh), int(ev["fw"] * w), int(ev["fh"] * hh)

    def play_once(self, slot):
        evs = self.cfg["sequences"].get(slot, [])
        for i, ev in enumerate(evs):
            if "wait" in ev:
                continue  # handled together with the previous click
            if not self.wait(self.jit(ev["dt"])):
                return False
            h = self.game()  # in background mode: the game window even when not focused (user's request)
            if not h:
                return False
            nxt = evs[i + 1] if i + 1 < len(evs) and "wait" in evs[i + 1] else None
            _, _, w, hh = client_rect(h)
            px, py = int(ev["fx"] * w), int(ev["fy"] * hh)
            log("PLAY slot %s event %d bg=%s client_size=(%d,%d) -> px=(%d,%d)" % (slot, i, self.bg, w, hh, px, py))
            for attempt in (1, 2):
                base = self.snap(h, nxt) if nxt else None
                self.click_at(h, ev["b"], px, py)
                if not nxt:
                    break
                end = time.time() + nxt["timeout"]
                ok = False
                while time.time() < end and self.alive():
                    time.sleep(0.08 if self.bg else 0.04)
                    if changed(base, self.snap(h, nxt)):
                        ok = True
                        break
                if not self.alive():
                    return False
                if ok:
                    if not self.wait(self.jit(0.08)):  # window opened: short pause, then continue
                        return False
                    break
                log("window did not appear after click %d (attempt %d)" % (i, attempt))
        return True

    def w_play(self, slots):
        while self.alive():
            for s in slots:
                if not self.play_once(s):
                    return
            if not self.wait(self.cfg["seq_pause"] / self.cfg["speed"]):
                return

    # -- auto-hunt: attack the bot at the starting spot, repeat the attack each turn, loot, wait for it to respawn
    def hunt_say(self, text):
        self.msg = "Auto-hunt: " + text
        log("HUNT " + text)

    def hunt_move(self, h, fx, fy):
        x, y, w, hh = client_rect(h)
        u32.SetCursorPos(x + int(fx * w), y + int(fy * hh))
        time.sleep(0.12)

    def hunt_in_combat(self, h):
        """(in combat?, banner fraction, turn-buttons fraction). Either cue counts: the red COMBATE banner or the
        green turn buttons, so a miss of one does not hide a fight."""
        banner, fc = detect(h, "combat")
        mine, ft = detect(h, "turn")
        return banner or mine, fc, ft

    def hunt_attack(self, h, spot):
        """Ctrl+A, then click the bot (it may have to walk there first). True once a fight is detected."""
        for attempt in (1,):
            self.hunt_say("attacking (Ctrl+A + click)")
            self.hunt_move(h, *spot)
            key_combo(0x1D, 0x1E)  # Ctrl+A: the cursor becomes the attack pointer
            time.sleep(0.1)
            mouse_click("L")
            # the character now WALKS to the bot and the fight starts when it arrives: keep waiting while it moves,
            # give up only when it has stood still for 3 s without a fight (or after 30 s)
            t0, best, still, last = time.time(), (0.0, 0.0), 0.0, find_self(h)
            lastm = read_minimap(*grab_minimap(h))[0]  # the minimap arrow also tells whether we are walking
            while time.time() - t0 < 30:
                if not self.wait(0.4):
                    return False
                ok, fc, ft = self.hunt_in_combat(h)
                best = (max(best[0], fc), max(best[1], ft))
                if ok:
                    log("HUNT fight detected after %.1f s (banner %.3f, buttons %.3f)" % (time.time() - t0, fc, ft))
                    return True
                me = find_self(h)
                pm = read_minimap(*grab_minimap(h))[0]
                same_scene = bool(me and last) and abs(me[0] - last[0]) < 0.004 and abs(me[1] - last[1]) < 0.004
                same_map = bool(pm and lastm) and abs(pm[0] - lastm[0]) < 0.006 and abs(pm[1] - lastm[1]) < 0.006
                if same_scene and (same_map or not pm):
                    still += 0.4
                else:
                    still = 0.0
                last, lastm = me or last, pm or lastm
                if still >= 3.0 and time.time() - t0 > 1.5:
                    break
            log("HUNT attempt %d at (%.3f,%.3f): no fight after %.1f s (best banner %.3f, buttons %.3f)" % (
                attempt, spot[0], spot[1], time.time() - t0, best[0], best[1]))
        return False

    def hunt_approach(self, h, bot):
        """The game refuses attacks on bots that are too far ("escapado de tu radio de acciÃ³n"): click the floor part of
        the way towards the bot, then wait until the character stops. False if we cannot see ourselves."""
        me = find_self(h)
        if not me:
            log("HUNT approach: own label not found")
            return False
        mx, my = me[0], me[1] + FEET_DROP
        bx, by = bot[0], bot[1] + 0.11  # body point + a bit = the bot's feet
        px, py = mx + (bx - mx) * 0.6, my + (by - my) * 0.6
        log("HUNT approach: me=(%.3f,%.3f) bot=(%.3f,%.3f) click=(%.3f,%.3f)" % (mx, my, bx, by, px, py))
        self.hunt_say("moving closer to the bot")
        self.hunt_move(h, px, min(py, 0.88))
        mouse_click("L")
        last, still, t0 = me, 0.0, time.time()
        while time.time() - t0 < 8:
            if not self.wait(0.4):
                return False
            cur = find_self(h)
            if cur and last and abs(cur[0] - last[0]) < 0.004 and abs(cur[1] - last[1]) < 0.004:
                still += 0.4
                if still >= 1.2:
                    return True
            else:
                still = 0.0
            last = cur or last
        return True

    def hunt_engage(self, h, bot):
        """Attack; if the bot is out of range, walk closer and try again (up to 4 times)."""
        for step in range(4):
            if self.hunt_attack(h, bot):
                return True
            if not self.alive() or step == 3 or not self.hunt_approach(h, bot):
                return False
            near = [p for p in find_bots(h) if abs(p[0] - bot[0]) < 0.25 and abs(p[1] - bot[1]) < 0.25]
            bot = min(near, key=lambda p: (p[0] - bot[0]) ** 2 + (p[1] - bot[1]) ** 2) if near else bot
        return False

    OPENING = 2  # manual attacks (Ctrl+A + click) before Ctrl+R has something to repeat

    def hunt_manual_attack(self, h, spot):
        """One manual attack inside the fight: click the bot nearest to `spot` (the second bot of a fight
        stands somewhere else, so the scene is scanned again)."""
        bots = find_bots(h)
        if bots:
            ref = spot or (0.5, 0.5)
            spot = min(bots, key=lambda p: (p[0] - ref[0]) ** 2 + (p[1] - ref[1]) ** 2)
        if not spot:
            return False
        self.hunt_move(h, *spot)
        mouse_click("L")  # inside a fight a plain click on the bot attacks (no Ctrl+A)
        return True

    def hunt_fight(self, h, spot=None):
        """Attack by hand for the first turns (Ctrl+R has nothing to repeat yet), then Ctrl+R on every turn of yours until
        the fight is over (banner gone for 2 s). If Ctrl+R does not pass the turn (e.g. the bot it repeated is dead and a
        second one is in the fight), it starts again with manual attacks. False if stopped/timeout."""
        last, gone, t0 = 0.0, None, time.time()
        manual, sent_r, end_turn, away, fails = self.OPENING, None, False, None, 0
        mine_t = -99.0
        while True:
            if not self.wait(0.4):
                return False
            now = time.time()
            in_combat, fc, ft = self.hunt_in_combat(h)
            if ft >= DETECT["turn"][5]:
                mine_t = now
            mine = now - mine_t < 1.2  # the green ring pulses: a short gap does not mean the turn is over
            if in_combat:
                gone = None
                # the turn really passed (buttons away for 2 s): nothing left to end, the repeat worked
                away = (away or now) if not mine else None
                if away and now - away >= 2.0:
                    end_turn, sent_r, fails = False, None, 0
                if sent_r and mine and now - sent_r >= 3.0:
                    # still our turn 3 s after Ctrl+R: the game said "La secuencia de repetición no puede ser ejecutada"
                    # (the bot it repeated on is dead and another one is in the fight): attack by hand again
                    sent_r = None
                    log("HUNT Ctrl+R did not work: %d manual attacks, then Ctrl+T" % self.OPENING)
                    manual, end_turn = self.OPENING, False
                if mine and now - last >= max(self.cfg["repeat_interval"], 5.0):
                    log("HUNT health %.0f%% in the fight" % (read_health(h) * 100))
                    if manual > 0:
                        log("HUNT my turn (buttons %.3f) -> manual attack (%d left)" % (ft, manual))
                        self.hunt_say("my turn: attacking (click on the bot)")
                        if self.hunt_manual_attack(h, spot):
                            manual -= 1
                            end_turn = manual == 0  # both attacks done: spend the leftover action points by ending the turn
                    elif end_turn:
                        log("HUNT still my turn after the attacks -> Ctrl+T (end turn)")
                        self.hunt_say("my turn: ending it (Ctrl+T)")
                        key_combo(0x1D, 0x14)
                        end_turn = False
                    else:
                        log("HUNT my turn (buttons %.3f) -> Ctrl+R" % ft)
                        self.hunt_say("my turn: Ctrl+R")
                        key_combo(0x1D, 0x13)
                        sent_r = now
                    last = now
                else:
                    self.hunt_say("fighting" if not mine else "my turn, waiting %ds" % max(
                        0, round(max(self.cfg["repeat_interval"], 5.0) - (now - last))))
            else:
                gone = gone or now
                if now - gone >= 2.0:
                    return True
            if now - t0 > 900:
                self.hunt_say("fight longer than 15 min: stopped")
                return False

    def hunt_loot(self, h):
        if not self.wait(1.0):
            return
        self.hunt_say("looting (%s)" % self.cfg["loot_command"])
        type_line(self.cfg["loot_command"])
        end = time.time() + 3.5
        opened = False
        top = None
        while time.time() < end and top is None:
            if not self.wait(0.2):
                return
            top = find_loot(h)
        if top is None:
            log("HUNT loot window did not open")
            return
        skip, destroyed = 0, 0  # skip = rows at the top that cannot be taken and are left alone
        for k in range(14):
            # item rows (icon + name) sit 0.095 of the screen height below the header, 0.069 apart; the window is
            # re-located every time because it shrinks and re-centres when an item is taken
            row = skip + (0 if k < 10 else k - 9)  # first row until it is empty, then probe the rows below
            log("HUNT loot click %d: header y=%.3f row=%d" % (k, top, row))
            base = grab_chat(h)
            self.hunt_move(h, 0.41, top + 0.095 + row * 0.069)
            mouse_click("L")
            if not self.wait(0.6):
                return
            if chat_unique_error(h) and changed(base, grab_chat(h), min_frac=0.01, tol=40):
                log("HUNT unique item at row %d (the game says we already have one)" % row)
                if self.cfg["hunt_destroy_unique"] and destroyed < 4 and self.hunt_destroy(h, top, row):
                    destroyed += 1
                else:
                    skip += 1  # leave it and try the next one
            top = find_loot(h)
            if top is None:
                if not self.wait(0.4):
                    return
                top = find_loot(h)
                if top is None:
                    log("HUNT loot window closed after %d clicks" % (k + 1))
                    return        log("HUNT loot window still open after 14 clicks")

    def hunt_destroy(self, h, top, row):
        """Right click the item -> CONFIRMAR dialog -> SI. The items below move up. True if the dialog was answered."""
        self.hunt_say("destroying a unique item")
        self.hunt_move(h, 0.41, top + 0.095 + row * 0.069)
        mouse_click("R")
        if not self.wait(0.7):
            return False
        ty = find_dialog(h, top + 0.05)
        if ty is None:
            log("HUNT destroy: the CONFIRMAR dialog did not appear")
            return False
        self.hunt_move(h, 0.4665, ty + 0.106)  # the SI button: left of the middle, a little below the title bar
        mouse_click("L")
        if not self.wait(0.8):
            return False
        gone = find_dialog(h, top + 0.05) is None
        log("HUNT destroy: SI clicked, dialog %s" % ("closed" if gone else "STILL OPEN"))
        return gone

    DANGER_R = 0.25  # minimap units (fraction of the minimap width): keep at least this far from a deadly spot
    ALARM_R = 0.20  # if we are this close to one, stop everything

    @staticmethod
    def seg_dist(p, a, b):
        """Distance from point p to the segment a-b."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
        return ((p[0] - a[0] - t * dx) ** 2 + (p[1] - a[1] - t * dy) ** 2) ** 0.5

    def unsafe(self, a, b, deadly):
        """True if the straight walk a -> b passes within DANGER_R of a deadly spot."""
        for d in deadly:
            start = ((a[0] - d[0]) ** 2 + (a[1] - d[1]) ** 2) ** 0.5
            # already inside the keep-away radius (e.g. standing at the safe limit): only walking away is allowed
            if self.seg_dist(d, a, b) < min(d[2], start - 0.01):
                return True
        return False

    def hunt_deadly_near(self, h, factor):
        """Are we within `factor` x the alarm radius of a deadly spot (red diamond or visor fan)?"""
        player, _, _, deadly = read_minimap(*grab_minimap(h))
        return bool(player) and any(((player[0] - d[0]) ** 2 + (player[1] - d[1]) ** 2) ** 0.5 < factor * d[3]
                                    for d in deadly)

    def hunt_zone_changed(self, h, zone0):
        """The zone name (top right) differs from the one at start: we died / left the zone. Stops the hunt."""
        if zone0 is None or self.hunt_in_combat(h)[0]:
            return False  # the name bar is hidden during a fight
        def diff():
            d = zone_differs(zone0, grab_zone(h))
            return d is not None and d > 0.25  # None: map hidden, we cannot tell
        if not diff():
            return False
        for _ in range(3):  # a real change stays: look again a few times before believing it
            if not self.wait(1.5) or self.hunt_in_combat(h)[0] or not diff():
                log("HUNT zone map looked different for a moment: ignored")
                return False
        log("HUNT zone map changed: stopping")
        self.halt("Zone changed (did you die?): hunt stopped")
        return True

    def hunt_isolated(self, p, others, gap):
        """True if no other point in `others` is closer than `gap` (fraction of the screen width) to p."""
        return all(((p[0] - q[0]) ** 2 + ((p[1] - q[1]) * 0.563) ** 2) ** 0.5 >= gap
                   for q in others if q is not p and q != p)

    NEAR = 0.22  # bots this close to the player (fraction of the screen width) are attackable even outside the area
    HOP = 0.12  # minimap units walked per click

    def hunt_candidates(self, h, bad):
        """Bots we may attack: in the chosen area, or right next to the player; and far enough from every other bot
        (so only one enters the fight)."""
        ax0, ay0, ax1, ay1 = self.cfg["hunt_area"]
        allbots = find_bots(h)
        now = time.time()
        me = find_self(h)
        mine = (me[0], me[1] + BODY_DROP) if me else None
        near = lambda p: bool(mine) and ((p[0] - mine[0]) ** 2 + ((p[1] - mine[1]) * 0.563) ** 2) ** 0.5 <= self.NEAR
        # a body point below 0.78 would be a click on the bottom bar, not on the bot
        eligible = [p for p in allbots if p[1] <= 0.78 and ((ax0 <= p[0] <= ax1 and ay0 <= p[1] <= ay1) or near(p))]
        fresh = lambda p: all(abs(p[0] - b[0]) > 0.05 or abs(p[1] - b[1]) > 0.08 for b in bad if b[2] > now)
        self.hunt_counts = (len(allbots), len(eligible))
        self.hunt_outside = [p for p in allbots if p not in eligible and fresh(p)
                             and self.hunt_isolated(p, allbots, self.cfg["hunt_gap"])]
        return [p for p in eligible if self.hunt_isolated(p, allbots, self.cfg["hunt_gap"]) and fresh(p)], len(allbots)

    def hunt_goto(self, h, target, bad, retreat=False, stop_for_target=True):
        """Walk to a minimap point in short hops. The game picks its own route, so one long click could pass right by
        a visor: every hop is checked against the deadly spots first.
        Returns 'arrived', 'stuck', 'blocked', 'danger', 'combat', 'target' or 'stopped'."""
        mx, my, mw, mh = MAP_AREA
        dist = lambda a, b: ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
        stuck = 0
        for _ in range(30):
            player, _, dots, deadly = read_minimap(*grab_minimap(h))
            if not player:
                return "stuck"
            if not retreat and any(dist(player, d) < d[3] for d in deadly):
                return "danger"
            left = dist(player, target)
            if left < 0.04:
                return "arrived"
            k = min(1.0, self.HOP / left)
            nxt = (player[0] + (target[0] - player[0]) * k, player[1] + (target[1] - player[1]) * k)
            if not retreat and self.unsafe(player, nxt, deadly):
                return "blocked"
            if any(dist(nxt, o) < 0.045 for o in dots):
                return "blocked"
            self.hunt_move(h, mx + nxt[0] * mw, my + nxt[1] * mh)
            mouse_click("L")
            last, still, t0 = player, 0.0, time.time()
            while time.time() - t0 < 8:
                if not self.wait(0.4):
                    return "stopped"
                if self.hunt_in_combat(h)[0]:
                    return "combat"
                if stop_for_target and not retreat and self.hunt_candidates(h, bad)[0]:
                    return "target"
                pl, _, _, dd = read_minimap(*grab_minimap(h))
                if not retreat and pl and any(dist(pl, d) < d[3] for d in dd):
                    return "danger"
                if pl and abs(pl[0] - last[0]) < 0.008 and abs(pl[1] - last[1]) < 0.008:
                    still += 0.4
                    if still >= 1.2:
                        break
                else:
                    still = 0.0
                last = pl or last
            if dist(last, player) < 0.015:
                stuck += 1
                if stuck >= 2:
                    return "stuck"
            else:
                stuck = 0
        return "arrived"

    def hunt_retreat(self, h):
        """Walk back to the last safe position (or the start) after getting too close to a deadly spot."""
        target = self.safe_pos or self.home
        if not target:
            return False
        self.hunt_say("DANGER: moving away from a deadly bot")
        for attempt in (1, 2):
            r = self.hunt_goto(h, target, [], retreat=True, stop_for_target=False)
            log("HUNT retreat %d towards (%.3f,%.3f): %s" % (attempt, target[0], target[1], r))
            if r == "stopped":
                return False
            if not self.hunt_deadly_near(h, 1.0):
                return True
        return False

    def hunt_alarm(self, h):
        """Too close to a deadly spot (red diamond or visor)? Retreat to the last safe position and go on; stop only if
        the retreat does not work. True if danger was found (and dealt with or stopped)."""
        player, _, _, deadly = read_minimap(*grab_minimap(h))
        if player and any(((player[0] - d[0]) ** 2 + (player[1] - d[1]) ** 2) ** 0.5 < d[3] for d in deadly):
            log("HUNT DANGER: deadly diamond / visor close to the player (%.3f,%.3f)" % player)
            if not self.hunt_retreat(h):
                self.halt("DANGER: a deadly bot (red or with a visor) is close and I could not back off. Hunt stopped")
            return True
        if player and all(((player[0] - d[0]) ** 2 + (player[1] - d[1]) ** 2) ** 0.5 > 1.6 * d[3] for d in deadly):
            self.safe_pos = player
        return False

    def hunt_walk(self, h, tried, bad):
        """Walk (in hops) next to the nearest isolated bot diamond that is not near a deadly spot or an exit.
        True if it did something."""
        buf, rw, rh = grab_minimap(h)
        player, diamonds, dots, deadly = read_minimap(buf, rw, rh)
        now = time.time()
        tried[:] = [t for t in tried if t[2] > now]
        dist = lambda a, b: ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
        gap = self.cfg["hunt_map_gap"]
        free = [d for d in diamonds
                if all(dist(d, q) > q[2] for q in deadly)  # never near a deadly spot
                and all(dist(d, q) >= gap for q in diamonds if q != d)  # alone
                and all(abs(d[0] - t[0]) > 0.04 or abs(d[1] - t[1]) > 0.04 for t in tried)]
        if now - getattr(self, "_mlog", 0) > 3:
            self._mlog = now
            log("HUNT minimap: player=%s diamonds=%d alone-and-new=%d deadly=%d dots=%d" % (
                "yes" if player else "NOT FOUND", len(diamonds), len(free), len(deadly), len(dots)))
        if not player or not free:
            return False
        d = min(free, key=lambda q: dist(q, player))
        tried.append((d[0], d[1], now + 45))
        # stop a little short of the diamond, on the player side
        k = min(0.07 / max(dist(d, player), 1e-6), 0.9)
        goal = (d[0] + (player[0] - d[0]) * k, d[1] + (player[1] - d[1]) * k)
        self.hunt_say("walking to a bot (minimap)")
        log("HUNT walk: diamond (%.3f,%.3f) player (%.3f,%.3f) goal (%.3f,%.3f)" % (d + player + goal))
        r = self.hunt_goto(h, goal, bad)
        log("HUNT walk result: %s" % r)
        if r == "danger":
            self.hunt_alarm(h)
            return True
        return r in ("arrived", "combat", "target", "stopped")

    def hunt_go_home(self, h, home):
        """Walk back to where the hunt started. True if we moved."""
        player, _, dots, deadly = read_minimap(*grab_minimap(h))
        if not player or ((player[0] - home[0]) ** 2 + (player[1] - home[1]) ** 2) ** 0.5 < 0.05:
            return False
        if any(((home[0] - o[0]) ** 2 + (home[1] - o[1]) ** 2) ** 0.5 < 0.045 for o in dots):
            return False  # the starting point is right next to an exit: do not click there
        self.hunt_say("going back to the starting point")
        log("HUNT going back to the start: player (%.3f,%.3f) home (%.3f,%.3f)" % (player + home))
        r = self.hunt_goto(h, home, [], stop_for_target=False)
        log("HUNT going home result: %s" % r)
        if r == "danger":
            self.hunt_alarm(h)
        return r in ("arrived", "combat", "stopped", "danger")

    def hunt_patrol_step(self, h, st, home):
        """One leg of the patrol: walk (in hops) to a minimap point far from the ones already visited. Bot diamonds only
        show up on the minimap after moving, so we walk a tour of K points, dwelling at each one so that the scene
        scan can find bots. Unreachable or unsafe points are dropped."""
        dist = lambda a, b: ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
        player, _, dots, deadly = read_minimap(*grab_minimap(h))
        if not player:
            return False
        if "pts" not in st:  # new tour: grid of candidate points, farthest-first from the start
            grid = [(0.12 + 0.11 * i, 0.12 + 0.11 * j) for i in range(8) for j in range(8)]
            grid = [p for p in grid if all(dist(p, o) > 0.08 for o in dots)]
            order, ref = [], [home or player]
            while grid and len(order) < 40:
                p = max(grid, key=lambda q: min(dist(q, r) for r in ref))
                grid.remove(p)
                order.append(p)
                ref.append(p)
            st["pts"], st["done"] = order, 0
            log("HUNT patrol: new tour, %d candidate points" % len(order))
        for _ in range(4):  # try up to 4 candidates for this leg
            if st["done"] >= self.cfg["hunt_tour"] or not st["pts"]:
                return False
            p = st["pts"].pop(0)
            if any(dist(p, d) < d[2] for d in deadly) or self.unsafe(player, p, deadly):
                log("HUNT patrol point (%.2f,%.2f) skipped: a deadly spot is near it or the way" % p)
                continue
            self.hunt_say("patrol: walking to point %d/%d" % (st["done"] + 1, self.cfg["hunt_tour"]))
            r = self.hunt_goto(h, p, [], stop_for_target=True)
            now_pl = read_minimap(*grab_minimap(h))[0] or player
            moved = dist(now_pl, player)
            log("HUNT patrol point (%.2f,%.2f): %s, moved %.3f on the minimap" % (p[0], p[1], r, moved))
            if r == "danger":
                self.hunt_alarm(h)
                return True
            if r in ("combat", "target", "stopped"):
                return True
            if moved >= 0.03:
                st["done"] += 1
                st["dwell"] = time.time() + 3.0
                return True
            player = now_pl
        return False
    def w_hunt(self):
        """Find living bots by their name label, attack the nearest isolated one, fight, loot; with the minimap walk
        to the next bot when none is in the area."""
        h = self.game()
        set_forbidden(self.cfg.get("hunt_forbidden"))
        park = (0.55, 0.935)  # chat area: no hover tooltips while we look at the scene
        patrol = {}  # state of the patrol tour
        chase = 0  # approach steps towards bots outside the area since the last target
        bad, tried = [], []  # (fx, fy, until): spots where an attack did not start a fight / minimap targets done
        log("HUNT start area=%s gap=%s walk=%s" % (self.cfg["hunt_area"], self.cfg["hunt_gap"], self.cfg["hunt_walk"]))
        zone0 = grab_zone(h)  # the zone name on top: if it changes we died / left the zone
        home = read_minimap(*grab_minimap(h))[0]  # where we started, on the minimap
        self.home = self.safe_pos = home
        log("HUNT home on minimap: %s" % (home,))
        while self.alive():
            if self.hunt_in_combat(h)[0]:  # a bot attacked us (e.g. while walking): fight it
                self.hunt_say("attacked: fighting")
                if not self.hunt_fight(h):
                    return
                self.hunt_loot(h)
                continue
            if self.hunt_zone_changed(h, zone0):
                return
            if self.hunt_alarm(h):  # backed off from a deadly bot (or stopped): look again
                continue
            hp = read_health(h)
            if hp < self.cfg["hunt_min_health"]:  # a tough bot left us low: do nothing new until we have healed
                self.hunt_say("health %d%% is below %d%%: waiting to heal" % (hp * 100, self.cfg["hunt_min_health"] * 100))
                if time.time() - getattr(self, "_hlog", 0) > 15:
                    self._hlog = time.time()
                    log("HUNT health %.0f%% < %.0f%%: waiting" % (hp * 100, self.cfg["hunt_min_health"] * 100))
                if not self.wait(1.5):
                    return
                continue
            self.hunt_move(h, *park)
            bad = [b for b in bad if b[2] > time.time()]
            bots, seen = self.hunt_candidates(h, bad)
            if not bots:
                if seen and time.time() - getattr(self, "_clog", 0) > 3:
                    self._clog = time.time()
                    log("HUNT no candidate: %d bots on screen, %d in area/near, gap=%.2f, recently failed=%d" % (
                        self.hunt_counts + (self.cfg["hunt_gap"], len(bad))))
                if self.cfg["hunt_walk"] and self.hunt_walk(h, tried, bad):
                    continue
                if self.cfg["hunt_walk"] and self.hunt_outside and not self.hunt_deadly_near(h, 2.0):
                    # no lone bot in the area and none on the minimap: walk towards one that is on screen outside it
                    chase += 1
                    tgt = min(self.hunt_outside, key=lambda p: (p[0] - 0.5) ** 2 + (p[1] - 0.65) ** 2)
                    if chase > 4:
                        bad += [(p[0], p[1], time.time() + 30) for p in self.hunt_outside]
                        chase = 0
                    elif self.hunt_approach(h, tgt):
                        log("HUNT chase %d towards (%.3f,%.3f)" % (chase, tgt[0], tgt[1]))
                        continue
                if self.cfg["hunt_walk"] and self.cfg["hunt_patrol"]:
                    now = time.time()
                    if now < patrol.get("dwell", 0) or now < patrol.get("rest", 0):
                        self.hunt_say("patrol: looking around")
                        if not self.wait(0.8):
                            return
                        continue
                    if self.hunt_patrol_step(h, patrol, home):
                        continue
                    if "pts" in patrol:  # tour finished (or nothing reachable): rest at the start, then start over
                        patrol.pop("pts")
                        patrol["rest"] = time.time() + 30
                        log("HUNT patrol: tour finished")
                        if self.cfg["hunt_home"] and home and self.hunt_go_home(h, home):
                            continue
                if self.cfg["hunt_walk"] and self.cfg["hunt_home"] and home and self.hunt_go_home(h, home):
                    continue
                self.hunt_say("no bot to attack (on screen %d, in area %d, alone-and-new 0)" % self.hunt_counts)
                if not self.wait(0.8):
                    return
                continue
            chase = 0
            target = bots[0]
            log("HUNT bots=%d target=(%.3f,%.3f)" % (len(bots), target[0], target[1]))
            if not self.hunt_engage(h, target):
                if not self.alive():
                    return
                log("HUNT no fight started at that spot: ignoring it for 30 s")
                bad.append((target[0], target[1], time.time() + 30))
                continue
            if not self.hunt_fight(h, (target[0], target[1])):
                return
            self.hunt_loot(h)  # /loot opens the window whatever the corpse position
            if not self.wait(0.5):
                return
    def w_double(self):
        missing = [s for s in ("8", "9") if s not in self.cfg["sequences"]]
        if missing:
            self.msg = "Record sequences 8 (turn 1) and 9 (turn 2) first"
            return
        self.w_play(["8", "9"])

    def loop(self):
        self.root.after(15, self.tick)
        self.root.mainloop()


class Gui:
    """Control window: autoclick delay, the 9 sequence slots with names, and a library of named sequences."""

    def __init__(self, app):
        self.app, self.cfg = app, app.cfg
        w = self.win = tk.Toplevel(app.root)
        w.title("AutoPrison")
        w.geometry("780x720")
        w.minsize(680, 680)
        w.protocol("WM_DELETE_WINDOW", app.root.destroy)  # closing this window quits the program

        top = ttk.LabelFrame(w, text="Autoclick (menu option 1)")
        top.pack(fill="x", padx=10, pady=(10, 4))
        self.delay = tk.StringVar(value=str(int(round(self.cfg["click_interval"] * 1000))))
        self.jit = tk.StringVar(value=str(int(round(self.cfg["jitter"] * 100))))
        self.speed = tk.StringVar(value="%g" % self.cfg["speed"])
        self.settle = tk.StringVar(value=str(int(round(self.cfg["bg_settle"] * 1000))))
        self.rep = tk.StringVar(value="%g" % max(self.cfg["repeat_interval"], 5.0))
        for col, (label, var, lo, hi, inc, key) in enumerate((
                ("Delay between clicks (ms)", self.delay, 10, 60000, 10, "delay"),
                ("Random variation (Â±%)", self.jit, 0, 90, 5, "jit"),
                ("Sequence speed (x)", self.speed, 0.1, 8, 0.05, "speed"),
                ("Background pause before click (ms)", self.settle, 0, 2000, 25, "settle"),
                ("Auto-fight delay (s, min 5)", self.rep, 5, 300, 0.5, "rep"))):
            ttk.Label(top, text=label).grid(row=0, column=col, padx=8, pady=(6, 0), sticky="w")
            sp = ttk.Spinbox(top, from_=lo, to=hi, increment=inc, textvariable=var, width=10,
                             command=self.apply)
            sp.grid(row=1, column=col, padx=8, pady=(0, 8), sticky="w")
            sp.bind("<KeyRelease>", lambda e: self.apply())
            sp.bind("<FocusOut>", lambda e: self.apply())
        ttk.Label(top, text="Delay and variation apply to autoclick; speed applies to recorded sequences.",
                  foreground="gray").grid(row=2, column=0, columnspan=4, padx=8, pady=(0, 6), sticky="w")
        self.bgvar = tk.BooleanVar(value=bool(self.cfg["background"]))
        ttk.Checkbutton(top, variable=self.bgvar, command=self.apply, text=(
            "Background mode (experimental): clicks are sent to the game window without moving your mouse, "
            "so you can use other programs. Keep the game window open, not minimized. F12 stops from anywhere."
        )).grid(row=3, column=0, columnspan=4, padx=8, pady=(0, 8), sticky="w")

        hunt = ttk.LabelFrame(w, text="Auto-hunt area (menu option 7: bots outside this rectangle are ignored)")
        hunt.pack(fill="x", padx=10, pady=4)
        self.cv = tk.Canvas(hunt, width=240, height=135, bg="#1b1b1b", highlightthickness=1,
                            highlightbackground="#666")
        self.cv.grid(row=0, column=0, rowspan=3, padx=8, pady=8)
        self.harea = [tk.StringVar() for _ in range(4)]
        for col, (label, var) in enumerate(zip(("Left (%)", "Top (%)", "Right (%)", "Bottom (%)"), self.harea)):
            ttk.Label(hunt, text=label).grid(row=0, column=1 + col, padx=6, pady=(8, 0), sticky="w")
            sp = ttk.Spinbox(hunt, from_=0, to=100, increment=1, textvariable=var, width=7, command=self.apply_area)
            sp.grid(row=1, column=1 + col, padx=6, sticky="w")
            sp.bind("<KeyRelease>", lambda e: self.apply_area())
        ttk.Button(hunt, text="Clear area", command=self.clear_area).grid(row=1, column=5, padx=6, sticky="w")
        self.hinfo = ttk.Label(hunt, foreground="gray", wraplength=470, justify="left")
        self.hinfo.grid(row=2, column=1, columnspan=5, padx=6, pady=(4, 8), sticky="w")
        self.gap = tk.StringVar(value="%g" % round(self.cfg["hunt_gap"] * 100, 1))
        self.mgap = tk.StringVar(value="%g" % round(self.cfg["hunt_map_gap"] * 100, 1))
        opts = ttk.Frame(hunt)
        opts.grid(row=3, column=0, columnspan=6, padx=8, pady=(0, 8), sticky="w")
        ttk.Label(opts, text="Min distance between bots, screen (% of width)").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(opts, from_=0, to=100, increment=1, textvariable=self.gap, width=6, command=self.apply).grid(
            row=0, column=1, padx=(6, 18))
        ttk.Label(opts, text="on the minimap (%)").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(opts, from_=0, to=100, increment=1, textvariable=self.mgap, width=6, command=self.apply).grid(
            row=0, column=3, padx=(6, 0))
        self.hmin = tk.StringVar(value="%g" % round(self.cfg["hunt_min_health"] * 100))
        ttk.Label(opts, text="Wait to attack while health is below (%)").grid(row=4, column=0, columnspan=2, sticky="w",
                                                                              pady=(6, 0))
        ttk.Spinbox(opts, from_=0, to=100, increment=5, textvariable=self.hmin, width=6, command=self.apply).grid(
            row=4, column=2, padx=(6, 0), pady=(6, 0), sticky="w")
        self.walkvar = tk.BooleanVar(value=bool(self.cfg["hunt_walk"]))
        ttk.Checkbutton(opts, variable=self.walkvar, command=self.apply, text=(
            "Walk to the next lone bot by clicking the minimap when none is in the area "
            "(avoids the fixed orange points = exits)")).grid(row=1, column=0, columnspan=4, pady=(6, 0), sticky="w")
        self.patrolvar = tk.BooleanVar(value=bool(self.cfg["hunt_patrol"]))
        ttk.Checkbutton(opts, variable=self.patrolvar, command=self.apply, text=(
            "Patrol: when nothing is found, walk a tour of minimap points (bots show on the minimap only after "
            "moving)")).grid(row=3, column=0, columnspan=4, pady=(2, 0), sticky="w")
        self.destroyvar = tk.BooleanVar(value=bool(self.cfg["hunt_destroy_unique"]))
        ttk.Checkbutton(opts, variable=self.destroyvar, command=self.apply, text=(
            "Loot: destroy UNIQUE items we already own (right click, then Yes) so the next one can be picked up"
        )).grid(row=5, column=0, columnspan=4, pady=(2, 0), sticky="w")
        zrow = ttk.Frame(opts)
        zrow.grid(row=6, column=0, columnspan=4, pady=(6, 0), sticky="w")
        ttk.Button(zrow, text="Forbidden zones on the minimapâ€¦", command=self.zones_dialog).pack(side="left")
        self.zinfo = ttk.Label(zrow, foreground="gray")
        self.zinfo.pack(side="left", padx=8)
        self.zones_label()
        set_forbidden(self.cfg.get("hunt_forbidden"))
        self.homevar = tk.BooleanVar(value=bool(self.cfg["hunt_home"]))
        ttk.Checkbutton(opts, variable=self.homevar, command=self.apply, text=(
            "When no lone bot is left, walk back to the starting point of the hunt")).grid(
            row=2, column=0, columnspan=4, pady=(2, 0), sticky="w")
        for e in opts.winfo_children():
            if isinstance(e, ttk.Spinbox):
                e.bind("<KeyRelease>", lambda ev: self.apply())
        self.hunt_last = "unset"
        self.hunt_sync()

        body = ttk.Frame(w)
        body.pack(fill="both", expand=True, padx=10, pady=4)
        body.columnconfigure((0, 1), weight=1, uniform="c")
        body.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(body, text="Slots (keys 1-9 in game)")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.slots = self.tree(left, ("slot", "name", "clicks"), ("Slot", "Name", "Clicks"), (45, 190, 55))
        self.slots.bind("<Double-1>", lambda e: self.rename_slot())
        bar = ttk.Frame(left)
        bar.pack(fill="x", padx=6, pady=6)
        for text, cmd in (("Rename", self.rename_slot), ("Clear", self.clear_slot),
                          ("Save to library â†’", self.to_library)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 4))

        right = ttk.LabelFrame(body, text="Library (saved sequences)")
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.lib = self.tree(right, ("name", "clicks"), ("Name", "Clicks"), (210, 55))
        self.lib.bind("<Double-1>", lambda e: self.rename_lib())
        bar = ttk.Frame(right)
        bar.pack(fill="x", padx=6, pady=6)
        for text, cmd in (("â† Load into slot", self.from_library), ("Rename", self.rename_lib),
                          ("Delete", self.delete_lib)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 4))

        ttk.Label(w, foreground="gray", wraplength=720, text=(
            "Record in game: TAB, 2, then 1-9. Play: TAB, 3, then 1-9. Name a slot, save it to the library, "
            "and load it back into any slot later.")).pack(fill="x", padx=12, pady=(2, 10))
        self.refresh()

    @staticmethod
    def tree(parent, cols, heads, widths):
        t = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse", height=9)
        for c, h, wd in zip(cols, heads, widths):
            t.heading(c, text=h)
            t.column(c, width=wd, anchor="w" if c == "name" else "center")
        t.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        return t

    # -- settings
    def apply(self):
        self.cfg["background"] = bool(self.bgvar.get())
        try:
            self.cfg["click_interval"] = min(max(float(self.delay.get()), 10), 60000) / 1000
            self.cfg["jitter"] = min(max(float(self.jit.get()), 0), 90) / 100
            self.cfg["speed"] = min(max(float(self.speed.get().replace(",", ".")), 0.1), 8)
            self.cfg["bg_settle"] = min(max(float(self.settle.get()), 0), 2000) / 1000
            self.cfg["repeat_interval"] = min(max(float(self.rep.get().replace(",", ".")), 5), 300)
            self.cfg["hunt_gap"] = min(max(float(self.gap.get().replace(",", ".")), 0), 100) / 100
            self.cfg["hunt_map_gap"] = min(max(float(self.mgap.get().replace(",", ".")), 0), 100) / 100
            self.cfg["hunt_min_health"] = min(max(float(self.hmin.get().replace(",", ".")), 0), 100) / 100
            self.cfg["hunt_destroy_unique"] = bool(self.destroyvar.get())
            self.cfg["hunt_walk"] = bool(self.walkvar.get())
            self.cfg["hunt_home"] = bool(self.homevar.get())
            self.cfg["hunt_patrol"] = bool(self.patrolvar.get())
        except ValueError:
            return  # half-typed value: ignore until it is a number
        save(self.cfg)

    # -- auto-hunt area (the in-game setup, option 7, writes the same cfg value)
    def hunt_sync(self):
        cur = self.cfg.get("hunt_area")
        if cur != self.hunt_last:
            self.hunt_last = list(cur) if cur else cur
            for var, v in zip(self.harea, cur or ("", "", "", "")):
                var.set("" if v == "" else "%g" % round(v * 100, 2))
        self.draw_area()
        self.win.after(500, self.hunt_sync)

    def draw_area(self):
        cv, cur = self.cv, self.cfg.get("hunt_area")
        cv.delete("all")
        cv.create_text(120, 67, text="game window", fill="#555")
        if cur:
            cv.create_rectangle(cur[0] * 240, cur[1] * 135, cur[2] * 240, cur[3] * 135,
                                outline="#ffe14d", width=2, fill="#4d4410", stipple="gray50")
            text = "Saved: left %.1f%%, top %.1f%%, right %.1f%%, bottom %.1f%% of the game window." % tuple(
                v * 100 for v in cur)
            g = find_game()
            if g:
                _, _, w, hh = client_rect(g)
                text += " Now (%dx%d): x %d-%d, y %d-%d px." % (
                    w, hh, cur[0] * w, cur[2] * w, cur[1] * hh, cur[3] * hh)
        else:
            text = "No area saved yet. In game: TAB, 7, put the mouse on a corner and press F9 (top-left) and F10 (bottom-right)."
        self.hinfo.config(text=text)

    def apply_area(self):
        try:
            l, t, r, b = (min(max(float(v.get().replace(",", ".")), 0), 100) / 100 for v in self.harea)
        except ValueError:
            return  # half-typed value
        if r - l < 0.03 or b - t < 0.03:
            return
        self.cfg["hunt_area"] = [round(l, 4), round(t, 4), round(r, 4), round(b, 4)]
        self.hunt_last = list(self.cfg["hunt_area"])
        save(self.cfg)
        self.draw_area()

    def clear_area(self):
        self.cfg["hunt_area"] = None
        save(self.cfg)
        self.hunt_sync_now()

    def hunt_sync_now(self):
        self.hunt_last = "unset"
        cur = self.cfg.get("hunt_area")
        self.hunt_last = list(cur) if cur else cur
        for var in self.harea:
            var.set("")
        self.draw_area()

    # -- forbidden zones, drawn on a snapshot of the minimap
    def zones_label(self):
        n = len(self.cfg.get("hunt_forbidden") or [])
        self.zinfo.config(text="%d zone%s: the hunt never walks into them" % (n, "" if n == 1 else "s") if n
                          else "none: the hunt only avoids red diamonds and visors")

    def zones_dialog(self):
        CW = 460
        mx, my, mw, mh = MAP_AREA
        g = find_game()
        if g:
            _, _, gw, gh = client_rect(g)
            CH = int(CW * (mh * gh) / (mw * gw))
        else:
            CH = int(CW * 0.97)
        d = tk.Toplevel(self.win)
        d.title("Forbidden zones on the minimap")
        d.transient(self.win)
        ttk.Label(d, wraplength=CW, justify="left", text=(
            "Drag on the map to mark an area the character must never enter or cross (red). The hunt then walks, "
            "patrols and picks targets around it. Use Capture with the game visible to get the current minimap.")
                  ).pack(padx=10, pady=(10, 4))
        cv = tk.Canvas(d, width=CW, height=CH, bg="#1b1b1b", highlightthickness=1, highlightbackground="#666")
        cv.pack(padx=10, pady=4)
        st = {"img": None, "drag": None}

        def redraw():
            cv.delete("all")
            if st["img"]:
                cv.create_image(0, 0, anchor="nw", image=st["img"])
            else:
                cv.create_text(CW // 2, CH // 2, text="no snapshot: press Capture", fill="#777")
            for x0, y0, x1, y1 in self.cfg.get("hunt_forbidden") or []:
                cv.create_rectangle(x0 * CW, y0 * CH, x1 * CW, y1 * CH, outline="#ff4040", width=2,
                                    fill="#ff2020", stipple="gray50")
            self.zones_label()

        def store(rects):
            self.cfg["hunt_forbidden"] = rects
            save(self.cfg)
            set_forbidden(rects)
            redraw()

        def clamp(v, hi):
            return round(min(max(v, 0), hi) / hi, 4)

        def press(e):
            st["drag"] = (e.x, e.y)

        def move(e):
            cv.delete("drag")
            if st["drag"]:
                cv.create_rectangle(st["drag"][0], st["drag"][1], e.x, e.y, outline="#ffe14d", dash=(3, 2), tags="drag")

        def release(e):
            if not st["drag"]:
                return
            (sx, sy), st["drag"] = st["drag"], None
            x0, x1 = sorted((clamp(sx, CW), clamp(e.x, CW)))
            y0, y1 = sorted((clamp(sy, CH), clamp(e.y, CH)))
            cv.delete("drag")
            if x1 - x0 >= 0.03 and y1 - y0 >= 0.03:
                store((self.cfg.get("hunt_forbidden") or []) + [[x0, y0, x1, y1]])

        def undo():
            store((self.cfg.get("hunt_forbidden") or [])[:-1])

        def clear():
            store([])

        def snap():
            gg = find_game()
            if not gg or u32.IsIconic(gg):
                return messagebox.showinfo("AutoPrison", "Open the game window (not minimized) first.", parent=d)
            d.withdraw()
            self.win.withdraw()

            def take():
                try:
                    buf, rw, rh = grab_minimap(gg)
                    out = bytearray(b"P6\n%d %d\n255\n" % (CW, CH))
                    for y in range(CH):
                        row = (y * rh // CH) * rw
                        for x in range(CW):
                            i = (row + x * rw // CW) * 4
                            out += bytes((buf[i + 2], buf[i + 1], buf[i]))
                    st["img"] = tk.PhotoImage(data=bytes(out))
                finally:
                    self.win.deiconify()
                    d.deiconify()
                    redraw()
            self.win.after(2500, take)

        cv.bind("<ButtonPress-1>", press)
        cv.bind("<B1-Motion>", move)
        cv.bind("<ButtonRelease-1>", release)
        bar = ttk.Frame(d)
        bar.pack(pady=(4, 10))
        for text, cmd in (("Capture minimap (2.5 s)", snap), ("Undo last", undo), ("Clear all", clear),
                          ("Close", d.destroy)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=4)
        redraw()

    # -- helpers
    def sel(self, tree):
        s = tree.selection()
        return tree.item(s[0], "values")[0] if s else None

    def refresh(self):
        keep_s, keep_l = self.sel(self.slots), self.sel(self.lib)
        self.slots.delete(*self.slots.get_children())
        self.lib.delete(*self.lib.get_children())
        for n in range(1, 10):
            s = str(n)
            evs = self.cfg["sequences"].get(s)
            self.slots.insert("", "end", iid=s, values=(
                s, self.cfg["names"].get(s, "") if evs else "", self.clicks(evs) if evs else "â€”"))
        for name in sorted(self.cfg["library"], key=str.lower):
            self.lib.insert("", "end", iid=name, values=(name, self.clicks(self.cfg["library"][name])))
        if keep_s and self.slots.exists(keep_s):
            self.slots.selection_set(keep_s)
        if keep_l and self.lib.exists(keep_l):
            self.lib.selection_set(keep_l)

    @staticmethod
    def clicks(evs):
        return sum(1 for e in evs if "wait" not in e)

    def ask(self, title, prompt, initial=""):
        v = simpledialog.askstring(title, prompt, initialvalue=initial, parent=self.win)
        return v.strip() if v and v.strip() else None

    def busy(self):
        if self.app.state in ("REC", "RUN"):
            messagebox.showinfo("AutoPrison", "Stop the recording or playback first.", parent=self.win)
            return True
        return False

    # -- slot actions
    def rename_slot(self):
        s = self.sel(self.slots)
        if not s or s not in self.cfg["sequences"]:
            return messagebox.showinfo("AutoPrison", "Select a slot that has a recorded sequence.", parent=self.win)
        name = self.ask("Rename", "Name for slot %s:" % s, self.cfg["names"].get(s, ""))
        if name:
            self.cfg["names"][s] = name
            save(self.cfg)
            self.refresh()

    def clear_slot(self):
        s = self.sel(self.slots)
        if self.busy() or not s or s not in self.cfg["sequences"]:
            return
        if messagebox.askyesno("Clear slot", "Clear slot %s? Save it to the library first to keep it." % s,
                               parent=self.win):
            self.cfg["sequences"].pop(s, None)
            self.cfg["names"].pop(s, None)
            save(self.cfg)
            self.refresh()

    def to_library(self):
        s = self.sel(self.slots)
        if not s or s not in self.cfg["sequences"]:
            return messagebox.showinfo("AutoPrison", "Select a slot that has a recorded sequence.", parent=self.win)
        name = self.cfg["names"].get(s) or self.ask("Save to library", "Name for this sequence:", "Sequence %s" % s)
        if not name:
            return
        if name in self.cfg["library"] and not messagebox.askyesno(
                "Overwrite", "'%s' already exists in the library. Overwrite it?" % name, parent=self.win):
            return
        self.cfg["names"][s] = name
        self.cfg["library"][name] = copy.deepcopy(self.cfg["sequences"][s])
        save(self.cfg)
        self.refresh()

    # -- library actions
    def from_library(self):
        name, s = self.sel(self.lib), self.sel(self.slots)
        if self.busy():
            return
        if not name or not s:
            return messagebox.showinfo("AutoPrison", "Select a library entry and a target slot.", parent=self.win)
        if s in self.cfg["sequences"] and not messagebox.askyesno(
                "Replace", "Slot %s already has a sequence. Replace it?" % s, parent=self.win):
            return
        self.cfg["sequences"][s] = copy.deepcopy(self.cfg["library"][name])
        self.cfg["names"][s] = name
        save(self.cfg)
        self.refresh()

    def rename_lib(self):
        old = self.sel(self.lib)
        if not old:
            return
        new = self.ask("Rename", "New name:", old)
        if not new or new == old:
            return
        if new in self.cfg["library"]:
            return messagebox.showinfo("AutoPrison", "A library entry named '%s' already exists." % new,
                                       parent=self.win)
        self.cfg["library"][new] = self.cfg["library"].pop(old)
        for s, n in self.cfg["names"].items():
            if n == old:
                self.cfg["names"][s] = new
        save(self.cfg)
        self.refresh()

    def delete_lib(self):
        name = self.sel(self.lib)
        if name and messagebox.askyesno("Delete", "Delete '%s' from the library?" % name, parent=self.win):
            self.cfg["library"].pop(name, None)
            save(self.cfg)
            self.refresh()


if __name__ == "__main__":
    rotate_log()
    log("AutoPrison started")
    print("AutoPrison is running. Close the AutoPrison window to quit (everything is already saved).")
    App().loop()
