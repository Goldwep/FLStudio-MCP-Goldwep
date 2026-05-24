# name=FLStudio MCP Probe 2
# url=
# version 0.1.0
"""
Probe 2 — does processRECEvent(REC_Chan_NoteOn, ...) actually MODIFY
project state, or is it a silent no-op?

L0 confirmed the call is ACCEPTED (no exception). What we don't know yet
is whether anything actually happened — REC events can be silently dropped
when there's no recordable target. This probe answers that via FL's own
"changed since save" flag: if the flag goes from 0 (clean) to 1 (dirty)
across the REC call, the call had side effects and a note likely landed.

Non-destructive — does NOT save the project. Only observes the dirty
flag delta. Run on a SAVED clean project (flag should start at 0).

Install: same flow as probe 1. Set Controller type to "FLStudio MCP
Probe 2" on any input port and enable.

Output: probe2_results.json next to this script.
"""

import os
import sys
import json
import time
import traceback
from pathlib import Path

import channels
import general
import patterns
import transport
import ui
import midi

_USER_HOME = os.path.expanduser("~")
SCRIPT_DIR = (
    Path(_USER_HOME)
    / "Documents"
    / "Image-Line"
    / "FL Studio"
    / "Settings"
    / "Hardware"
    / "FLStudio-MCP-Probe-2"
)
RESULTS_PATH = SCRIPT_DIR / "probe2_results.json"
LOG_PATH = SCRIPT_DIR / "probe2_log.txt"

state = {
    "schema_version": 1,
    "started_at": None,
    "environment": {
        "python_version": None,
        "fl_version": None,
        "fl_prog_title": None,
    },
    "preconditions": {
        "channel_count": None,
        "changed_flag_before": None,
        "current_pattern": None,
    },
    "rec_call": {
        "attempted": False,
        "rec_id": None,
        "value": None,
        "flags": None,
        "exception": None,
        "fl_alive_after": None,
    },
    "postconditions": {
        "changed_flag_after": None,
        "changed_flag_delta": None,
        "current_pattern_after": None,
    },
    "verdict": "pending",
}


def _log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.time():.3f}] {msg}\n")
    except Exception:
        pass


def _write_results():
    # Direct write — os.replace is broken in FL's embedded Python on Windows.
    try:
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        _log(f"write failed: {e}")


def OnInit():
    _log("OnInit fired")
    state["started_at"] = time.time()
    state["environment"]["python_version"] = sys.version
    try:
        state["environment"]["fl_version"] = ui.getVersion()
    except Exception:
        pass
    try:
        state["environment"]["fl_prog_title"] = ui.getProgTitle()
    except Exception:
        pass

    # Preconditions
    try:
        cc = channels.channelCount()
        state["preconditions"]["channel_count"] = cc
    except Exception as e:
        _log(f"channelCount failed: {e}")
        cc = 0

    if cc < 1:
        state["verdict"] = "no-channel"
        _log("verdict: no-channel (need at least 1 channel in the rack)")
        _write_results()
        return

    try:
        state["preconditions"]["changed_flag_before"] = general.getChangedFlag()
    except Exception as e:
        _log(f"getChangedFlag (before) failed: {e}")

    try:
        state["preconditions"]["current_pattern"] = patterns.patternNumber()
    except Exception as e:
        _log(f"patternNumber failed: {e}")

    print(
        f"[probe2] preconditions: channels={cc}, "
        f"changed_flag={state['preconditions']['changed_flag_before']}, "
        f"pattern={state['preconditions']['current_pattern']}"
    )

    # The REC call
    try:
        ch_idx = 0
        rec_id = midi.REC_Chan_NoteOn + ch_idx * midi.REC_ItemRange
        pitch = 60  # C4
        velocity = 100
        value = (pitch << 8) | velocity
        flags = midi.REC_Controller

        state["rec_call"]["attempted"] = True
        state["rec_call"]["rec_id"] = rec_id
        state["rec_call"]["value"] = value
        state["rec_call"]["flags"] = flags

        _log(f"calling processRECEvent({rec_id}, {value}, {flags})")
        general.processRECEvent(rec_id, value, flags)
        state["rec_call"]["fl_alive_after"] = True
        _log("processRECEvent returned cleanly")
    except Exception as e:
        state["rec_call"]["exception"] = f"{type(e).__name__}: {e}"
        _log(f"processRECEvent raised: {e}\n{traceback.format_exc()}")

    # Postconditions
    try:
        state["postconditions"]["changed_flag_after"] = general.getChangedFlag()
    except Exception as e:
        _log(f"getChangedFlag (after) failed: {e}")

    try:
        state["postconditions"]["current_pattern_after"] = patterns.patternNumber()
    except Exception:
        pass

    before = state["preconditions"]["changed_flag_before"]
    after = state["postconditions"]["changed_flag_after"]
    if before is not None and after is not None:
        delta = after - before
        state["postconditions"]["changed_flag_delta"] = delta
        if delta > 0:
            state["verdict"] = "MODIFIED"
        elif delta == 0 and after > 0:
            state["verdict"] = "ALREADY-DIRTY"  # can't tell if probe caused it
        else:
            state["verdict"] = "NO-OP"

    _log(
        f"verdict: {state['verdict']} "
        f"(changed_flag {before} -> {after}, delta={state['postconditions']['changed_flag_delta']})"
    )
    print(
        f"[probe2] verdict: {state['verdict']} "
        f"(changed_flag {before} -> {after})"
    )

    _write_results()


def OnDeInit():
    _log("OnDeInit fired")
    _write_results()


def OnIdle():
    pass


def OnMidiMsg(event):
    event.handled = False


def OnRefresh(flags):
    pass
