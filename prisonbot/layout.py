"""Where the sections of the screen are, asked to the vision model when the hunt starts (and once in the first fight, when
the fight-only boxes are on screen). The model proposes boxes; the colour detectors judge them: a box is used only if the
thing it should hold is really found there, and only where the calibrated place does not work. Everything it finds is
reported (log, diagnostic report, web page) so that a screen shaped differently can be understood."""
from .config import log
from . import llm
from .vision import (AREAS, HUD, NOMINAL_BAR_Y, ATTACKS_AREA, client_rect, grab, health_bar_from_buf, attacks_from_buf,
                     read_attacks, read_health, area)
from . import minimap

REPORT = []  # the lines of the last analysis


def iou(a, b):
    """Overlap of two (x0, y0, x1, y1) boxes, 0..1."""
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(x1 - x0, 0.0) * max(y1 - y0, 0.0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _rect(box):
    return box[0], box[1], box[2] - box[0], box[3] - box[1]


def _grab_box(h, box, pad=0.0):
    x0, y0, x1, y1 = max(box[0] - pad, 0.0), max(box[1] - pad, 0.0), min(box[2] + pad, 1.0), min(box[3] + pad, 1.0)
    x, y, w, hh = client_rect(h)
    rw, rh = int((x1 - x0) * w), int((y1 - y0) * hh)
    if rw <= 0 or rh <= 0:
        return None, 0, 0, (x0, y0, x1, y1)
    return grab(x + int(x0 * w), y + int(y0 * hh), rw, rh), rw, rh, (x0, y0, x1, y1)


def health_bar_y(h, box):
    """The y (client fraction) of the red bar inside the model's box, or None if there is no red bar there."""
    buf, rw, rh, (x0, y0, x1, y1) = _grab_box(h, box, 0.01)
    if buf is None:
        return None
    x, y, w, hh = client_rect(h)
    found = health_bar_from_buf(buf, rw, rh, w)
    return None if found is None else y0 + found[1] / float(rh) * (y1 - y0)


def minimap_found(h, box):
    """True if the minimap reader finds the player arrow inside the box."""
    buf, rw, rh, _ = _grab_box(h, box)
    if buf is None:
        return False
    return minimap.read_minimap(buf, rw, rh)[0] is not None


def attacks_found(h, box):
    buf, rw, rh, _ = _grab_box(h, box)
    return buf is not None and attacks_from_buf(buf, rw, rh) is not None


def analyze_and_apply(cfg, h, phase):
    """Ask the model, check what it says against the colours on screen, adopt what is needed. `phase` is "start" or
    "fight". Returns the report lines (also kept in REPORT)."""
    out = []
    boxes = llm.analyze_layout(cfg, h)
    if boxes is None:
        REPORT[:] = ["the vision model gave no answer: the colour scan is used"]
        log("LAYOUT model (%s): no answer, the colour scan is used" % phase)
        return list(REPORT)

    # the health bar: the colour scan follows it already; the model is the fallback when the scan finds nothing
    if "health_bar" in boxes:
        model_y = health_bar_y(h, boxes["health_bar"])
        scan = read_health(h)
        if scan is not None:
            if model_y is None:
                out.append("health bar: found by the colours at y=%.3f; the model's box has no red bar" % HUD["bar_y"])
            else:
                out.append("health bar: colours y=%.3f, model y=%.3f (%s)" % (
                    HUD["bar_y"], model_y, "agree" if abs(model_y - HUD["bar_y"]) < 0.03 else "differ: the colours win"))
        elif model_y is not None:
            HUD["bar_y"] = min(max(model_y, 0.5), 0.97)
            out.append("health bar: not found by the colours; the model's box holds a red bar: using y=%.3f" % model_y)
        else:
            out.append("health bar: found by neither the colours nor the model")
    else:
        out.append("health bar: the model did not find it")

    # the minimap: the calibrated place first
    if "minimap" in boxes:
        mb = boxes["minimap"]
        buf, rw, rh = minimap.grab_minimap(h)
        default_ok = minimap.read_minimap(buf, rw, rh)[0] is not None
        fx, fy, fw, fh = minimap.map_area(h)
        same = iou(mb, (fx, fy, fx + fw, fy + fh))
        if default_ok:
            out.append("minimap: the calibrated place works (overlap with the model's box %.2f)" % same)
        elif minimap_found(h, mb):
            AREAS["minimap"] = (mb[0], mb[1], mb[2] - mb[0], mb[3] - mb[1])
            minimap._map_cache.clear()
            out.append("minimap: NOT found at the calibrated place; the model's box holds the player arrow: using it")
        else:
            out.append("minimap: found at neither the calibrated place nor the model's box")

    # the ATAQUES box exists only in a fight
    if "attacks_box" in boxes:
        ab = boxes["attacks_box"]
        if read_attacks(h) is not None:
            out.append("ATAQUES box: the calibrated place works")
        elif attacks_found(h, ab):
            AREAS["attacks"] = _rect(ab)
            out.append("ATAQUES box: not read at the calibrated place; the model's box holds a digit: using it")
        else:
            out.append("ATAQUES box: not readable at either place (the box is empty during the enemy's turn)")

    # the rest is for the record: it tells how this screen is laid out
    for key in ("bottom_bar", "chat", "top_bar", "turn_buttons"):
        if key in boxes:
            b = boxes[key]
            out.append("%s: x %.2f-%.2f, y %.2f-%.2f" % (key, b[0], b[2], b[1], b[3]))
    REPORT[:] = out
    for line in out:
        log("LAYOUT model (%s): %s" % (phase, line))
    return list(out)
