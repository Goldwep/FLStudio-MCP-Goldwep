"""Enumerate all child windows of FL Studio's Script Output hwnd.
Looking for tab control + Reload button so we can target precisely."""

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


def get_window_rect(hwnd: int):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def find_script_output_hwnd():
    target = []
    def cb(hwnd, _):
        try:
            if user32.IsWindowVisible(hwnd) and "Script output" in get_window_text(hwnd):
                target.append(hwnd)
        except Exception:
            pass
        return True
    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return target[0] if target else None


def enum_children_recursive(parent_hwnd, depth=0, out=None):
    if out is None:
        out = []
    def cb(hwnd, _):
        try:
            title = get_window_text(hwnd)
            cls = get_class_name(hwnd)
            l, t, r, b = get_window_rect(hwnd)
            out.append((depth, hwnd, cls, title, l, t, r, b))
            enum_children_recursive(hwnd, depth + 1, out)
        except Exception:
            pass
        return True
    user32.EnumChildWindows(parent_hwnd, EnumWindowsProc(cb), 0)
    return out


def main():
    so = find_script_output_hwnd()
    if so is None:
        print("Script output not found")
        return 1
    print(f"Script output hwnd={so} rect={get_window_rect(so)}")
    print("Children (recursive):")
    children = enum_children_recursive(so)
    for depth, hwnd, cls, title, l, t, r, b in children:
        indent = "  " * (depth + 1)
        w, h = r - l, b - t
        print(f"{indent}hwnd={hwnd:>10} cls={cls!r:<30} rect=({l},{t})..({r},{b}) size={w}x{h} title={title!r}")
    if not children:
        print("  (no child windows — Script Output likely uses custom-drawn UI without HWND children)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
