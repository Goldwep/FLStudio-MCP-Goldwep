"""Switch to the MPKmini2 tab in FL Studio's Script Output, then click
the Reload Script button to fire OnInit on the file-IPC bridge.

Strategy:
1. Force Script Output to foreground.
2. Click the right half of the TQuickSheetSelector (tab strip) — MPKmini2
   is the second tab after Interpreter, so it's on the right.
3. Wait 200ms for tab switch render.
4. Click the rightmost ~60px of the bottom TVectorPanel — that's where
   FL Studio's Reload Script button lives.
5. Wait 2s. Check bridge_alive.txt + bridge.log for new OnInit.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

# --- Win32 input plumbing ---

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


def send_click(sx: int, sy: int) -> int:
    """Move to (sx, sy) in screen coords and click."""
    SM_XV, SM_YV, SM_CXV, SM_CYV = 76, 77, 78, 79
    vx = user32.GetSystemMetrics(SM_XV)
    vy = user32.GetSystemMetrics(SM_YV)
    vw = user32.GetSystemMetrics(SM_CXV)
    vh = user32.GetSystemMetrics(SM_CYV)
    nx = int((sx - vx) * 65535 / max(1, vw - 1))
    ny = int((sy - vy) * 65535 / max(1, vh - 1))

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
    return user32.SendInput(len(events), ctypes.byref(arr), ctypes.sizeof(INPUT))


# --- Window helpers ---


def get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_window_rect(hwnd: int):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def find_script_output():
    target = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and "Script output" in get_window_text(hwnd):
            target.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return target[0] if target else None


def find_child_by_class(parent: int, classname: str):
    """Return first descendant with matching window class."""
    matches = []

    def cb(hwnd, _):
        if get_class_name(hwnd) == classname:
            matches.append(hwnd)
        return True

    user32.EnumChildWindows(parent, EnumWindowsProc(cb), 0)
    return matches[0] if matches else None


def find_children_by_class(parent: int, classname: str):
    matches = []

    def cb(hwnd, _):
        if get_class_name(hwnd) == classname:
            matches.append(hwnd)
        return True

    user32.EnumChildWindows(parent, EnumWindowsProc(cb), 0)
    return matches


def force_foreground(hwnd: int):
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, 0)
    target_tid = user32.GetWindowThreadProcessId(hwnd, 0)
    cur_tid = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(cur_tid, fg_tid, True)
    user32.AttachThreadInput(cur_tid, target_tid, True)
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(hwnd)
    user32.AttachThreadInput(cur_tid, fg_tid, False)
    user32.AttachThreadInput(cur_tid, target_tid, False)


# --- State helpers ---

IPC_DIR = os.path.expanduser(
    r"~\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\ipc"
)
LOG_FILE = os.path.expanduser(
    r"~\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\bridge.log"
)


def check_bridge_alive():
    """Return True if bridge_alive.txt exists with a recent mtime."""
    path = os.path.join(IPC_DIR, "bridge_alive.txt")
    if not os.path.exists(path):
        return False
    age = time.time() - os.path.getmtime(path)
    return age < 30


def log_tail():
    if not os.path.exists(LOG_FILE):
        return "[no bridge.log]"
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return "".join(lines[-5:])


# --- Main ---


def main() -> int:
    so = find_script_output()
    if so is None:
        print("[reload] Script output not found")
        return 2
    l, t, r, b = get_window_rect(so)
    print(f"[reload] Script output hwnd={so} rect=({l},{t})..({r},{b})")

    # Find the tab selector and the bottom toolbar.
    sheet_selector = find_child_by_class(so, "TQuickSheetSelector")
    if sheet_selector is None:
        print("[reload] TQuickSheetSelector (tab strip) not found")
        return 3
    sl, st, sr, sb = get_window_rect(sheet_selector)
    print(f"[reload] tab strip rect=({sl},{st})..({sr},{sb})")

    toolbars = find_children_by_class(so, "TVectorPanel")
    if not toolbars:
        print("[reload] TVectorPanel (bottom toolbar) not found")
        return 4
    # Pick the toolbar at the bottom of the window (highest top).
    toolbars.sort(key=lambda h: get_window_rect(h)[1], reverse=True)
    toolbar = toolbars[0]
    tl, tt, tr, tb = get_window_rect(toolbar)
    print(f"[reload] toolbar rect=({tl},{tt})..({tr},{tb})")

    # Bring Script Output to foreground.
    print("[reload] forcing foreground...")
    force_foreground(so)
    time.sleep(0.4)
    fg = user32.GetForegroundWindow()
    print(f"[reload] foreground now: {fg} title={get_window_text(fg)!r}")

    # Click the MPKmini2 tab — it's the 2nd of 2 tabs, so right half.
    # Tab strip width = sr - sl. With 2 tabs, MPKmini2 spans the right half.
    tab_w = sr - sl
    mpk_x = sl + int(tab_w * 0.75)  # 75% across (middle of right tab)
    mpk_y = (st + sb) // 2
    print(f"[reload] clicking MPKmini2 tab at ({mpk_x}, {mpk_y})")
    send_click(mpk_x, mpk_y)
    time.sleep(0.4)

    # Now click the Reload button — rightmost area of the toolbar.
    # Toolbar typical layout has buttons left-to-right; Reload is the
    # rightmost icon. Try ~35px in from the right edge.
    reload_x = tr - 35
    reload_y = (tt + tb) // 2
    print(f"[reload] clicking Reload at ({reload_x}, {reload_y})")
    send_click(reload_x, reload_y)

    # Wait for bridge to come up.
    print("[reload] waiting for bridge_alive.txt...")
    for i in range(20):
        time.sleep(0.5)
        if check_bridge_alive():
            print(f"[reload] BRIDGE ALIVE after {(i + 1) * 0.5}s!")
            print("[reload] bridge.log tail:")
            print(log_tail())
            return 0
    print("[reload] timed out waiting for bridge_alive.txt")
    print("[reload] bridge.log tail:")
    print(log_tail())
    return 1


if __name__ == "__main__":
    sys.exit(main())
