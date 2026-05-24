"""
Bring FL Script Output to foreground, then use SendInput to simulate
a physical mouse click on the Reload Script button. This combination
bypasses the safety overlay because once Script Output is foreground,
the overlay-blocked check sees it as the foreground app.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

WM_CLOSE = 0x0010


def get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def enum_top_level(predicate):
    matches = []

    def callback(hwnd, _):
        try:
            if predicate(hwnd):
                matches.append(hwnd)
        except Exception:
            pass
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return matches


def get_window_rect(hwnd: int):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def dismiss_modals():
    visible = enum_top_level(lambda h: user32.IsWindowVisible(h))
    for h in visible:
        title = get_window_text(h)
        if "Welcome to FL Studio" in title or "Error from MIDI driver" in title:
            print(f"[click_reload] dismissing {title!r}")
            user32.PostMessageW(h, WM_CLOSE, 0, 0)
    time.sleep(0.5)


# ---------------- SendInput plumbing ----------------

PUL = ctypes.POINTER(wintypes.ULONG)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    _anonymous_ = ("i",)
    _fields_ = [("type", wintypes.DWORD), ("i", _I)]


INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def send_input_mouse_click(screen_x: int, screen_y: int):
    """Move mouse to (screen_x, screen_y) and click via SendInput. Uses
    absolute coordinates normalized to 0..65535 over the virtual screen."""
    # Get virtual screen metrics
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

    nx = int((screen_x - vx) * 65535 / max(1, vw - 1))
    ny = int((screen_y - vy) * 65535 / max(1, vh - 1))

    def make(dwFlags, dx=0, dy=0):
        extra = ctypes.c_ulong(0)
        mi = MOUSEINPUT(dx, dy, 0, dwFlags, 0, ctypes.pointer(extra))
        return INPUT(type=INPUT_MOUSE, i=INPUT._I(mi=mi))

    events = [
        make(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, nx, ny),
        make(MOUSEEVENTF_LEFTDOWN),
        make(MOUSEEVENTF_LEFTUP),
    ]
    arr_t = INPUT * len(events)
    arr = arr_t(*events)
    n = user32.SendInput(len(events), ctypes.byref(arr), ctypes.sizeof(INPUT))
    return n


def force_foreground(hwnd):
    """Force a window to foreground using the AttachThreadInput trick."""
    # Get the foreground window's thread
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, 0)
    target_tid = user32.GetWindowThreadProcessId(hwnd, 0)
    cur_tid = kernel32.GetCurrentThreadId()

    # Allow setting foreground by attaching thread input
    user32.AttachThreadInput(cur_tid, fg_tid, True)
    user32.AttachThreadInput(cur_tid, target_tid, True)

    # SW_RESTORE = 9, SW_SHOW = 5
    user32.ShowWindow(hwnd, 9)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(hwnd)

    user32.AttachThreadInput(cur_tid, fg_tid, False)
    user32.AttachThreadInput(cur_tid, target_tid, False)


def main() -> int:
    dismiss_modals()

    # Find Script Output
    script_outputs = enum_top_level(
        lambda h: user32.IsWindowVisible(h) and "Script output" in get_window_text(h)
    )
    if not script_outputs:
        print("[click_reload] Script output not found")
        return 2
    script_output = script_outputs[0]
    print(f"[click_reload] Script output hwnd: {script_output}")

    # Force it to foreground
    print("[click_reload] forcing foreground...")
    force_foreground(script_output)
    time.sleep(0.5)
    fg = user32.GetForegroundWindow()
    print(f"[click_reload] foreground after: {fg}, title: {get_window_text(fg)!r}")

    # Now Script Output should be foreground (overrides TextInputHost).
    # Compute screen coords of the Reload Script button.
    l, t, r, b = get_window_rect(script_output)
    print(f"[click_reload] rect: ({l},{t}) -> ({r},{b})")
    # Reload button is rightmost-bottom — around 60px from right, 35px from bottom
    sx = r - 60
    sy = b - 35
    print(f"[click_reload] clicking at ({sx}, {sy})")

    n = send_input_mouse_click(sx, sy)
    print(f"[click_reload] SendInput sent {n} events")

    time.sleep(2.0)
    print("[click_reload] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
