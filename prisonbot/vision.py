"""Colour detectors for the combat banner, turn buttons, bot labels, health bar, chat errors and the loot window."""
import copy, ctypes, json, os, random, re, sys, threading, time
from ctypes import wintypes
from .config import *
from .winapi import *


# --- screen detectors for auto-hunt (colour heuristics measured on real game screenshots, 2360x1328 layout)
def _red(r, g, b):  # the "COMBATE" banner (it reads "GENERAL" in grey outside combat)
    return r > 170 and g < 110 and b < 90


def _diamond(r, g, b):  # the red border of a bot's minimap diamond; the health bar fill is the same red
    return r >= 150 and g <= 65 and b <= 65 and r - g >= 100


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


BOT_SIG = {}  # body spot -> shape of its name label (set by find_bots): the same name looks the same wherever it is


def label_sig(buf, w, hh, lx, ly, scale):
    """The label's text pixels around its centre, relative to their top-left corner."""
    cx, cy = int(lx * w), int(ly * hh)
    rx, ry = int(50 * scale), int(16 * scale)
    s = set()
    for y in range(max(cy - ry, 0), min(cy + ry, hh)):
        for x in range(max(cx - rx, 0), min(cx + rx, w)):
            i = (y * w + x) * 4
            if _label(buf[i + 2], buf[i + 1], buf[i]):
                s.add((x, y))
    if not s:
        return None
    mx, my = min(p[0] for p in s), min(p[1] for p in s)
    return frozenset((x - mx, y - my) for x, y in s)


def sig_similar(a, b):
    """Same name label? (measured: the same NPC in two views 1.00, two different bots 0.82, NPC vs bot 0.4)"""
    if not a or not b or not 0.8 <= len(a) / len(b) <= 1.25:
        return False
    da = {(x + i, y + j) for x, y in a for i in (-1, 0, 1) for j in (-1, 0, 1)}
    db = {(x + i, y + j) for x, y in b for i in (-1, 0, 1) for j in (-1, 0, 1)}
    return min(sum(1 for p in a if p in db) / len(a), sum(1 for p in b if p in da) / len(b)) >= 0.92


def find_bots(h):
    """Living bots on screen, as client-area fractions of a point on their body, nearest to the player first."""
    fx, fy, fw, fh = LABEL_AREA
    x, y, w, hh = client_rect(h)
    rw, rh = int(fw * w), int(fh * hh)
    buf = grab(x + int(fx * w), y + int(fy * hh), rw, rh)
    labels = find_labels(buf, rw, rh, w / 2000.0)
    BOT_SIG.clear()
    bots = []
    for lx, ly, _ in labels:
        p = (fx + lx * fw, min(fy + ly * fh + BODY_DROP, 0.9))
        BOT_SIG[p] = label_sig(buf, rw, rh, lx, ly, w / 2000.0)
        bots.append(p)
    return sorted(bots, key=lambda p: (p[0] - 0.5) ** 2 + (p[1] - 0.65) ** 2)


BAR_DROP = BODY_DROP - 0.027  # the red health bar sits 0.027 of the screen height below the name label


def find_bars(h):
    """Fallback inside a fight, where the name label is drawn in another colour: the red health bars shown under
    every combatant. -> body points (client fractions) of the bars that are not yours, nearest to the centre first."""
    fx, fy, fw, fh = LABEL_AREA
    x, y, w, hh = client_rect(h)
    rw, rh = int(fw * w), int(fh * hh)
    buf = grab(x + int(fx * w), y + int(fy * hh), rw, rh)
    need = int(55 * w / 2000.0)
    rows = []
    for j in range(rh):
        run = best = bx = 0
        for i in range(rw):
            k = (j * rw + i) * 4
            if _diamond(buf[k + 2], buf[k + 1], buf[k]):
                run += 1
                if run > best:
                    best, bx = run, i - run // 2
            else:
                run = 0
        if best >= need:
            rows.append((j, bx))
    bars = []  # rows that touch each other belong to the same bar
    for j, bx in rows:
        if bars and j - bars[-1][1] <= 3 and abs(bx - bars[-1][2]) <= need // 2:
            bars[-1][1] = j
        else:
            bars.append([j, j, bx])
    out = [(fx + b[2] / rw * fw, fy + (b[0] + b[1]) / 2 / rh * fh) for b in bars if b[1] - b[0] <= 0.02 * hh]
    me = None
    try:
        me = [(m[0], m[1]) for m in find_labels(buf, rw, rh, w / 2000.0, _mine)]
    except Exception:
        pass
    out = [p for p in out if not any(abs(p[0] - (fx + mx * fw)) < 0.03 and 0 < p[1] - (fy + my * fh) < 0.07
                                     for mx, my in (me or []))]
    return sorted(((p[0], min(p[1] + BAR_DROP, 0.9)) for p in out), key=lambda p: (p[0] - 0.5) ** 2 + (p[1] - 0.65) ** 2)


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


__all__ = [n for n in list(globals()) if not n.startswith("__")]
