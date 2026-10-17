"""AutoPrison: autoclick and click-sequence recorder for Prison Legacy (clean-room rewrite).

EXTERNAL program: it only simulates mouse and keyboard input (SendInput) and reads screen pixels.
It never opens, reads or modifies the game process (the window is found by its title only).
It acts only while the game window is in the foreground.

Usage: TAB opens the menu, then:
  1 autoclick   2 record (then 1-9)   3 play (then 1-9)   4 speed (1 up, 2 down, 0 exit)
  5 simple auto-fight (/repeat)   6 double-turn auto-fight (alternates sequences 8 and 9)   0 close menu
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
VK = {"TAB": 0x09, "F8": 0x77, "F9": 0x78, "F10": 0x79, "CAPSLOCK": 0x14}
LBTN, RBTN = 0x01, 0x02

DEFAULTS = {"hotkey": "TAB", "speed": 1.0, "click_interval": 0.10, "repeat_command": "/repetir",
            "repeat_interval": 1.5, "seq_pause": 0.5, "jitter": 0.2, "background": False, "sequences": {},
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


def type_line(text):
    for ch in text:
        key_tap(char=ch)
    key_tap(vk=0x0D)


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


u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.PrintWindow.argtypes = [wintypes.HWND, _P, wintypes.UINT]


def post_click(h, button, px, py, hold=0.04):
    """Background click: window messages sent to the game window, no cursor movement, no focus change.
    px, py are client-area pixels."""
    lp = ((py & 0xFFFF) << 16) | (px & 0xFFFF)
    down, up, mk = (0x0201, 0x0202, 0x0001) if button == "L" else (0x0204, 0x0205, 0x0002)
    u32.PostMessageW(h, 0x0200, 0, lp)  # WM_MOUSEMOVE: the game needs to see the pointer over the window
    time.sleep(0.02)
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
                     "5 Simple auto-fight", "6 Double-turn auto-fight", "0 Close menu"],
            "REC_SLOT": ["RECORD: press 1-9 to choose the sequence slot"] + self.slot_lines() + ["0 cancel"],
            "REC": ["RECORDING sequence %s  (%d clicks)" % (self.rec_slot, len(self.rec)),
                    "F9 = wait for a dialog window (screen center, e.g. MAQUINA)",
                    "F10 = wait for a menu next to the cursor",
                    "%s to finish and save" % self.cfg["hotkey"]],
            "PLAY_SLOT": ["PLAY: press 1-9"] + self.slot_lines() + ["0 cancel"],
            "SPEED": ["SPEED x%.2f" % self.cfg["speed"], "1 faster   2 slower   0 exit"],
            "RUN": [self.msg, "%s to stop" % self.cfg["hotkey"]],
        }.get(self.state, [])
        if self.msg and self.state not in ("RUN",):
            lines = lines + ["", self.msg]
        if not lines:
            self.ov.withdraw()
            return
        if self.state in ("MENU", "SPEED", "REC_SLOT", "PLAY_SLOT"):
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
            elif self.state in ("MENU", "REC_SLOT", "PLAY_SLOT", "SPEED"):
                d = self.digit()
                if d is not None:
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
            post_click(h, button, px, py)
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
                post_click(self.game(), "L", *target)
            else:
                mouse_click("L")
            j = self.cfg["jitter"]  # delay set in the window, in ms; independent of the sequence speed
            if not self.wait(max(self.cfg["click_interval"] * (1 + random.uniform(-j, j)), 0.01)):
                break

    def w_repeat(self):
        while self.alive():
            type_line(self.cfg["repeat_command"])
            if not self.wait(self.cfg["repeat_interval"] / self.cfg["speed"]):
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


class Gui:
    """Control window: autoclick delay, the 9 sequence slots with names, and a library of named sequences."""

    def __init__(self, app):
        self.app, self.cfg = app, app.cfg
        w = self.win = tk.Toplevel(app.root)
        w.title("AutoPrison")
        w.geometry("760x480")
        w.minsize(640, 420)
        w.protocol("WM_DELETE_WINDOW", app.root.destroy)  # closing this window quits the program

        top = ttk.LabelFrame(w, text="Autoclick (menu option 1)")
        top.pack(fill="x", padx=10, pady=(10, 4))
        self.delay = tk.StringVar(value=str(int(round(self.cfg["click_interval"] * 1000))))
        self.jit = tk.StringVar(value=str(int(round(self.cfg["jitter"] * 100))))
        self.speed = tk.StringVar(value="%g" % self.cfg["speed"])
        for col, (label, var, lo, hi, inc, key) in enumerate((
                ("Delay between clicks (ms)", self.delay, 10, 60000, 10, "delay"),
                ("Random variation (±%)", self.jit, 0, 90, 5, "jit"),
                ("Sequence speed (x)", self.speed, 0.1, 8, 0.05, "speed"))):
            ttk.Label(top, text=label).grid(row=0, column=col, padx=8, pady=(6, 0), sticky="w")
            sp = ttk.Spinbox(top, from_=lo, to=hi, increment=inc, textvariable=var, width=10,
                             command=self.apply)
            sp.grid(row=1, column=col, padx=8, pady=(0, 8), sticky="w")
            sp.bind("<KeyRelease>", lambda e: self.apply())
            sp.bind("<FocusOut>", lambda e: self.apply())
        ttk.Label(top, text="Delay and variation apply to autoclick; speed applies to recorded sequences.",
                  foreground="gray").grid(row=2, column=0, columnspan=3, padx=8, pady=(0, 6), sticky="w")
        self.bgvar = tk.BooleanVar(value=bool(self.cfg["background"]))
        ttk.Checkbutton(top, variable=self.bgvar, command=self.apply, text=(
            "Background mode (experimental): clicks are sent to the game window without moving your mouse, "
            "so you can use other programs. Keep the game window open, not minimized. F12 stops from anywhere."
        )).grid(row=3, column=0, columnspan=3, padx=8, pady=(0, 8), sticky="w")

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
                          ("Save to library →", self.to_library)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 4))

        right = ttk.LabelFrame(body, text="Library (saved sequences)")
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.lib = self.tree(right, ("name", "clicks"), ("Name", "Clicks"), (210, 55))
        self.lib.bind("<Double-1>", lambda e: self.rename_lib())
        bar = ttk.Frame(right)
        bar.pack(fill="x", padx=6, pady=6)
        for text, cmd in (("← Load into slot", self.from_library), ("Rename", self.rename_lib),
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
        except ValueError:
            return  # half-typed value: ignore until it is a number
        save(self.cfg)

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
                s, self.cfg["names"].get(s, "") if evs else "", self.clicks(evs) if evs else "—"))
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
    print("AutoPrison is running. Close the AutoPrison window to quit (everything is already saved).")
    App().loop()
