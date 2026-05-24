"""Check what's currently foreground and whether any safety/IME overlay
is potentially blocking input. Used to decide whether SendInput will land."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

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


def main():
    fg = user32.GetForegroundWindow()
    print(f"foreground hwnd={fg} title={get_window_text(fg)!r} class={get_class_name(fg)!r}")

    # Enumerate all visible windows looking for known blockers.
    blockers = []
    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            title = get_window_text(hwnd).lower()
            cls = get_class_name(hwnd).lower()
            for keyword in ("textinputhost", "text input", "ime", "welcome to fl"):
                if keyword in title or keyword in cls:
                    blockers.append((hwnd, get_window_text(hwnd), get_class_name(hwnd)))
                    break
        except Exception:
            pass
        return True
    user32.EnumWindows(EnumWindowsProc(cb), 0)

    if blockers:
        print(f"BLOCKERS found ({len(blockers)}):")
        for h, t, c in blockers:
            print(f"  hwnd={h} title={t!r} class={c!r}")
    else:
        print("No known blockers visible.")


if __name__ == "__main__":
    main()
