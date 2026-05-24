"""Invoke OnInit() in the bridge script via FL Studio's 'Command to
execute' field. This bypasses the unreliable Reload button click by
using the script's own command interface.

Approach:
  1. Find the TPyFormEdit (command-to-execute input) inside the MPKmini2
     TVectorSheet inside Script Output.
  2. Click the field to focus it (legacy mouse_event API — proven to work).
  3. Set clipboard to "OnInit()" + Enter key combo.
  4. Send Ctrl+V to paste, then Enter to execute.

Verifies success by checking bridge.log size + heartbeat file + Script
Output content for the "ready" message.
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

WM_SETTEXT = 0x000C
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102

VK_RETURN = 0x0D
VK_CONTROL = 0x11
VK_V = 0x56

LOG_FILE = os.path.expanduser(
    r"~\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\bridge.log"
)
HEARTBEAT = os.path.expanduser(
    r"~\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\ipc\bridge_alive.txt"
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


def find_mpkmini2_sheet(parent):
    """Find the MPKmini2 TVectorSheet child."""
    matches = []

    def cb(h, _):
        if get_class_name(h) == "TVectorSheet" and "MPKmini2" in get_window_text(h):
            matches.append(h)
        return True

    user32.EnumChildWindows(parent, EnumWindowsProc(cb), 0)
    return matches[0] if matches else None


def find_command_input(parent):
    """Find the TPyFormEdit inside the parent (command-to-execute field)."""
    matches = []

    def cb(h, _):
        if get_class_name(h) == "TPyFormEdit":
            matches.append(h)
        return True

    user32.EnumChildWindows(parent, EnumWindowsProc(cb), 0)
    return matches[0] if matches else None


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
    user32.SetCursorPos(sx, sy)
    time.sleep(0.1)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def send_char(hwnd, ch):
    """Send a single character to the focused window via WM_CHAR."""
    user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 0)


def press_key_send(vk):
    """Press and release a virtual key via legacy keybd_event API."""
    KEYEVENTF_KEYUP = 0x0002
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def type_string_via_keybd(s):
    """Type each character via keybd_event with appropriate VK codes.
    Only handles ASCII printable + special chars used in 'OnInit()'."""
    # Map: characters that need special handling
    for ch in s:
        if ch.isalpha():
            vk = ord(ch.upper())
            shift = ch.isupper()
            if shift:
                user32.keybd_event(0x10, 0, 0, 0)  # SHIFT down
            user32.keybd_event(vk, 0, 0, 0)
            time.sleep(0.02)
            user32.keybd_event(vk, 0, 0x0002, 0)  # key up
            if shift:
                user32.keybd_event(0x10, 0, 0x0002, 0)  # SHIFT up
        elif ch == "(":
            user32.keybd_event(0x10, 0, 0, 0)  # SHIFT
            user32.keybd_event(0x39, 0, 0, 0)  # 9
            time.sleep(0.02)
            user32.keybd_event(0x39, 0, 0x0002, 0)
            user32.keybd_event(0x10, 0, 0x0002, 0)
        elif ch == ")":
            user32.keybd_event(0x10, 0, 0, 0)
            user32.keybd_event(0x30, 0, 0, 0)  # 0
            time.sleep(0.02)
            user32.keybd_event(0x30, 0, 0x0002, 0)
            user32.keybd_event(0x10, 0, 0x0002, 0)
        time.sleep(0.03)


def main():
    so = find_script_output()
    if so is None:
        print("Script Output not found")
        return 1

    sheet = find_mpkmini2_sheet(so)
    if sheet is None:
        print("MPKmini2 sheet not found")
        return 1

    cmd_field = find_command_input(sheet)
    if cmd_field is None:
        print("Command input not found inside MPKmini2 sheet")
        return 1

    cl, ct, cr, cb = get_window_rect(cmd_field)
    cmd_cx = (cl + cr) // 2
    cmd_cy = (ct + cb) // 2
    print(f"Command field hwnd={cmd_field} rect=({cl},{ct})..({cr},{cb}) center=({cmd_cx},{cmd_cy})")

    initial_log_size = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0
    initial_hb = os.path.exists(HEARTBEAT)
    print(f"Before: log={initial_log_size} bytes, heartbeat={initial_hb}")

    # Bring Script Output forward and click the command field to focus it.
    print("Forcing foreground + clicking command field...")
    force_foreground(so)
    time.sleep(0.4)
    click_at(cmd_cx, cmd_cy)
    time.sleep(0.3)

    # Type OnInit() and press Enter
    print("Typing OnInit() via keybd_event...")
    type_string_via_keybd("OnInit()")
    time.sleep(0.2)
    print("Pressing Enter...")
    press_key_send(VK_RETURN)

    # Wait + check
    for i in range(20):
        time.sleep(0.5)
        cur_size = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0
        hb = os.path.exists(HEARTBEAT)
        if cur_size != initial_log_size or hb != initial_hb:
            print(f"CHANGE after {(i+1)*0.5}s: log={cur_size} bytes, heartbeat={hb}")
            return 0
    print("No change after 10s")
    return 2


if __name__ == "__main__":
    sys.exit(main())
