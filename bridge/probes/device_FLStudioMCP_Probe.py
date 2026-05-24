# name=FLStudio MCP Probe
# url=
# version 0.1.0
"""
L0 empirical probe — answers 7 questions about FL Studio's MIDI scripting
runtime model to lock the bridge architecture before any production code.

Install:
  Copy this folder to:
    %USERPROFILE%\\Documents\\Image-Line\\FL Studio\\Settings\\Hardware\\FLStudio-MCP-Probe\\

Run:
  1. Open FL Studio.
  2. Options -> MIDI Settings.
  3. In the Input list, pick ANY input device, set "Controller type" to
     "FLStudio MCP Probe".
  4. Open View -> Script output. The probe runs automatically on init.
  5. Wait ~15 seconds — Q5 finishes when 200 OnIdle samples are collected.
  6. Press "Reload script" once. (This tests Q4 — OnDeInit firing.)
  7. Wait ~5 more seconds.
  8. Read results from:
     %USERPROFILE%\\Documents\\Image-Line\\FL Studio\\Settings\\Hardware\\FLStudio-MCP-Probe\\probe_results.json

Q1 thread survival         | spawn daemon thread, observe counter from OnIdle
Q2 cross-thread API call   | channels.channelCount() from worker (may crash FL)
Q3 processRECEvent + Note  | accept REC_Chan_NoteOn or throw?
Q4 OnDeInit on reload      | count OnInit vs OnDeInit invocations
Q5 OnIdle cadence          | record interval ms, compute p50/p99
Q6 worker print            | emit marker; manual check of Script Output window
Q7 OnUpdateLiveDisplay     | distinct from OnUpdateLiveMode or merged?

This script is read-only on the project. Q2 may crash FL — save your work
before running. Q3 attempts a REC event; on a fresh empty project it is
harmless (no channel to receive). Run on a fresh blank project to be safe.
"""

import json
import os
import sys
import time
import threading
import traceback
from pathlib import Path

import channels
import general
import patterns
import transport
import ui
import midi

# FL Studio's MIDI scripting environment does NOT define __file__ — device
# scripts are exec'd by the host rather than imported as a module. Derive
# the install path from the user's profile dir instead. This works for any
# user whose FL data lives at the documented default location.
_USER_HOME = os.path.expanduser("~")
SCRIPT_DIR = (
    Path(_USER_HOME)
    / "Documents"
    / "Image-Line"
    / "FL Studio"
    / "Settings"
    / "Hardware"
    / "FLStudio-MCP-Probe"
)
RESULTS_PATH = SCRIPT_DIR / "probe_results.json"
LOG_PATH = SCRIPT_DIR / "probe_log.txt"

# Lock + state accessed from FL callback thread AND worker thread.
_lock = threading.Lock()
state = {
    "schema_version": 1,
    "started_at": None,
    "last_write_at": None,
    "environment": {
        "python_version": None,
        "fl_version": None,
        "fl_prog_title": None,
        "script_path": str(SCRIPT_DIR / "device_FLStudioMCP_Probe.py"),
    },
    "q1_thread_survival": {
        "spawned": False,
        "thread_id": None,
        "alive_after_init": None,
        "alive_after_idle10s": None,
        "counter": 0,
        "ticks_observed": [],
        "status": "pending",
    },
    "q2_cross_thread_api": {
        "channel_count_from_worker": None,
        "exception": None,
        "fl_still_alive_after": None,
        "status": "pending",
    },
    "q3_processREC_note": {
        "attempted": False,
        "rec_id_used": None,
        "value_used": None,
        "flags_used": None,
        "exception": None,
        "post_call_observed_alive": None,
        "status": "pending",
    },
    "q4_ondeinit": {
        "init_count": 0,
        "deinit_count": 0,
        "first_init_ts": None,
        "last_deinit_ts": None,
        "status": "pending",
    },
    "q5_onidle_cadence": {
        "samples": 0,
        "intervals_ms": [],
        "p50_ms": None,
        "p90_ms": None,
        "p99_ms": None,
        "min_ms": None,
        "max_ms": None,
        "status": "pending",
    },
    "q6_worker_print": {
        "main_marker": "MAIN_THREAD_PRINT_OK",
        "worker_marker": "WORKER_THREAD_PRINT_xyzzy_42",
        "note": "Manually inspect FL's Script Output window — both markers should appear if worker-thread prints route through. Only main marker means worker prints are lost.",
        "main_emitted": False,
        "worker_emitted": False,
        "status": "manual-inspect",
    },
    "q7_live_display_vs_mode": {
        "OnUpdateLiveMode_calls": 0,
        "OnUpdateLiveDisplay_calls": 0,
        "OnUpdateLiveMode_last_args": None,
        "OnUpdateLiveDisplay_last_args": None,
        "status": "pending",
    },
}

