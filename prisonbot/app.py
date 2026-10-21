"""The program: hotkey, in-game menu, autoclick, recording and playback; the hunt lives in hunt.py."""
import copy, ctypes, json, os, random, re, sys, threading, time
from ctypes import wintypes
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from .config import *
from .winapi import *
from .vision import *
from .minimap import *
from .hunt import HuntMixin
from .heal import HealMixin
from .gui import Gui


class App(HuntMixin, HealMixin):
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
                           "To heal: Ctrl+1, mouse on the food in the list, press F8" + ("  [saved]" if self.cfg.get("heal_item") else ""),
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

    def w_double(self):
        missing = [s for s in ("8", "9") if s not in self.cfg["sequences"]]
        if missing:
            self.msg = "Record sequences 8 (turn 1) and 9 (turn 2) first"
            return
        self.w_play(["8", "9"])

    def loop(self):
        self.root.after(15, self.tick)
        self.root.mainloop()


__all__ = [n for n in list(globals()) if not n.startswith("__")]
