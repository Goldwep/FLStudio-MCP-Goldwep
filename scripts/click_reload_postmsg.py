"""Try Reload Script click via PostMessage WM_LBUTTONDOWN/UP directly to
the TVectorPanel toolbar HWND. This avoids SendInput and any potential
input-origin checks FL might apply.

If WM_LBUTTONDOWN/UP doesn't work, fall back to sending the messages with
WM_MOUSEACTIVATE first, then a slow click sequence.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_MOUSEMOVE = 0x0200
WM_MOUSEACTIVATE = 0x0021
WM_SETFOCUS = 0x0007
WM_ACTIVATE = 0x0006
WM_NCHITTEST = 0x0084

MK_LBUTTON = 0x0001

HEARTBEAT = os.path.expanduser(
    r"~\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\ipc\bridge_alive.txt"
)
LOG_FILE = os.path.expanduser(
    r"~\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\bridge.log"
)


def MAKELPARAM(lo, hi):
    return (hi & 0xFFFF) << 16 | (lo & 0xFFFF)


def get_window_text(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def get_class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_window_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def find_script_output():
    out = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and "Script output" in get_window_text(hwnd):
            out.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out[0] if out else None


def find_toolbar(parent):
    """Find the bottom TVectorPanel inside Script Output."""
    matches = []

    def cb(hwnd, _):
        if get_class_name(hwnd) == "TVectorPanel":
            matches.append(hwnd)
        return True

    user32.EnumChildWindows(parent, EnumWindowsProc(cb), 0)
    if not matches:
        return None
    matches.sort(key=lambda h: get_window_rect(h)[1], reverse=True)
    return matches[0]


def force_foreground(hwnd):
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, 0)
    tgt_tid = user32.GetWindowThreadProcessId(hwnd, 0)
    cur_tid = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(cur_tid, fg_tid, True)
    user32.AttachThreadInput(cur_tid, tgt_tid, True)
    user32.ShowWindow(hwnd, 9)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(hwnd)
    user32.AttachThreadInput(cur_tid, fg_tid, False)
    user32.AttachThreadInput(cur_tid, tgt_tid, False)


def click_toolbar(toolbar, rel_x, rel_y):
    """Send a click to the toolbar at relative coords."""
    lp = MAKELPARAM(rel_x, rel_y)
    # Move + activate first
    user32.PostMessageW(toolbar, WM_MOUSEMOVE, 0, lp)
    time.sleep(0.05)
    user32.PostMessageW(toolbar, WM_LBUTTONDOWN, MK_LBUTTON, lp)
    time.sleep(0.05)
    user32.PostMessageW(toolbar, WM_LBUTTONUP, 0, lp)


def log_size():
    return os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0


def heartbeat_exists():
    return os.path.exists(HEARTBEAT)


def main():
    so = find_script_output()
    if so is None:
        print("Script output not found")
        return 1
    print(f"Script Output hwnd={so}")
    toolbar = find_toolbar(so)
    if toolbar is None:
        print("Toolbar not found")
        return 1
    tl, tt, tr, tb = get_window_rect(toolbar)
    print(f"Toolbar rect=({tl},{tt})..({tr},{tb}) size={tr-tl}x{tb-tt}")

    # Reload button is rightmost — from screenshot, button center ~570 in
    # cropped image (0..630). Relative to toolbar: ~(566, 28).
    rel_x = (tr - tl) - 60  # 60px from right
    rel_y = (tb - tt) // 2  # vertical center
    print(f"Click at toolbar-relative ({rel_x}, {rel_y})")

    initial_log_size = log_size()
    print(f"bridge.log size before: {initial_log_size}")
    print(f"heartbeat exists before: {heartbeat_exists()}")

    force_foreground(so)
    time.sleep(0.3)
    click_toolbar(toolbar, rel_x, rel_y)

    # Wait + check
    for i in range(20):
        time.sleep(0.5)
        new_size = log_size()
        if new_size != initial_log_size:
            print(f"bridge.log changed: {initial_log_size} -> {new_size}")
            break
        if heartbeat_exists():
            print(f"heartbeat appeared after {(i+1)*0.5}s!")
            break
    else:
        print(f"After 10s: bridge.log size={log_size()} (unchanged), heartbeat={heartbeat_exists()}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
