"""Window size information and a diagnostic report (a screenshot plus what every detector sees), for checking the program
on a screen size other than the one it was calibrated on."""
import os, time
from .config import HERE, log
from .vision import (client_rect, detect, find_bars, find_bots, read_attacks, read_health, chat_turn_is_mine,
                     LAST_BARS)
from . import llm

REF = (2360, 1328)  # the window size the colour detectors were measured on
APP = "AutoPrison"


def window_info(h):
    """(text, ok): the window size, its shape and how it compares with the calibrated one. ok is False when the shape
    (aspect ratio) differs, because the screen layout (HUD, chat, minimap positions) was measured on 16:9 only."""
    x, y, w, hh = client_rect(h)
    aspect, ref = w / float(hh or 1), REF[0] / float(REF[1])
    scale = hh / float(REF[1])
    ok = abs(aspect / ref - 1) <= 0.04
    text = "window %dx%d, aspect %.2f (calibrated %.2f), size %.0f%% of the calibrated %dx%d" % (
        w, hh, aspect, ref, scale * 100, REF[0], REF[1])
    return text, ok


def log_window(h):
    """Write the window size to the log, with a warning when the shape is not the calibrated one."""
    text, ok = window_info(h)
    log("WINDOW %s" % text)
    if not ok:
        log("WINDOW warning: another aspect ratio than the calibrated 16:9; areas of the HUD, chat and minimap may be off. "
            "Use the diagnostic report (Auto-hunt tab) and send it to the author.")
    return ok


def _try(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        return "error: %s" % e


def save_report(h, cfg):
    """Folder with screen.png (the whole game window) and report.txt (window size, detector results, settings).
    Returns the folder path. Nothing leaves the computer: the user sends the folder if they want to."""
    folder = os.path.join(HERE, "diagnostics", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(folder, exist_ok=True)
    x, y, w, hh = client_rect(h)
    from .vision import grab
    rows, w2, h2 = llm.to_rgb(grab(x, y, w, hh), w, hh, w)
    with open(os.path.join(folder, "screen.png"), "wb") as f:
        f.write(llm.png_bytes(rows, w2, h2))
    text, ok = window_info(h)
    lines = [APP + " diagnostic report", time.strftime("%Y-%m-%d %H:%M:%S"), "", text,
             "aspect ratio as calibrated: %s" % ("yes" if ok else "NO"), ""]
    bars = _try(find_bars, h)
    lines.append("health bars (x, y of the body point): %s" % (
        bars if isinstance(bars, str) else ", ".join("(%.3f,%.3f)" % p for p in bars)))
    if not isinstance(bars, str):
        lines.append("  health left of each: %s" % ", ".join("%.0f%%" % (f * 100) for p, f in LAST_BARS))
    bots = _try(find_bots, h)
    lines.append("name labels: %s" % (bots if isinstance(bots, str) else ", ".join("(%.3f,%.3f)" % p for p in bots)))
    lines.append("attacks left (ATAQUES digit): %s" % _try(read_attacks, h))
    lines.append("own health (SALUD bar): %s" % _try(read_health, h))
    lines.append("chat says it is our turn: %s" % _try(chat_turn_is_mine, h))
    for name in ("combat", "turn"):
        lines.append("zone %s: %s" % (name, _try(detect, h, name)))
    lines += ["", "settings: area=%s gap=%s min_health=%s" % (cfg.get("hunt_area"), cfg.get("hunt_gap"),
                                                          cfg.get("hunt_min_health"))]
    with open(os.path.join(folder, "report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    log("diagnostic report saved: %s" % folder)
    return folder


def save_marked(h, name, points, max_width=1280):
    """Save a screenshot of the whole game window with numbered markers at `points` (client fractions) in snapshots/:
    1 = where the click went, 2 = where the bot was thought to be. For seeing why an attack click missed."""
    try:
        from .vision import grab, SNAP_KEEP
        x, y, w, hh = client_rect(h)
        rows, w2, h2 = llm.to_rgb(grab(x, y, w, hh), w, hh, max_width)
        scale = max(2, w2 // 220)
        for n, (px, py) in enumerate(points, 1):
            llm.draw_marker(rows, w2, h2, px * w2, py * h2, n, scale)
        folder = os.path.join(HERE, "snapshots")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "%s-%s.png" % (time.strftime("%Y%m%d-%H%M%S"), name))
        with open(path, "wb") as f:
            f.write(llm.png_bytes(rows, w2, h2))
        for old in sorted(os.listdir(folder))[:-SNAP_KEEP]:
            os.remove(os.path.join(folder, old))
        log("snapshot saved: %s" % path)
    except Exception as e:
        log("marked snapshot failed: %s" % e)
