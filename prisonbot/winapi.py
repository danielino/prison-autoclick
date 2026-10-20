"""Win32 access: input simulation, window lookup, screen reading. Nothing here touches the game process."""
import copy, ctypes, json, os, random, re, sys, threading, time
from ctypes import wintypes
from .config import *


u32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    u32.SetProcessDPIAware()

LBTN, RBTN = 0x01, 0x02


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


__all__ = [n for n in list(globals()) if not n.startswith("__")]