_q5_last_idle_ts = None


def _log(msg):
    """Best-effort file log so worker-thread output is captured even if Script
    Output ignores worker prints (Q6 mitigation)."""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.time():.3f}] {msg}\n")
    except Exception:
        pass


def _write_results():
    with _lock:
        state["last_write_at"] = time.time()
        try:
            tmp = RESULTS_PATH.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, RESULTS_PATH)
        except Exception as e:
            _log(f"write_results failed: {e}")


def _worker_thread():
    """Q1 thread survival + Q2 cross-thread API call + Q6 worker print."""
    _log("worker thread started")
    try:
        with _lock:
            state["q1_thread_survival"]["thread_id"] = threading.get_ident()
        # Q6: emit marker BEFORE risky API call so Script Output gets it even
        # if Q2 crashes FL.
        print(state["q6_worker_print"]["worker_marker"])
        with _lock:
            state["q6_worker_print"]["worker_emitted"] = True
        _write_results()

        # Q2: cross-thread FL API call. May crash FL.
        _log("worker about to call channels.channelCount() — DANGER ZONE")
        try:
            cc = channels.channelCount()
            with _lock:
                state["q2_cross_thread_api"]["channel_count_from_worker"] = cc
                state["q2_cross_thread_api"]["fl_still_alive_after"] = True
                state["q2_cross_thread_api"]["status"] = "ok"
            _log(f"worker channels.channelCount() returned {cc} — FL did NOT crash")
        except Exception as e:
            with _lock:
                state["q2_cross_thread_api"]["exception"] = (
                    f"{type(e).__name__}: {e}"
                )
                state["q2_cross_thread_api"]["status"] = "exception"
            _log(f"worker channels.channelCount() raised {type(e).__name__}: {e}")
        _write_results()
    except Exception:
        _log("worker thread top-level exception:\n" + traceback.format_exc())

    # Q1: stay alive, increment counter so OnIdle can observe.
    while True:
        with _lock:
            state["q1_thread_survival"]["counter"] += 1
        time.sleep(0.5)


def _try_q3_process_rec_event():
    """Q3: does general.processRECEvent accept a REC_Chan_NoteOn event ID?"""
    try:
        # Channel-0 note-on REC ID. Per midi.py layout: REC_Chan_NoteOn is
        # at offset REC_Chan_Note_First inside the channel slice. Channel N's
        # base is N * REC_ItemRange.
        ch_idx = 0
        rec_id = midi.REC_Chan_NoteOn + ch_idx * midi.REC_ItemRange
        # Pack pitch + velocity. Encoding is best-guess; the binary outcome
        # (exception vs no-exception) is the actual answer we want.
        pitch = 60  # C4
        velocity = 100
        value = (pitch << 8) | velocity
        flags = midi.REC_Controller
        with _lock:
            state["q3_processREC_note"]["attempted"] = True
            state["q3_processREC_note"]["rec_id_used"] = rec_id
            state["q3_processREC_note"]["value_used"] = value
            state["q3_processREC_note"]["flags_used"] = flags
        general.processRECEvent(rec_id, value, flags)
        with _lock:
            state["q3_processREC_note"]["status"] = "accepted"
            state["q3_processREC_note"]["post_call_observed_alive"] = True
        _log(f"Q3 processRECEvent({rec_id}, {value}, {flags}) accepted — no exception")
    except Exception as e:
        with _lock:
            state["q3_processREC_note"]["exception"] = f"{type(e).__name__}: {e}"
            state["q3_processREC_note"]["status"] = "rejected"
        _log(f"Q3 processRECEvent raised {type(e).__name__}: {e}")
    _write_results()


