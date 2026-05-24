"""Read FL Studio's Script Output content via Win32 messages.

The Script Output text area is a Delphi TQuickMemo control. Even though
Delphi components are custom-drawn, many of them respond to standard
WM_GETTEXT / WM_GETTEXTLENGTH messages. If this works, we have a new
transport channel: bridge prints responses to stdout, Node side polls
Script Output via WM_GETTEXT and parses lines starting with a tag.

This probe enumerates Script Output's children, finds the TQuickMemo,
and tries to read it via several methods.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
EM_GETLINECOUNT = 0x00BA
EM_GETLINE = 0x00C4


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


def find_mpkmini2_sheet(parent):
    matches = []

    def cb(h, _):
        if get_class_name(h) == "TVectorSheet" and "MPKmini2" in get_window_text(h):
            matches.append(h)
        return True

    user32.EnumChildWindows(parent, EnumWindowsProc(cb), 0)
    return matches[0] if matches else None


def find_quickmemos(parent):
    matches = []

    def cb(h, _):
        if get_class_name(h) == "TQuickMemo":
            matches.append(h)
        return True

    user32.EnumChildWindows(parent, EnumWindowsProc(cb), 0)
    return matches


def try_wm_gettext(hwnd):
    """Try standard WM_GETTEXT."""
    # SendMessageW with WM_GETTEXTLENGTH first
    SendMessageW = user32.SendMessageW
    SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    SendMessageW.restype = ctypes.c_void_p

    length = SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    print("  WM_GETTEXTLENGTH returned: %s" % length)
    if length is None or length == 0:
        return None
    buf_size = (length or 0) + 256
    buf = ctypes.create_unicode_buffer(buf_size)
    n = SendMessageW(hwnd, WM_GETTEXT, buf_size, ctypes.addressof(buf))
    print("  WM_GETTEXT returned: %s chars" % n)
    if n and n > 0:
        return buf.value
    return None


def try_em_gettext(hwnd):
    """Try EM_GETLINE for each line."""
    SendMessageW = user32.SendMessageW
    SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    SendMessageW.restype = ctypes.c_void_p

    count = SendMessageW(hwnd, EM_GETLINECOUNT, 0, 0)
    print("  EM_GETLINECOUNT returned: %s" % count)
    if not count:
        return None
    lines = []
    for i in range(count):
        buf_size = 1024
        buf = ctypes.create_unicode_buffer(buf_size)
        # First wchar is buffer size as WORD
        ctypes.cast(buf, ctypes.POINTER(wintypes.WORD))[0] = buf_size
        n = SendMessageW(hwnd, EM_GETLINE, i, ctypes.addressof(buf))
        if n and n > 0:
            lines.append(buf.value[:n])
    return "\n".join(lines)


def main():
    so = find_script_output()
    if so is None:
        print("Script output not found")
        return 1
    print("Script output hwnd=%s" % so)

    sheet = find_mpkmini2_sheet(so)
    if sheet is None:
        print("MPKmini2 sheet not found")
        return 1
    print("MPKmini2 sheet hwnd=%s" % sheet)

    memos = find_quickmemos(sheet)
    print("Found %d TQuickMemo children in MPKmini2 sheet" % len(memos))

    for i, memo in enumerate(memos):
        l, t, r, b = get_window_rect(memo)
        print("\n[memo %d] hwnd=%s rect=(%d,%d)..(%d,%d) size=%dx%d" %
              (i, memo, l, t, r, b, r - l, b - t))

        print(" Trying WM_GETTEXT:")
        text = try_wm_gettext(memo)
        if text:
            print(" ===== Content (first 500 chars) =====")
            print(text[:500])
            print(" ===== END =====")
            return 0
        else:
            print(" WM_GETTEXT returned no content")

        print(" Trying EM_GETLINE pattern:")
        text = try_em_gettext(memo)
        if text:
            print(" ===== Content via EM_GETLINE =====")
            print(text[:500])
            print(" ===== END =====")
            return 0

    print("\nNo content extracted via Win32 messages.")
    print("TQuickMemo is fully custom-drawn; no standard message route works.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
