# name=FLStudio MCP Bridge
# url=https://github.com/Goldwep/FLStudio-MCP-Goldwep
# version 0.9.1-pre-bridge
"""
FL Studio MIDI device script -- in-FL half of the MCP bridge.

Architecture lock (see docs/PROBE-REPORT.md for empirical justification):

  * SINGLE-THREADED, non-blocking TCP socket polled from OnIdle.
    FL's embedded Python is a sub-interpreter with daemon threads
    explicitly disabled. We cannot spawn a socket-accept thread.

  * NO __file__ resolution. FL exec's device scripts rather than importing
    them as modules, so __file__ is not defined. We derive paths from the
    user's home directory via os.path.expanduser("~").

  * NO os.replace() / Path.rename(). The atomic-rename pattern returns NULL
    without setting an exception on Windows in FL's embedded Python. We
    write directly to the final filename and accept partial-write risk on
    crash (mitigation: ring-buffer for state that needs crash-resilience).

  * NO trust in OnDeInit. Reload Script does NOT fire OnDeInit on the prior
    instance, so socket cleanup happens defensively on OnInit:
    SO_REUSEADDR plus force-close-any-prior-server.

  * OnIdle cadence is ~50ms p50, ~86ms p99 (NOT 20ms). Per-request budget
    is ~750ms (10x p99). Up to 16 requests are processed per OnIdle tick
    to avoid stalling FL.

Wire protocol: newline-delimited JSON-RPC. Each request is one line of:

    {"id": <any>, "method": "module.method", "args": { ... }}

Each response is one line of:

    {"id": <same>, "ok": true,  "result": <value>}              -- success
    {"id": <same>, "ok": false, "error": "<class>: <msg>",      -- failure
                              "traceback": "<full traceback>"}

The DISPATCH table below covers every bridge.call("X.Y", args) issued from
src/tools/*.ts. Bridge-internal primitives ("ping", "state.*") are NOT FL
API calls -- they are MCP-side helpers implemented locally in this file.
"""

import json
import logging
import os
import socket
import time
import traceback
from logging.handlers import RotatingFileHandler
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
# Paths and logging
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
LOG_PATH = SCRIPT_DIR / "bridge.log"

log = logging.getLogger("flstudio-mcp-bridge")
log.setLevel(logging.INFO)
log.propagate = False
_log_handler_installed = False


def _install_log_handler():
    """Install a rotating file handler once SCRIPT_DIR exists.

    Idempotent -- multiple OnInit calls (FL re-exec's the script on Reload
    without firing OnDeInit, see Q4 in PROBE-REPORT.md) must not stack
    handlers.
    """
    global _log_handler_installed
    if _log_handler_installed:
        return
    try:
        SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            str(LOG_PATH), maxBytes=512 * 1024, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        log.addHandler(handler)
        _log_handler_installed = True
    except Exception as exc:  # pragma: no cover -- best-effort
        print(f"[mcp-bridge] log handler install failed: {exc}")


# ----------------------------------------------------------------------
# Module-level globals -- persist across OnInit re-runs.
#
# FL's "Reload Script" re-exec's the script body but does NOT clear the
# module dict, so any name already bound here survives the reload. This
# is the foundation of the Q4 (no-OnDeInit-on-reload) survival pattern:
# we test for an existing _server on OnInit and close it before binding
# a fresh one.
# ----------------------------------------------------------------------

HOST = "127.0.0.1"
PORT = 9876
MAX_REQUESTS_PER_TICK = 16
RECV_CHUNK = 4096
LISTEN_BACKLOG = 8

_server = None  # type: ignore  -- socket.socket or None
_conns = []  # list[dict]: {"sock": socket, "buf": bytes, "addr": tuple}

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
    """Bind the listen socket. Defensive against Reload Script (no OnDeInit)."""
    global _server, _conns
    _install_log_handler()
    log.info("OnInit fired")

    # Drop any sockets left over from a previous exec of this script.
    if _server is not None:
        try:
            _server.close()
        except Exception:
            pass
        _server = None
    for entry in _conns:
        try:
            entry["sock"].close()
        except Exception:
            pass
    _conns = []

    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.setblocking(False)
        srv.bind((HOST, PORT))
        srv.listen(LISTEN_BACKLOG)
        _server = srv
        msg = f"MCP bridge listening on {HOST}:{PORT}"
        log.info(msg)
        print(f"[mcp-bridge] {msg}")
    except Exception as exc:
        log.error(f"OnInit failed: {exc}\n{traceback.format_exc()}")
        print(f"[mcp-bridge] OnInit failed: {exc}")


