"""Healing between fights: Ctrl+1 opens the character sheet, a double click on the food opens the COMER/BEBER dialog,
+ is pressed while the "salud +N" text is white (it turns red when N is more than the health that is missing), then -
once and the green tick."""
import copy, ctypes, json, os, random, re, sys, threading, time
from ctypes import wintypes
from .config import *
from .winapi import *
from .vision import *

# client fractions, measured on the user's screenshots of the dialog
BTN_PLUS, BTN_MINUS = (0.4485, 0.5634), (0.4485, 0.5981)
BTN_OK, BTN_CANCEL = (0.5515, 0.5634), (0.5515, 0.5972)
HEAL_TEXT = (0.515, 0.508, 0.075, 0.030)  # the "salud +580" line of the dialog
HEAL_DIALOG = (0.38, 0.38, 0.24, 0.28)  # the dialog (screen centre)
SHEET_AREA = (0.0, 0.15, 0.16, 0.65)  # the inventory list of the character sheet (left)
SC_CTRL, SC_1 = 0x1D, 0x02


def _white(r, g, b):
    return r >= 200 and g >= 200 and b >= 200


def _text_red(r, g, b):
    return r >= 170 and g <= 90 and b <= 90


def heal_text_state(buf, w, hh):
    """'white' (the food still fits in the missing health), 'red' (too much) or None (no text: no dialog)."""
    n = white = red = 0
    for i in range(0, w * hh * 4 - 3, 4):
        n += 1
        r, g, b = buf[i + 2], buf[i + 1], buf[i]
        if _text_red(r, g, b):
            red += 1
        elif _white(r, g, b):
            white += 1
    if not n or max(white, red) / n < 0.03:
        return None
    return "red" if red > white else "white"


def _area(h, rect):
    fx, fy, fw, fh = rect
    x, y, w, hh = client_rect(h)
    rw, rh = int(fw * w), int(fh * hh)
    return grab(x + int(fx * w), y + int(fy * hh), rw, rh), rw, rh


class HealMixin:
    """Methods of App that heal the character with the food chosen in the setup (F8)."""

    def heal_click(self, h, pt):
        self.hunt_move(h, *pt)
        mouse_click("L")
        return self.wait(0.3)

    def heal_state(self, h):
        return heal_text_state(*_area(h, HEAL_TEXT))

    def hunt_heal(self, h):
        """Eat until the health is (nearly) full. True if something was eaten."""
        item = self.cfg.get("heal_item")
        if not item:
            return False
        hp0 = read_health(h)
        self.hunt_say("healing (health %d%%)" % (hp0 * 100))
        ate = False
        for attempt in (1, 2):  # the 2nd attempt: the first Ctrl+1 may have CLOSED a sheet that was already open
            before = _area(h, HEAL_DIALOG)[0]
            key_combo(SC_CTRL, SC_1)
            if not self.wait(0.9):
                return False
            self.hunt_move(h, *item)
            mouse_click("L")
            time.sleep(0.15)
            mouse_click("L")  # double click: the COMER/BEBER dialog
            if not self.wait(0.8):
                return False
            if self.heal_state(h) or changed(before, _area(h, HEAL_DIALOG)[0], min_frac=0.15, tol=40):
                break
            log("HUNT heal: no dialog after the double click (attempt %d)" % attempt)
        else:
            self.hunt_say("healing failed: the food dialog did not open")
            key_combo(SC_CTRL, SC_1)
            return False
        state = self.heal_state(h)
        if state is None:
            log("HUNT heal: dialog text not readable")
            self.heal_click(h, BTN_CANCEL)
        elif state == "red":
            log("HUNT heal: one portion is already too much (health is nearly full)")
            self.heal_click(h, BTN_CANCEL)
        else:
            for n in range(60):
                if not self.heal_click(h, BTN_PLUS):
                    return False
                state = self.heal_state(h)
                if state == "red":
                    log("HUNT heal: %d portions are too many, going back one" % (n + 2))
                    self.heal_click(h, BTN_MINUS)
                    break
                if state is None:
                    break
            self.heal_click(h, BTN_OK)
            ate = True
            self.wait(1.0)
        key_combo(SC_CTRL, SC_1)  # close the sheet again
        self.wait(0.6)
        log("HUNT heal: health %d%% -> %d%%" % (hp0 * 100, read_health(h) * 100))
        return ate


__all__ = [n for n in list(globals()) if not n.startswith("__")]