def OnInit():
    _log("OnInit fired")
    with _lock:
        state["q4_ondeinit"]["init_count"] += 1
        if state["q4_ondeinit"]["first_init_ts"] is None:
            state["q4_ondeinit"]["first_init_ts"] = time.time()
            state["started_at"] = time.time()
        state["environment"]["python_version"] = sys.version
        try:
            state["environment"]["fl_version"] = ui.getVersion()
        except Exception as e:
            state["environment"]["fl_version"] = f"unknown ({type(e).__name__}: {e})"
        try:
            state["environment"]["fl_prog_title"] = ui.getProgTitle()
        except Exception:
            pass

    # Q6: emit main-thread marker.
    print("[probe] OnInit — beginning empirical sweep")
    print(state["q6_worker_print"]["main_marker"])
    with _lock:
        state["q6_worker_print"]["main_emitted"] = True

    # Q1: spawn worker thread. Stores thread + alive flag.
    try:
        t = threading.Thread(target=_worker_thread, daemon=True, name="probe-worker")
        t.start()
        with _lock:
            state["q1_thread_survival"]["spawned"] = True
            state["q1_thread_survival"]["alive_after_init"] = t.is_alive()
        _log(f"worker thread spawned, alive_after_init={t.is_alive()}")
    except Exception as e:
        with _lock:
            state["q1_thread_survival"]["status"] = "spawn-failed"
            state["q1_thread_survival"]["exception"] = (
                f"{type(e).__name__}: {e}"
            )
        _log(f"worker spawn failed: {e}")

    # Q3: attempt processRECEvent on a Note REC ID.
    _try_q3_process_rec_event()

    _write_results()


def OnDeInit():
    _log("OnDeInit fired")
    with _lock:
        state["q4_ondeinit"]["deinit_count"] += 1
        state["q4_ondeinit"]["last_deinit_ts"] = time.time()
        if state["q4_ondeinit"]["deinit_count"] >= 1:
            state["q4_ondeinit"]["status"] = "fires-on-reload"
    _write_results()


def OnIdle():
    global _q5_last_idle_ts
    now = time.time()
    if _q5_last_idle_ts is not None:
        interval_ms = (now - _q5_last_idle_ts) * 1000.0
        with _lock:
            if len(state["q5_onidle_cadence"]["intervals_ms"]) < 500:
                state["q5_onidle_cadence"]["intervals_ms"].append(interval_ms)
            state["q5_onidle_cadence"]["samples"] += 1
            samples = state["q5_onidle_cadence"]["samples"]
    else:
        with _lock:
            state["q5_onidle_cadence"]["samples"] += 1
            samples = state["q5_onidle_cadence"]["samples"]
    _q5_last_idle_ts = now

    # Q1: snapshot worker counter at a few moments.
    if samples in (1, 10, 50, 200):
        with _lock:
            state["q1_thread_survival"]["ticks_observed"].append(
                {
                    "samples": samples,
                    "counter": state["q1_thread_survival"]["counter"],
                    "ts": now,
                }
            )

    # Compute Q5 stats + lock Q1 once we have enough OnIdle data.
    if samples == 200:
        with _lock:
            intervals = sorted(state["q5_onidle_cadence"]["intervals_ms"])
            n = len(intervals)
            if n > 0:
                state["q5_onidle_cadence"]["p50_ms"] = intervals[n // 2]
                state["q5_onidle_cadence"]["p90_ms"] = intervals[min(n - 1, int(n * 0.90))]
                state["q5_onidle_cadence"]["p99_ms"] = intervals[min(n - 1, int(n * 0.99))]
                state["q5_onidle_cadence"]["min_ms"] = intervals[0]
                state["q5_onidle_cadence"]["max_ms"] = intervals[-1]
            state["q5_onidle_cadence"]["status"] = "done"
            state["q1_thread_survival"]["alive_after_idle10s"] = (
                state["q1_thread_survival"]["counter"] > 0
            )
            state["q1_thread_survival"]["status"] = (
                "alive"
                if state["q1_thread_survival"]["counter"] > 0
                else "dead-or-not-scheduled"
            )
        _write_results()
        _log(
            f"Q1+Q5 finalized at {samples} samples; counter="
            f"{state['q1_thread_survival']['counter']}"
        )


def OnMidiMsg(event):
    # Required entry point. Don't consume — pass through.
    event.handled = False


def OnRefresh(flags):
    pass


def OnUpdateLiveMode(lastTrack):
    with _lock:
        state["q7_live_display_vs_mode"]["OnUpdateLiveMode_calls"] += 1
        state["q7_live_display_vs_mode"]["OnUpdateLiveMode_last_args"] = repr(lastTrack)


def OnUpdateLiveDisplay(lastTrack):
    with _lock:
        state["q7_live_display_vs_mode"]["OnUpdateLiveDisplay_calls"] += 1
        state["q7_live_display_vs_mode"]["OnUpdateLiveDisplay_last_args"] = repr(lastTrack)
        if state["q7_live_display_vs_mode"]["OnUpdateLiveDisplay_calls"] >= 1:
            state["q7_live_display_vs_mode"]["status"] = "distinct"