def OnDeInit():
    """Best-effort teardown. Does NOT fire on Reload Script (Q4)."""
    global _server, _conns
    log.info("OnDeInit fired")
    for entry in _conns:
        try:
            entry["sock"].close()
        except Exception:
            pass
    _conns = []
    if _server is not None:
        try:
            _server.close()
        except Exception:
            pass
        _server = None


def OnIdle():
    """Pump the socket: accept new conns, drain requests, dispatch, reply."""
    global _conns

    # 1. Accept any pending connections. setblocking(False) means accept()
    #    raises BlockingIOError when nothing is queued.
    if _server is not None:
        while True:
            try:
                conn, addr = _server.accept()
            except BlockingIOError:
                break
            except Exception as exc:
                log.error(f"accept failed: {exc}")
                break
            try:
                conn.setblocking(False)
                _conns.append({"sock": conn, "buf": b"", "addr": addr})
                log.debug(f"accepted connection from {addr}")
            except Exception as exc:
                log.error(f"post-accept setup failed: {exc}")
                try:
                    conn.close()
                except Exception:
                    pass

    # 2. Drain incoming data and dispatch. Cap at MAX_REQUESTS_PER_TICK to
    #    avoid stalling FL's callback thread on a flood.
    #
    #    Per-connection recv state has three outcomes:
    #      * raises BlockingIOError -> no data ready this tick, keep alive
    #      * returns b""             -> peer closed the connection, drop it
    #      * returns non-empty bytes -> append to buffer and frame-parse
    processed = 0
    for entry in list(_conns):
        if processed >= MAX_REQUESTS_PER_TICK:
            break
        sock = entry["sock"]

        peer_closed = False
        try:
            chunk = sock.recv(RECV_CHUNK)
            if chunk == b"":
                peer_closed = True
            else:
                entry["buf"] += chunk
        except BlockingIOError:
            pass  # no data ready; keep the connection alive
        except Exception as exc:
            log.error(f"recv failed: {exc}")
            _drop_conn(entry)
            continue

        # Process every newline-terminated frame in the buffer.
        while b"\n" in entry["buf"]:
            if processed >= MAX_REQUESTS_PER_TICK:
                break
            line, _, entry["buf"] = entry["buf"].partition(b"\n")
            if not line.strip():
                continue
            response = _handle_request(line)
            try:
                sock.sendall(response + b"\n")
            except Exception as exc:
                log.error(f"send failed: {exc}")
                _drop_conn(entry)
                peer_closed = False  # already dropped
                break
            processed += 1

        if peer_closed:
            _drop_conn(entry)


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
                "flag_name": _CE_FLAG_NAMES.get(flag, f"CE_{flag}"),
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
# Connection management helpers
# ----------------------------------------------------------------------


def _drop_conn(entry):
    """Close and forget a connection."""
    global _conns
    try:
        entry["sock"].close()
    except Exception:
        pass
    try:
        _conns.remove(entry)
    except ValueError:
        pass


# ----------------------------------------------------------------------
# Request handler
# ----------------------------------------------------------------------


def _handle_request(raw):
    """Parse one JSON-RPC request, dispatch, return JSON-encoded response bytes."""
    req = None
    req_id = None
    try:
        req = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        if not isinstance(req, dict):
            return _err_response(None, "BadRequest: payload must be a JSON object")
        req_id = req.get("id")
        method = req.get("method")
        if not isinstance(method, str):
            return _err_response(req_id, "BadRequest: missing 'method' string")
        args = req.get("args") or {}
        if not isinstance(args, dict):
            return _err_response(req_id, "BadRequest: 'args' must be an object")
        handler = DISPATCH.get(method)
        if handler is None:
            return _err_response(req_id, f"UnknownMethod: {method}")
        try:
            result = handler(**args)
        except TypeError as exc:
            # Argument-shape mismatch -- include the method name so the
            # MCP server can diff its bridge.call signature against this
            # handler's positional arguments.
            return _err_response(
                req_id,
                f"BadArgs in {method}: {exc}",
                traceback.format_exc(),
            )
        return _ok_response(req_id, result)
    except Exception as exc:
        return _err_response(
            req_id,
            f"{type(exc).__name__}: {exc}",
            traceback.format_exc(),
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
