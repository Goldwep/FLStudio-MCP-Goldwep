"""
Close the orphan FL64.exe that Claude accidentally spawned during the
safety-overlay session via open_application. The orphan (parent=claude.exe)
is holding MPKmini2's MIDI input port, blocking the user's real FL64.exe
(parent=explorer.exe) from activating the FLStudio MCP Bridge controller.

Strategy:
  1. Enumerate FL64.exe PIDs and parent processes via WMIC.
  2. Identify the orphan(s) — any FL64.exe whose parent is claude.exe.
  3. Enumerate top-level windows belonging to each orphan PID.
  4. PostMessageW(hwnd, WM_CLOSE, 0, 0) — graceful close, equivalent to
     the user clicking the X on the title bar. If a "save changes?" dialog
     pops, leave it for the user (we never spawned a project, so this
     should never happen, but we don't auto-dismiss save prompts).
  5. Wait briefly, verify the PID is gone.

Safe by design: never uses taskkill, never modifies process tokens, never
touches the user's real FL64.exe. WM_CLOSE is identical to the user
hitting Alt+F4 on the orphan window.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_CLOSE = 0x0010

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


def enum_windows_for_pid(target_pid: int):
    matches = []

    def callback(hwnd, _):
        try:
            if user32.IsWindowVisible(hwnd) and get_window_pid(hwnd) == target_pid:
                matches.append((hwnd, get_window_text(hwnd)))
        except Exception:
            pass
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return matches


def find_orphan_fl64_pids() -> list[int]:
    """Return PIDs of FL64.exe processes whose parent is claude.exe."""
    # First, list all FL64.exe processes with parent PIDs.
    out = subprocess.run(
        [
            "wmic",
            "process",
            "where",
            "name='FL64.exe'",
            "get",
            "ProcessId,ParentProcessId",
            "/FORMAT:CSV",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    fl_entries: list[tuple[int, int]] = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("Node") or "ParentProcessId" in line:
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            parent_pid = int(parts[1])
            pid = int(parts[2])
            fl_entries.append((pid, parent_pid))
        except ValueError:
            continue

    if not fl_entries:
        return []

    # Now resolve each parent PID to a process name, filter to claude.exe.
    parent_pids = sorted({ppid for _, ppid in fl_entries})
    parent_names: dict[int, str] = {}
    for ppid in parent_pids:
        po = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                f"ProcessId={ppid}",
                "get",
                "Name",
                "/FORMAT:CSV",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        for ln in po.stdout.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("Node") or "Name" == ln.split(",")[-1]:
                continue
            parts = ln.split(",")
            if len(parts) >= 2:
                parent_names[ppid] = parts[1]
                break

    orphans = [
        pid
        for pid, ppid in fl_entries
        if parent_names.get(ppid, "").lower() == "claude.exe"
    ]
    return orphans


def close_pid(pid: int) -> bool:
    windows = enum_windows_for_pid(pid)
    if not windows:
        print(f"[close_orphan_fl] PID {pid}: no visible windows (may already be exiting)")
        return False
    print(f"[close_orphan_fl] PID {pid}: {len(windows)} visible window(s)")
    for hwnd, title in windows:
        print(f"  - hwnd={hwnd} title={title!r}  -> WM_CLOSE")
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    return True


def main() -> int:
    orphans = find_orphan_fl64_pids()
    if not orphans:
        print("[close_orphan_fl] No orphan FL64.exe found (parent != claude.exe).")
        return 0

    print(f"[close_orphan_fl] Orphan FL64.exe PIDs: {orphans}")
    for pid in orphans:
        close_pid(pid)

    # Wait up to 5s for graceful close, then verify.
    time.sleep(5.0)
    still_alive = find_orphan_fl64_pids()
    if still_alive:
        print(
            f"[close_orphan_fl] WARNING: orphans still alive after WM_CLOSE: {still_alive}"
        )
        print("  (likely a save-changes dialog is open; leave it for the user)")
        return 1

    print("[close_orphan_fl] All orphans closed cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
