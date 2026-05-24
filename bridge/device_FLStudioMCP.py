# name=FLStudio MCP Bridge
# url=https://github.com/Goldwep/FLStudio-MCP-Goldwep
# version 0.9.2-file-ipc
"""
FL Studio MIDI device script -- in-FL half of the MCP bridge.

Architecture lock (see docs/PROBE-REPORT.md for empirical justification):

  * FILE-BASED IPC, NOT SOCKETS. Live-FL integration on 2026-05-24 found
    that socket.socket() returns SystemError "NULL without setting an
    exception" for every socket type (TCP/UDP/_socket) in FL's embedded
    Python 3.12.1 sub-interpreter. We pivoted to a file-IPC channel:
        Node writes  req_<id>.json   to ipc/
        FL reads + dispatches + writes resp_<id>.json
        Node polls + reads + unlinks resp_<id>.json
    Same single-threaded OnIdle pump as before; the framing changed.

  * SINGLE-THREADED OnIdle pump. FL's embedded Python is a sub-interpreter
    with daemon threads explicitly disabled. We cannot spawn workers; the
    only execution surface for the bridge is the OnIdle callback FL itself
    drives at ~50ms p50 / ~86ms p99.

  * NO mkdir / makedirs / pathlib.mkdir. All three return NULL-without-
    exception in this interpreter, even with exist_ok=True against an
    existing directory. The IPC folder must be pre-created externally
    (the installer creates it before FL ever loads this script).

  * NO os.replace / Path.rename. Atomic-rename pattern also broken. Write
    directly to the final filename; accept partial-write risk on crash.

  * NO logging module FileHandler -- it calls os.makedirs internally and
    will hit the broken mkdir. Direct open(LOG_PATH, "a").write() instead.

  * NO __file__. FL exec's device scripts rather than importing them, so
    __file__ is undefined. Paths derive from os.path.expanduser("~").

  * NO trust in OnDeInit. Reload Script does NOT fire OnDeInit on the prior
    instance, so any cleanup happens defensively on OnInit (drain leftover
    request files from the IPC folder).

  * OnIdle cadence ~50ms p50, ~86ms p99. We cap at 8 requests per tick to
    avoid stalling FL's callback thread on a flood.

Wire protocol: one JSON object per file. Each request:

    ipc/req_<id>.json: {"id": <any>, "method": "module.method", "args": {...}}

Each response:

    ipc/resp_<id>.json: {"id": <same>, "ok": true,  "result": <value>}
    ipc/resp_<id>.json: {"id": <same>, "ok": false, "error": "<class>: <msg>",
                                       "traceback": "<full traceback>"}

The DISPATCH table at the bottom covers every bridge.call("X.Y", args)
issued from src/tools/*.ts. Bridge-internal primitives ("ping", "state.*")
are NOT FL API calls -- they are MCP-side helpers implemented locally.
"""

import json
import os
import time
import traceback
from pathlib import Path

# FL-injected modules. These only exist when this script is exec'd inside
# FL Studio's MIDI scripting host. Importing them outside FL raises
# ModuleNotFoundError -- the syntax check via ast.parse() never executes
# the imports, so a host-less syntax check is fine.
import channels
import mixer
import patterns
import transport
import general
import playlist
import arrangement
import plugins
import ui
import midi

# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------

_USER_HOME = os.path.expanduser("~")
SCRIPT_DIR = (
    Path(_USER_HOME)
    / "Documents"
    / "Image-Line"
    / "FL Studio"
    / "Settings"
    / "Hardware"
    / "FLStudio-MCP"
)
IPC_DIR = SCRIPT_DIR / "ipc"
LOG_PATH = SCRIPT_DIR / "bridge.log"
HEARTBEAT_PATH = IPC_DIR / "bridge_alive.txt"


# ----------------------------------------------------------------------
# Logging -- direct open()+write(), no FileHandler (FileHandler calls
# os.makedirs internally which is broken in FL's embedded Python).
# ----------------------------------------------------------------------


