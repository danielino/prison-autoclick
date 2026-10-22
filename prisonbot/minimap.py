"""The minimap: player, bot diamonds, deadly spots, forbidden zones, zone fingerprint, own label."""
import copy, ctypes, json, os, random, re, sys, threading, time
from ctypes import wintypes
from .config import *
from .winapi import *
from .vision import *


# --- minimap (top right): bots are diamonds with a red border, the player is a blue arrow, orange dots are fixed
# points of the map (exits / usable objects) that we never click on
MAP_AREA = (0.804, 0.083, 0.18, 0.31)


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


_map_cache = {}


def map_area(h):
    """The minimap rectangle as client fractions. Its width is fixed but its HEIGHT depends on the zone (the frame
    ends at 0.27 in some rooms, at 0.39 in others), so the bottom frame edge is searched on the screen."""
    now = time.time()
    c = _map_cache.get(h)
    if c and now - c[0] < 1.5:
        return c[1]
    fx, fy, fw, fh = base = area("minimap", MAP_AREA)
    x, y, w, hh = client_rect(h)
    ends = []
    for k in range(9):
        cx = int((0.87 + 0.0105 * k) * w)
        col = grab(x + cx, y + int(0.10 * hh), 1, int(0.50 * hh))
        run = 0
        for j in range(len(col) // 4):
            r, g, b = col[j * 4 + 2], col[j * 4 + 1], col[j * 4]
            if r > b + 18 and r > 70 and not _dot(r, g, b):  # the brown/gold frame (not an orange dot inside the map)
                run += 1
                if run >= 4:
                    ends.append(0.10 + (j - 3) / hh)
                    break
            else:
                run = 0
    found = base
    if ends:
        best = max(ends, key=lambda e: sum(1 for o in ends if abs(o - e) < 0.012))  # the most common edge
        if sum(1 for o in ends if abs(o - best) < 0.012) >= 3 and 0.2 < best < 0.45:
            found = (fx, fy, fw, round(best - 0.004 - fy, 4))
    _map_cache[h] = (now, found)
    return found


def grab_minimap(h):
    fx, fy, fw, fh = map_area(h)
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


__all__ = [n for n in list(globals()) if not n.startswith("__")]
