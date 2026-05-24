"""Locate the MIDI Settings 'Controller type' dropdown and switch it from
'FLStudio MCP Probe' to 'FLStudio MCP Bridge'.

Strategy:
  1. Find MIDI Settings dialog hwnd.
  2. Recursively enumerate children, log classes + rects.
  3. Find the combobox / dropdown next to 'Controller type' label.
  4. Use ComboBox API (CB_FINDSTRINGEXACT + CB_SETCURSEL) if it's a native
     combo, or fall back to coordinate-based click + keyboard input.
  5. Verify Output section now reads 'FLStudio MCP Bridge'.

If FL Studio uses custom-drawn dropdowns (no native combo HWND), we fall
back to: click the dropdown center, wait for list popup, scroll/click the
correct entry by visual match.
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


def find_midi_settings():
    found = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            t = get_window_text(hwnd)
            if "MIDI input" in t and "Settings" in t:
                found.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found[0] if found else None


def enum_descendants(parent, depth=0, out=None):
    if out is None:
        out = []

    def cb(hwnd, _):
        try:
            cls = get_class_name(hwnd)
            title = get_window_text(hwnd)
            rect = get_window_rect(hwnd)
            out.append((depth, hwnd, cls, title, rect))
            enum_descendants(hwnd, depth + 1, out)
        except Exception:
            pass
        return True

    user32.EnumChildWindows(parent, EnumWindowsProc(cb), 0)
    return out


def main():
    ms = find_midi_settings()
    if ms is None:
        print("MIDI Settings dialog not found.")
        return 1
    print(f"MIDI Settings hwnd={ms} rect={get_window_rect(ms)}")
    children = enum_descendants(ms)
    print(f"{len(children)} descendants")
    for depth, hwnd, cls, title, rect in children:
        ind = "  " * (depth + 1)
        l, t, r, b = rect
        w, h = r - l, b - t
        # Highlight anything that looks like a dropdown / combo
        marker = ""
        cls_lower = cls.lower()
        if any(k in cls_lower for k in ("combo", "dropdown", "select", "edit")):
            marker = " <-- CANDIDATE"
        # Highlight anything showing the current wrong value
        if title and ("Probe" in title or "Bridge" in title):
            marker = " <-- TEXT MATCH"
        print(f"{ind}hwnd={hwnd:>10} cls={cls!r:<30} rect=({l},{t})..({r},{b}) size={w}x{h} title={title!r}{marker}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