def _log(level, msg):
    """Append a single timestamped line to LOG_PATH. Best-effort."""
    line = "%s %s %s\n" % (
        time.strftime("%Y-%m-%d %H:%M:%S"),
        level,
        msg,
    )
    # print() reaches FL's Script Output tab so the user sees errors
    # even if the log file is unwritable.
    if level in ("WARN", "ERROR"):
        print("[mcp-bridge] %s %s" % (level, msg))
    try:
        with open(str(LOG_PATH), "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        # Best-effort -- a logging failure must never break the dispatch loop.
        pass


# ----------------------------------------------------------------------
# Module-level globals -- persist across OnInit re-runs.
#
# FL's "Reload Script" re-exec's the script body but does NOT clear the
# module dict, so any name already bound here survives the reload. This
# is the foundation of the Q4 (no-OnDeInit-on-reload) survival pattern.
# ----------------------------------------------------------------------

MAX_REQUESTS_PER_TICK = 8

# State-sync subscription (L8b primitives).
_subscribed = False
_dirty_events = []  # list[dict]

# Bound flag-name table for OnDirtyChannel. CE_* constants live in midi
# but spell out a flag -> name map here so the JSON event is human-readable.
_CE_FLAG_NAMES = {
    0: "CE_New",
    1: "CE_Delete",
    2: "CE_Replace",
    3: "CE_Rename",
    4: "CE_Select",
}


# ----------------------------------------------------------------------
# FL device-script entry points
# ----------------------------------------------------------------------


def OnInit():
    """Initialize bridge. Defensive against Reload Script (no OnDeInit)."""
    _log("INFO", "OnInit fired (file-IPC bridge)")
    _log("INFO", "IPC dir: %s" % IPC_DIR)

    # The IPC folder MUST already exist -- the installer creates it. We
    # cannot create it here (mkdir is broken). Verify presence + log clearly
    # if it is missing so the user knows what to do.
    if not os.path.isdir(str(IPC_DIR)):
        _log(
            "ERROR",
            "IPC directory does not exist: %s -- please create it manually "
            "(mkdir is broken in FL's embedded Python; the installer "
            "normally pre-creates it)." % IPC_DIR,
        )
        return

    # Drop any leftover req_* and resp_* files from a previous exec. A stale
    # response could otherwise satisfy a fresh Node request with the wrong
    # data; a stale request would get re-dispatched against fresh state.
    drained = _cleanup_ipc_dir()
    _log("INFO", "OnInit: drained %d leftover ipc files" % drained)

    # Write a heartbeat file so Node-side `wait_for_bridge` can detect us
    # before the first real request. Content is just the start timestamp.
    try:
        with open(str(HEARTBEAT_PATH), "w", encoding="utf-8") as fh:
            fh.write(str(int(time.time() * 1000)))
    except Exception as exc:
        _log("WARN", "OnInit: could not write heartbeat: %s" % exc)

    msg = "MCP file-IPC bridge ready at %s" % IPC_DIR
    _log("INFO", msg)
    print("[mcp-bridge] %s" % msg)


def OnDeInit():
    """Best-effort teardown. Does NOT fire on Reload Script (Q4)."""
    _log("INFO", "OnDeInit fired")
    # Best-effort heartbeat removal so a stale heartbeat doesn't fool the
    # Node side into thinking FL is still up.
    try:
        if os.path.isfile(str(HEARTBEAT_PATH)):
            os.remove(str(HEARTBEAT_PATH))
    except Exception:
        pass


def OnIdle():
    """Pump the file IPC channel: scan ipc/, dispatch, write responses."""
    if not os.path.isdir(str(IPC_DIR)):
        return

    try:
        entries = os.listdir(str(IPC_DIR))
    except Exception as exc:
        _log("WARN", "OnIdle: listdir failed: %s" % exc)
        return

    # Filter to request files. We deliberately ignore anything else (resp_*,
    # bridge_alive.txt, log files, future extensions) so the IPC folder can
    # safely host non-IPC artifacts.
    req_names = []
    for name in entries:
        if name.startswith("req_") and name.endswith(".json"):
            req_names.append(name)

    if not req_names:
        return

    # Stable order so older requests dispatch first even if listdir returns
    # them out of order. File names embed an incrementing id from the Node
    # side, so lexical sort is "good enough" (zero-padded numeric would be
    # strictly correct, but ids reset to 1 per process so lexical works
    # within a single Node session).
    req_names.sort()

    processed = 0
    for name in req_names:
        if processed >= MAX_REQUESTS_PER_TICK:
            break
        req_path = IPC_DIR / name

        # Read + delete + dispatch + write response. If anything fails we
        # try hard to delete the request file so we don't get stuck looping
        # on a poison request.
        raw = None
        try:
            with open(str(req_path), "r", encoding="utf-8") as fh:
                raw = fh.read()
        except Exception as exc:
            _log("WARN", "OnIdle: could not read %s: %s" % (name, exc))
            _safe_remove(req_path)
            continue

        # Delete the request file BEFORE dispatching. If the handler raises
        # or stalls, the request is already off the queue -- it won't be
        # picked up again on the next tick. The cost: if FL crashes mid-
        # dispatch, the request is lost and the Node caller will time out.
        _safe_remove(req_path)

        response_bytes, req_id = _handle_request(raw)

        # Write the response file. Node polls for resp_<id>.json with the
        # matching id; if the write fails we log and move on (the caller
        # will time out, which is the correct surface).
        resp_path = IPC_DIR / ("resp_%s.json" % _id_for_filename(req_id))
        try:
            with open(str(resp_path), "w", encoding="utf-8") as fh:
                fh.write(response_bytes.decode("utf-8"))
        except Exception as exc:
            _log(
                "ERROR",
                "OnIdle: could not write %s: %s" % (resp_path.name, exc),
            )

        processed += 1


def OnMidiMsg(event):
    """Required entry point. Bridge does NOT consume MIDI -- pass through."""
    event.handled = False


# ----------------------------------------------------------------------
# State-sync OnDirty* callbacks. Effects are gated by _subscribed so
# unsubscribed callers pay near-zero cost.
# ----------------------------------------------------------------------


def OnDirtyChannel(index, flag=0):
    if _subscribed:
        _dirty_events.append(
            {
                "kind": "channel",
                "index": index,
                "flag": flag,
                "flag_name": _CE_FLAG_NAMES.get(flag, "CE_%s" % flag),
            }
        )


def OnDirtyMixerTrack(index):
    if _subscribed:
        _dirty_events.append({"kind": "mixer_track", "index": index})


def OnRefresh(flags):
    if _subscribed:
        _dirty_events.append({"kind": "refresh", "flags": flags})


def OnUpdateBeatIndicator(value):
    if _subscribed:
        _dirty_events.append({"kind": "beat", "value": value})


# ----------------------------------------------------------------------
# IPC helpers
# ----------------------------------------------------------------------


def _cleanup_ipc_dir():
    """Drop leftover req_*.json + resp_*.json from a previous session."""
    if not os.path.isdir(str(IPC_DIR)):
        return 0
    try:
        names = os.listdir(str(IPC_DIR))
    except Exception:
        return 0
    removed = 0
    for name in names:
        if (name.startswith("req_") or name.startswith("resp_")) and name.endswith(".json"):
            if _safe_remove(IPC_DIR / name):
                removed += 1
    return removed


def _safe_remove(path):
    """Best-effort file removal. Returns True if file is gone afterward."""
    try:
        os.remove(str(path))
        return True
    except FileNotFoundError:
        return True
    except Exception as exc:
        _log("WARN", "remove failed for %s: %s" % (path, exc))
        return False


def _id_for_filename(req_id):
    """Render a request id as a filename-safe string."""
    if req_id is None:
        return "null"
    return str(req_id)


# ----------------------------------------------------------------------
# Request handler
# ----------------------------------------------------------------------


def _handle_request(raw):
    """
    Parse one JSON-RPC request, dispatch, return (response_bytes, req_id).

    Returning the req_id alongside the response lets the OnIdle pump pick
    the correct resp_<id>.json filename even when the request payload was
    malformed (best-effort fallback to "null").
    """
    req_id = None
    try:
        req = json.loads(raw)
        if not isinstance(req, dict):
            return (
                _err_response(None, "BadRequest: payload must be a JSON object"),
                None,
            )
        req_id = req.get("id")
        method = req.get("method")
        if not isinstance(method, str):
            return (
                _err_response(req_id, "BadRequest: missing 'method' string"),
                req_id,
            )
        args = req.get("args") or {}
        if not isinstance(args, dict):
            return (
                _err_response(req_id, "BadRequest: 'args' must be an object"),
                req_id,
            )
        handler = DISPATCH.get(method)
        if handler is None:
            return (
                _err_response(req_id, "UnknownMethod: %s" % method),
                req_id,
            )
        try:
            result = handler(**args)
        except TypeError as exc:
            # Argument-shape mismatch -- include the method name so the
            # MCP server can diff its bridge.call signature against this
            # handler's positional arguments.
            return (
                _err_response(
                    req_id,
                    "BadArgs in %s: %s" % (method, exc),
                    traceback.format_exc(),
                ),
                req_id,
            )
        return (_ok_response(req_id, result), req_id)
    except Exception as exc:
        return (
            _err_response(
                req_id,
                "%s: %s" % (type(exc).__name__, exc),
                traceback.format_exc(),
            ),
            req_id,
        )


def _ok_response(req_id, result):
    return json.dumps({"id": req_id, "ok": True, "result": result}).encode("utf-8")


def _err_response(req_id, error, tb=None):
    payload = {"id": req_id, "ok": False, "error": error}
    if tb is not None:
        payload["traceback"] = tb
    return json.dumps(payload).encode("utf-8")


# ----------------------------------------------------------------------
# Bridge-internal handlers (NOT FL API calls).
# These exist solely as MCP-side primitives -- health check + state-sync.
# ----------------------------------------------------------------------


def _bridge_ping():
    """Liveness check. Returns pong + millisecond timestamp."""
    return {"pong": True, "ts": int(time.time() * 1000)}


def _bridge_state_set_subscribed(enabled=True):
    """Toggle the OnDirty* event accumulator."""
    global _subscribed
    _subscribed = bool(enabled)
    return {"subscribed": _subscribed}


def _bridge_state_drain_changes():
    """Drain and return the accumulated event queue."""
    global _dirty_events
    drained = _dirty_events
    _dirty_events = []
    return drained


# ----------------------------------------------------------------------
# Bridge-side composites and translations.
# Where the MCP server uses a simple verb that does not map 1:1 to an FL
# API call (toggleMetronome, tapTempo, saveProject), we translate here.
# ----------------------------------------------------------------------


def _transport_toggle_metronome():
    """FPT_Metronome = 110 -- bridge composite over globalTransport."""
    transport.globalTransport(midi.FPT_Metronome, 1)
    return True


def _transport_tap_tempo():
    """FPT_TapTempo = 106 -- bridge composite over globalTransport."""
    transport.globalTransport(midi.FPT_TapTempo, 1)
    return True


def _general_save_project():
    """FPT_Save = 92 -- bridge composite over globalTransport."""
    transport.globalTransport(midi.FPT_Save, 1)
    return True


# ----------------------------------------------------------------------
# FL API pass-through handlers
#
# One handler per dispatch entry. Most are 1-2 line forwards into the
# matching FL module. Where the MCP tool's args dict shape differs from
# FL's positional argument order, the handler does the translation.
# ----------------------------------------------------------------------

# --- channels ---------------------------------------------------------


def _channels_channel_count():
    return channels.channelCount()


def _channels_get_channel_name(index):
    return channels.getChannelName(index)


def _channels_get_channel_color(index):
    return channels.getChannelColor(index)


def _channels_get_channel_volume(index):
    return channels.getChannelVolume(index)


def _channels_get_channel_pan(index):
    return channels.getChannelPan(index)


def _channels_get_target_fx_track(index):
    return channels.getTargetFxTrack(index)


def _channels_get_channel_type(index):
    return channels.getChannelType(index)


def _channels_set_channel_name(index, name):
    channels.setChannelName(index, name)
    return True


def _channels_set_channel_volume(index, value):
    channels.setChannelVolume(index, value)
    return True


def _channels_set_channel_pan(index, value):
    channels.setChannelPan(index, value)
    return True


def _channels_set_channel_color(index, color):
    channels.setChannelColor(index, color)
    return True


def _channels_set_target_fx_track(index, fxIndex):
    channels.setTargetFxTrack(index, fxIndex)
    return True


def _channels_select_channel(index, value=-1):
    channels.selectChannel(index, value)
    return True


def _channels_mute_channel(index, value=-1):
    channels.muteChannel(index, value)
    return True


def _channels_solo_channel(index):
    channels.soloChannel(index)
    return True


def _channels_get_grid_bit(index, position):
    return channels.getGridBit(index, position)


def _channels_set_grid_bit(index, position, value):
    channels.setGridBit(index, position, value)
    return True


def _channels_get_current_step_param(index, step, param):
    return channels.getCurrentStepParam(index, step, param)


def _channels_set_step_parameter_by_index(index, step, param, value):
    channels.setStepParameterByIndex(index, step, param, value)
    return True


def _channels_midi_note_on(channel_index, note, velocity, midi_channel=0):
    channels.midiNoteOn(channel_index, note, velocity, midi_channel)
    return True


# --- patterns ---------------------------------------------------------


def _patterns_pattern_count():
    return patterns.patternCount()


def _patterns_pattern_number():
    return patterns.patternNumber()


def _patterns_get_pattern_name(index):
    return patterns.getPatternName(index)


def _patterns_get_pattern_color(index):
    return patterns.getPatternColor(index)


def _patterns_get_pattern_length(index):
    return patterns.getPatternLength(index)


def _patterns_select_pattern(index, value=-1, preview=0):
    patterns.selectPattern(index, value, preview)
    return True


def _patterns_jump_to_pattern(index):
    patterns.jumpToPattern(index)
    return True


def _patterns_set_pattern_name(index, name):
    patterns.setPatternName(index, name)
    return True


def _patterns_set_pattern_color(index, color):
    patterns.setPatternColor(index, color)
    return True


def _patterns_set_pattern_length(index, length):
    patterns.setPatternLength(index, length)
    return True


# --- mixer ------------------------------------------------------------


def _mixer_track_count():
    return mixer.trackCount()


def _mixer_get_track_name(index):
    return mixer.getTrackName(index)


def _mixer_get_track_color(index):
    return mixer.getTrackColor(index)


def _mixer_get_track_volume(index):
    return mixer.getTrackVolume(index)


def _mixer_get_track_pan(index):
    return mixer.getTrackPan(index)


def _mixer_is_track_muted(index):
    return mixer.isTrackMuted(index)


def _mixer_is_track_soloed(index):
    return mixer.isTrackSoloed(index)


def _mixer_get_track_peaks(index, mode):
    return mixer.getTrackPeaks(index, mode)


def _mixer_set_track_name(index, name):
    mixer.setTrackName(index, name)
    return True


def _mixer_set_track_volume(index, value):
    mixer.setTrackVolume(index, value)
    return True


def _mixer_set_track_pan(index, value):
    mixer.setTrackPan(index, value)
    return True


def _mixer_set_track_color(index, color):
    mixer.setTrackColor(index, color)
    return True


def _mixer_mute_track(index, value=-1):
    mixer.muteTrack(index, value)
    return True


def _mixer_solo_track(index, value=-1):
    mixer.soloTrack(index, value)
    return True


def _mixer_arm_track(index):
    mixer.armTrack(index)
    return True


def _mixer_link_channel_to_track(channel, track, select=0):
    # [UNVERIFIED] manual-only API per audit -- AttributeError surfaces
    # cleanly if FL's mixer module lacks linkChannelToTrack.
    mixer.linkChannelToTrack(channel, track, select)
    return True


def _mixer_link_track_to_channel(mode):
    mixer.linkTrackToChannel(mode)
    return True


def _mixer_set_route_to(source, dest, value):
    mixer.setRouteTo(source, dest, value)
    return True


def _mixer_after_routing_changed():
    mixer.afterRoutingChanged()
    return True


def _mixer_set_route_to_level(source, dest, level):
    # [UNVERIFIED] manual-only API per audit.
    mixer.setRouteToLevel(source, dest, level)
    return True


def _mixer_set_eq_gain(index, band, value):
    # [UNVERIFIED] vendor uses ambiguous arg order. We pass (index, band,
    # value); SMK-37 tries both. Probe needed to confirm round-trip.
    mixer.setEqGain(index, band, value)
    return True


def _mixer_set_eq_frequency(index, band, value):
    # [UNVERIFIED] no vendor caller.
    mixer.setEqFrequency(index, band, value)
    return True


def _mixer_set_current_tempo(bpm):
    # [UNVERIFIED] manual-only API per audit; REC-event path is the
    # vendor-preferred alternative. AttributeError if absent.
    mixer.setCurrentTempo(bpm)
    return True


# --- transport --------------------------------------------------------


def _transport_start():
    transport.start()
    return True


def _transport_stop():
    transport.stop()
    return True


def _transport_is_playing():
    return transport.isPlaying()


def _transport_record():
    transport.record()
    return True


def _transport_is_recording():
    return transport.isRecording()


def _transport_set_loop_mode():
    # Toggle-only per the FL API -- no argument.
    transport.setLoopMode()
    return True


def _transport_set_song_pos(position, mode=2):
    # mode default = SONGLENGTH_ABSTICKS (2). MCP side passes explicitly.
    transport.setSongPos(position, mode)
    return True


def _transport_get_song_pos(unit=2):
    return transport.getSongPos(unit)


def _transport_get_song_length(unit=2):
    # [UNVERIFIED] no vendor caller.
    return transport.getSongLength(unit)


# --- general ----------------------------------------------------------


def _general_get_project_title():
    return general.getProjectTitle()


def _general_undo():
    general.undo()
    return True


def _general_get_changed_flag():
    return general.getChangedFlag()


def _general_get_rec_ppb():
    # [UNVERIFIED] manual-only; vendor uses getRecPPQ.
    return general.getRecPPB()


def _general_get_use_metronome():
    return general.getUseMetronome()


# --- arrangement ------------------------------------------------------


def _arrangement_current_time(snap):
    # [UNVERIFIED] manual-only; vendor uses currentTimeHint(mode).
    return arrangement.currentTime(snap)


# --- playlist ---------------------------------------------------------


def _playlist_track_count():
    return playlist.trackCount()


def _playlist_get_track_name(index):
    return playlist.getTrackName(index)


def _playlist_get_track_color(index):
    return playlist.getTrackColor(index)


def _playlist_is_track_muted(index):
    return playlist.isTrackMuted(index)


def _playlist_get_display_zone():
    return playlist.getDisplayZone()


# --- plugins ----------------------------------------------------------


def _plugins_get_plugin_name(index, slotIndex=-1):
    return plugins.getPluginName(index, slotIndex)


def _plugins_get_param_count(index, slotIndex=-1):
    return plugins.getParamCount(index, slotIndex)


def _plugins_get_param_name(index, paramIndex, slotIndex=-1):
    return plugins.getParamName(paramIndex, index, slotIndex)


def _plugins_get_param_value(index, paramIndex, slotIndex=-1):
    return plugins.getParamValue(paramIndex, index, slotIndex)


def _plugins_set_param_value(index, paramIndex, value, slotIndex=-1):
    plugins.setParamValue(value, paramIndex, index, slotIndex)
    return True


def _plugins_next_preset(channel):
    plugins.nextPreset(channel)
    return True


def _plugins_prev_preset(channel):
    plugins.prevPreset(channel)
    return True


# --- ui ---------------------------------------------------------------


def _ui_get_visible(widget):
    return ui.getVisible(widget)


def _ui_get_focused_form_id():
    # [UNVERIFIED] manual-only.
    return ui.getFocusedFormID()


# ----------------------------------------------------------------------
# DISPATCH TABLE
#
# Every bridge.call("X.Y", ...) issued by src/tools/*.ts maps to exactly
# one entry here. Source of truth for the contract is the audit at
# Claude-Brain/_scratch/flstudio-mcp-research/bridge-contract-audit.md
# AND the actual current TS sources under src/tools/.
# ----------------------------------------------------------------------

DISPATCH = {
    # Bridge-internal -----------------------------------------------
    "ping": _bridge_ping,
    "state.setSubscribed": _bridge_state_set_subscribed,
    "state.drainChanges": _bridge_state_drain_changes,
    # channels.* ----------------------------------------------------
    "channels.channelCount": _channels_channel_count,
    "channels.getChannelName": _channels_get_channel_name,
    "channels.getChannelColor": _channels_get_channel_color,
    "channels.getChannelVolume": _channels_get_channel_volume,
    "channels.getChannelPan": _channels_get_channel_pan,
    "channels.getTargetFxTrack": _channels_get_target_fx_track,
    "channels.getChannelType": _channels_get_channel_type,
    "channels.setChannelName": _channels_set_channel_name,
    "channels.setChannelVolume": _channels_set_channel_volume,
    "channels.setChannelPan": _channels_set_channel_pan,
    "channels.setChannelColor": _channels_set_channel_color,
    "channels.setTargetFxTrack": _channels_set_target_fx_track,
    "channels.selectChannel": _channels_select_channel,
    "channels.muteChannel": _channels_mute_channel,
    "channels.soloChannel": _channels_solo_channel,
    "channels.getGridBit": _channels_get_grid_bit,
    "channels.setGridBit": _channels_set_grid_bit,
    "channels.getCurrentStepParam": _channels_get_current_step_param,
    "channels.setStepParameterByIndex": _channels_set_step_parameter_by_index,
    "channels.midiNoteOn": _channels_midi_note_on,
    # patterns.* ----------------------------------------------------
    "patterns.patternCount": _patterns_pattern_count,
    "patterns.patternNumber": _patterns_pattern_number,
    "patterns.getPatternName": _patterns_get_pattern_name,
    "patterns.getPatternColor": _patterns_get_pattern_color,
    "patterns.getPatternLength": _patterns_get_pattern_length,
    "patterns.selectPattern": _patterns_select_pattern,
    "patterns.jumpToPattern": _patterns_jump_to_pattern,
    "patterns.setPatternName": _patterns_set_pattern_name,
    "patterns.setPatternColor": _patterns_set_pattern_color,
    "patterns.setPatternLength": _patterns_set_pattern_length,
    # mixer.* -------------------------------------------------------
    "mixer.trackCount": _mixer_track_count,
    "mixer.getTrackName": _mixer_get_track_name,
    "mixer.getTrackColor": _mixer_get_track_color,
    "mixer.getTrackVolume": _mixer_get_track_volume,
    "mixer.getTrackPan": _mixer_get_track_pan,
    "mixer.isTrackMuted": _mixer_is_track_muted,
    "mixer.isTrackSoloed": _mixer_is_track_soloed,
    "mixer.getTrackPeaks": _mixer_get_track_peaks,
    "mixer.setTrackName": _mixer_set_track_name,
    "mixer.setTrackVolume": _mixer_set_track_volume,
    "mixer.setTrackPan": _mixer_set_track_pan,
    "mixer.setTrackColor": _mixer_set_track_color,
    "mixer.muteTrack": _mixer_mute_track,
    "mixer.soloTrack": _mixer_solo_track,
    "mixer.armTrack": _mixer_arm_track,
    "mixer.linkChannelToTrack": _mixer_link_channel_to_track,
    "mixer.linkTrackToChannel": _mixer_link_track_to_channel,
    "mixer.setRouteTo": _mixer_set_route_to,
    "mixer.afterRoutingChanged": _mixer_after_routing_changed,
    "mixer.setRouteToLevel": _mixer_set_route_to_level,
    "mixer.setEqGain": _mixer_set_eq_gain,
    "mixer.setEqFrequency": _mixer_set_eq_frequency,
    "mixer.setCurrentTempo": _mixer_set_current_tempo,
    # transport.* ---------------------------------------------------
    "transport.start": _transport_start,
    "transport.stop": _transport_stop,
    "transport.isPlaying": _transport_is_playing,
    "transport.record": _transport_record,
    "transport.isRecording": _transport_is_recording,
    "transport.setLoopMode": _transport_set_loop_mode,
    "transport.setSongPos": _transport_set_song_pos,
    "transport.getSongPos": _transport_get_song_pos,
    "transport.getSongLength": _transport_get_song_length,
    "transport.toggleMetronome": _transport_toggle_metronome,
    "transport.tapTempo": _transport_tap_tempo,
    # general.* -----------------------------------------------------
    "general.getProjectTitle": _general_get_project_title,
    "general.undo": _general_undo,
    "general.saveProject": _general_save_project,
    "general.getChangedFlag": _general_get_changed_flag,
    "general.getRecPPB": _general_get_rec_ppb,
    "general.getUseMetronome": _general_get_use_metronome,
    # arrangement.* -------------------------------------------------
    "arrangement.currentTime": _arrangement_current_time,
    # playlist.* ----------------------------------------------------
    "playlist.trackCount": _playlist_track_count,
    "playlist.getTrackName": _playlist_get_track_name,
    "playlist.getTrackColor": _playlist_get_track_color,
    "playlist.isTrackMuted": _playlist_is_track_muted,
    "playlist.getDisplayZone": _playlist_get_display_zone,
    # plugins.* -----------------------------------------------------
    "plugins.getPluginName": _plugins_get_plugin_name,
    "plugins.getParamCount": _plugins_get_param_count,
    "plugins.getParamName": _plugins_get_param_name,
    "plugins.getParamValue": _plugins_get_param_value,
    "plugins.setParamValue": _plugins_set_param_value,
    "plugins.nextPreset": _plugins_next_preset,
    "plugins.prevPreset": _plugins_prev_preset,
    # ui.* ----------------------------------------------------------
    "ui.getVisible": _ui_get_visible,
    "ui.getFocusedFormID": _ui_get_focused_form_id,
}
