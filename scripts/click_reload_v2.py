"""Click Reload Script using the SetCursorPos + mouse_event legacy API
combination that DOES register with FL Studio's TVectorPanel.

Empirically verified: SendInput-synthesized clicks are filtered by FL
Studio's custom-drawn TVectorPanel, but legacy mouse_event API clicks
go through (proven by clicking Clear output and verifying output cleared).
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

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

HEARTBEAT = os.path.expanduser(
    r"~\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\ipc\bridge_alive.txt"
)
LOG_FILE = os.path.expanduser(
    r"~\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\bridge.log"
)


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

    def cb(h, _):
        if user32.IsWindowVisible(h) and "Script output" in get_window_text(h):
            out.append(h)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out[0] if out else None


def find_toolbar(parent):
    matches = []

    def cb(h, _):
        if get_class_name(h) == "TVectorPanel":
            matches.append(h)
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
    user32.AttachThreadInput(cur_tid, fg_tid, False)
    user32.AttachThreadInput(cur_tid, tgt_tid, False)


def click_at(sx, sy):
    """Move cursor to (sx, sy) and click via legacy mouse_event API."""
    user32.SetCursorPos(sx, sy)
    time.sleep(0.1)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def log_size():
    return os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0


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
    print(f"Toolbar rect=({tl},{tt})..({tr},{tb})")

    # Reload script button center: ~60px from right edge, vertical center.
    rx = tr - 60
    ry = (tt + tb) // 2
    print(f"Reload click target: ({rx}, {ry})")

    initial_size = log_size()
    initial_hb = os.path.exists(HEARTBEAT)
    print(f"Initial state: bridge.log={initial_size} bytes, heartbeat={initial_hb}")

    print("Forcing Script Output foreground...")
    force_foreground(so)
    time.sleep(0.4)

    print(f"Clicking Reload at ({rx}, {ry}) via mouse_event...")
    click_at(rx, ry)

    print("Waiting for bridge to come up...")
    for i in range(30):
        time.sleep(0.5)
        size = log_size()
        hb = os.path.exists(HEARTBEAT)
        if size != initial_size or hb != initial_hb:
            print(f"CHANGE after {(i+1)*0.5}s: bridge.log={size} bytes, heartbeat={hb}")
            return 0
    print("Timed out — no change in bridge.log or heartbeat after 15s")
    return 2


if __name__ == "__main__":
    sys.exit(main())
