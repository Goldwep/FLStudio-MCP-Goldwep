"""Enumerate all visible top-level windows owned by the user's real FL64.exe
(PID with parent=explorer.exe). Helps decide whether Script Output is open
and where to send the Reload Script click."""

from __future__ import annotations

import ctypes
import subprocess
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


def get_window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_window_rect(hwnd: int):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def find_real_fl_pid() -> int | None:
    """Return PID of FL64.exe whose parent is explorer.exe."""
    out = subprocess.run(
        ["wmic", "process", "where", "name='FL64.exe'", "get",
         "ProcessId,ParentProcessId", "/FORMAT:CSV"],
        capture_output=True, text=True, check=False,
    )
    fl_pids = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("Node") or "ParentProcessId" in line:
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            ppid = int(parts[1])
            pid = int(parts[2])
            fl_pids.append((pid, ppid))
        except ValueError:
            continue
    # Look up parent names
    for pid, ppid in fl_pids:
        po = subprocess.run(
            ["wmic", "process", "where", f"ProcessId={ppid}", "get", "Name", "/FORMAT:CSV"],
            capture_output=True, text=True, check=False,
        )
        for ln in po.stdout.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("Node"):
                continue
            parts = ln.split(",")
            if len(parts) >= 2 and parts[1].lower() == "explorer.exe":
                return pid
    return None


def enum_pid_windows(pid: int):
    matches = []
    def callback(hwnd, _):
        try:
            if user32.IsWindowVisible(hwnd) and get_window_pid(hwnd) == pid:
                matches.append(hwnd)
        except Exception:
            pass
        return True
    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return matches


def main():
    pid = find_real_fl_pid()
    if pid is None:
        print("[inspect] no user-FL64 found (parent=explorer.exe)")
        return 1
    print(f"[inspect] user FL64.exe PID = {pid}")
    windows = enum_pid_windows(pid)
    print(f"[inspect] {len(windows)} visible top-level windows:")
    for hwnd in windows:
        title = get_window_text(hwnd)
        l, t, r, b = get_window_rect(hwnd)
        w, h = r - l, b - t
        print(f"  hwnd={hwnd:>10} rect=({l:>5},{t:>5})..({r:>5},{b:>5}) size={w}x{h} title={title!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
