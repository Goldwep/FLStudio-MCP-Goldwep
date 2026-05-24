"""
Smoke test for bridge/device_FLStudioMCP.py.

Mocks the FL-injected modules (channels, mixer, patterns, transport, etc.)
and the FL-side `midi` constants, then runs the device script as a normal
Python program. Exercises:

- OnInit binds the socket cleanly
- Socket round-trip: ping, channels.channelCount, mixer.trackCount,
  general.getProjectTitle, plus a few representative read/write/composite
  dispatch entries.
- Error paths: unknown method, handler raises (returns ok:false).
- OnIdle drains pending requests.
- OnDeInit closes the socket.

This is the closest we can get to integration testing without actually
running FL Studio. Catches typos in DISPATCH, signature mismatches between
the handler shim and the mocked FL function, framing bugs in the socket
loop, etc.

Real-FL integration test is documented in docs/INSTALL.md (one user-side
action: assign the controller in MIDI Settings).

Run:
    python tests/bridge_device_smoke.py
"""

from __future__ import annotations

import json
import socket
import sys
import time
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEVICE_SCRIPT = REPO_ROOT / "bridge" / "device_FLStudioMCP.py"


# ---------------------------------------------------------------------------
# Mock FL-injected modules
# ---------------------------------------------------------------------------

_mock_channels_state = {
    "count": 3,
    "names": ["Kick", "Snare", "Hat"],
    "colors": [0x00FF0000, 0x0000FF00, 0x000000FF],  # BGRA
    "volumes": [0.78, 0.65, 0.50],
    "pans": [-0.1, 0.0, 0.2],
    "muted": [False, False, False],
}

_mock_mixer_state = {
    "count": 16,
    "names": ["Master"] + [f"Insert {i}" for i in range(1, 16)],
}

_mock_patterns_state = {
    "count": 1,
    "current": 1,
    "names": {1: "Pattern 1"},
}

_mock_transport_state = {
    "playing": False,
    "recording": False,
    "song_pos": 0,
}

_mock_general_state = {
    "title": "Untitled.flp",
    "changed_flag": 0,
    "rec_ppb": 96,
}

# Track what the script CALLS so we can assert on side effects.
_mock_calls: list[tuple[str, tuple, dict]] = []


def _record(name):
    def wrapper(*args, **kwargs):
        _mock_calls.append((name, args, kwargs))
        return None

    return wrapper


def _build_mock_modules() -> None:
    channels = types.ModuleType("channels")
    channels.channelCount = lambda: _mock_channels_state["count"]
    channels.getChannelName = lambda i: _mock_channels_state["names"][i]
    channels.getChannelColor = lambda i: _mock_channels_state["colors"][i]
    channels.getChannelVolume = lambda i: _mock_channels_state["volumes"][i]
    channels.getChannelPan = lambda i: _mock_channels_state["pans"][i]
    channels.getTargetFxTrack = lambda i: i + 1
    channels.getChannelType = lambda i: 0  # CT_Sampler
    channels.setChannelName = _record("channels.setChannelName")
    channels.setChannelVolume = _record("channels.setChannelVolume")
    channels.setChannelPan = _record("channels.setChannelPan")
    channels.setChannelColor = _record("channels.setChannelColor")
    channels.setTargetFxTrack = _record("channels.setTargetFxTrack")
    channels.selectChannel = _record("channels.selectChannel")
    channels.muteChannel = _record("channels.muteChannel")
    channels.soloChannel = _record("channels.soloChannel")
    channels.midiNoteOn = _record("channels.midiNoteOn")
    channels.getGridBit = lambda idx, pos: 1 if (idx + pos) % 2 == 0 else 0
    channels.setGridBit = _record("channels.setGridBit")
    channels.getCurrentStepParam = lambda idx, step, param: 100
    channels.setStepParameterByIndex = _record("channels.setStepParameterByIndex")
    sys.modules["channels"] = channels

    mixer = types.ModuleType("mixer")
    mixer.trackCount = lambda: _mock_mixer_state["count"]
    mixer.getTrackName = lambda i: _mock_mixer_state["names"][i]
    mixer.getTrackColor = lambda i: 0x00808080
    mixer.getTrackVolume = lambda i: 0.8
    mixer.getTrackPan = lambda i: 0.0
    mixer.isTrackMuted = lambda i: False
    mixer.isTrackSoloed = lambda i: False
    mixer.getTrackPeaks = lambda i, mode=0: 0.5
    mixer.setTrackName = _record("mixer.setTrackName")
    mixer.setTrackVolume = _record("mixer.setTrackVolume")
    mixer.setTrackPan = _record("mixer.setTrackPan")
    mixer.setTrackColor = _record("mixer.setTrackColor")
    mixer.muteTrack = _record("mixer.muteTrack")
    mixer.soloTrack = _record("mixer.soloTrack")
    mixer.armTrack = _record("mixer.armTrack")
    mixer.linkChannelToTrack = _record("mixer.linkChannelToTrack")
    mixer.linkTrackToChannel = _record("mixer.linkTrackToChannel")
    mixer.setRouteTo = _record("mixer.setRouteTo")
    mixer.afterRoutingChanged = _record("mixer.afterRoutingChanged")
    mixer.setRouteToLevel = _record("mixer.setRouteToLevel")
    mixer.setEqGain = _record("mixer.setEqGain")
    mixer.setEqFrequency = _record("mixer.setEqFrequency")
    mixer.setCurrentTempo = _record("mixer.setCurrentTempo")
    sys.modules["mixer"] = mixer

    patterns = types.ModuleType("patterns")
    patterns.patternCount = lambda: _mock_patterns_state["count"]
    patterns.patternNumber = lambda: _mock_patterns_state["current"]
    patterns.getPatternName = lambda i: _mock_patterns_state["names"].get(i, f"Pattern {i}")
    patterns.getPatternColor = lambda i: 0x00FFFF00
    patterns.getPatternLength = lambda i: 16
    patterns.selectPattern = _record("patterns.selectPattern")
    patterns.jumpToPattern = _record("patterns.jumpToPattern")
    patterns.setPatternName = _record("patterns.setPatternName")
    patterns.setPatternColor = _record("patterns.setPatternColor")
    patterns.setPatternLength = _record("patterns.setPatternLength")
    sys.modules["patterns"] = patterns

    transport = types.ModuleType("transport")
    transport.start = _record("transport.start")
    transport.stop = _record("transport.stop")
    transport.isPlaying = lambda: 1 if _mock_transport_state["playing"] else 0
    transport.isRecording = lambda: _mock_transport_state["recording"]
    transport.record = _record("transport.record")
    transport.setLoopMode = _record("transport.setLoopMode")
    transport.getSongPos = lambda unit=0: _mock_transport_state["song_pos"]
    transport.getSongLength = lambda unit=0: 1000
    transport.setSongPos = _record("transport.setSongPos")
    transport.globalTransport = _record("transport.globalTransport")
    sys.modules["transport"] = transport

    general = types.ModuleType("general")
    general.getProjectTitle = lambda: _mock_general_state["title"]
    general.getRecPPB = lambda: _mock_general_state["rec_ppb"]
    general.getUseMetronome = lambda: False
    general.getChangedFlag = lambda: _mock_general_state["changed_flag"]
    general.undo = _record("general.undo")
    general.processRECEvent = _record("general.processRECEvent")
    sys.modules["general"] = general

    playlist = types.ModuleType("playlist")
    playlist.trackCount = lambda: 4
    playlist.getTrackName = lambda i: f"Track {i}"
    playlist.getTrackColor = lambda i: 0x00808080
    playlist.isTrackMuted = lambda i: False
    playlist.getDisplayZone = lambda: 0
    sys.modules["playlist"] = playlist

    arrangement = types.ModuleType("arrangement")
    arrangement.currentTime = lambda snap=0: 1234
    sys.modules["arrangement"] = arrangement

    plugins = types.ModuleType("plugins")
    plugins.getPluginName = lambda idx, slot=-1, fallback=False: "MockPlugin"
    plugins.getParamCount = lambda idx, slot=-1: 8
    plugins.getParamName = lambda p, idx, slot=-1: f"Param {p}"
    plugins.getParamValue = lambda p, idx, slot=-1: 0.5
    plugins.setParamValue = _record("plugins.setParamValue")
    plugins.nextPreset = _record("plugins.nextPreset")
    plugins.prevPreset = _record("plugins.prevPreset")
    sys.modules["plugins"] = plugins

    ui = types.ModuleType("ui")
    ui.getVisible = lambda widget: True
    ui.getFocusedFormID = lambda: -1
    ui.getVersion = lambda: "MockFL v0.0"
    ui.getProgTitle = lambda: "MockFL"
    sys.modules["ui"] = ui

    midi = types.ModuleType("midi")
    midi.REC_Chan_NoteOn = 0x4000
    midi.REC_ItemRange = 0x10000
    midi.REC_Controller = 981
    midi.REC_Tempo = 0x40000 + 5
    midi.FPT_Save = 92
    midi.FPT_TapTempo = 106
    midi.FPT_Metronome = 110
    midi.PME_System_Safe = 4
    sys.modules["midi"] = midi


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------


def _request(sock: socket.socket, request_id: int, method: str, args=None):
    payload = {"id": request_id, "method": method}
    if args is not None:
        payload["args"] = args
    sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))


def _wait_for_response(sock: socket.socket, device_globals, max_ticks=40):
    """Drain OnIdle until a response arrives, with a budget."""
    sock.settimeout(0.001)
    buf = b""
    for _ in range(max_ticks):
        device_globals["OnIdle"]()
        try:
            chunk = sock.recv(4096)
            if chunk:
                buf += chunk
                if b"\n" in buf:
                    line, _, _ = buf.partition(b"\n")
                    return json.loads(line.decode("utf-8"))
        except (BlockingIOError, socket.timeout):
            pass
        time.sleep(0.02)
    raise AssertionError(f"no response within {max_ticks} ticks; buffer={buf!r}")


def main() -> int:
    _build_mock_modules()

    # Load the device script
    device_globals: dict = {"__name__": "__main__"}
    exec(compile(DEVICE_SCRIPT.read_text(encoding="utf-8"), str(DEVICE_SCRIPT), "exec"), device_globals)

    print(f"[smoke] device script loaded ({len(device_globals.get('DISPATCH', {}))} dispatch entries)")

    # OnInit binds the socket
    try:
        device_globals["OnInit"]()
    except Exception as e:
        print(f"[smoke] OnInit FAILED: {e}")
        return 1

    failures = []
    client = None
    try:
        # Allow OS a moment to publish the listen
        time.sleep(0.1)
        client = socket.create_connection(("127.0.0.1", 9876), timeout=2.0)
        client.setblocking(False)

        # --- 1. ping ---
        _request(client, 1, "ping")
        resp = _wait_for_response(client, device_globals)
        assert resp["ok"], f"ping not ok: {resp}"
        assert resp["result"]["pong"] is True, f"ping result: {resp}"
        print(f"[smoke] ping OK: {resp['result']}")

        # --- 2. channels.channelCount ---
        _request(client, 2, "channels.channelCount")
        resp = _wait_for_response(client, device_globals)
        assert resp["ok"] and resp["result"] == 3, f"channelCount: {resp}"
        print(f"[smoke] channels.channelCount = {resp['result']}")

        # --- 3. channels.getChannelName ---
        _request(client, 3, "channels.getChannelName", {"index": 1})
        resp = _wait_for_response(client, device_globals)
        assert resp["ok"] and resp["result"] == "Snare", f"getChannelName: {resp}"
        print(f"[smoke] channels.getChannelName(1) = {resp['result']!r}")

        # --- 4. mixer.trackCount ---
        _request(client, 4, "mixer.trackCount")
        resp = _wait_for_response(client, device_globals)
        assert resp["ok"] and resp["result"] == 16, f"mixer.trackCount: {resp}"
        print(f"[smoke] mixer.trackCount = {resp['result']}")

        # --- 5. mixer.getTrackName(0) — Master ---
        _request(client, 5, "mixer.getTrackName", {"index": 0})
        resp = _wait_for_response(client, device_globals)
        assert resp["ok"] and resp["result"] == "Master", f"mixer.getTrackName: {resp}"
        print(f"[smoke] mixer.getTrackName(0) = {resp['result']!r}")

        # --- 6. patterns.patternCount ---
        _request(client, 6, "patterns.patternCount")
        resp = _wait_for_response(client, device_globals)
        assert resp["ok"] and resp["result"] == 1, f"patternCount: {resp}"
        print(f"[smoke] patterns.patternCount = {resp['result']}")

        # --- 7. general.getProjectTitle ---
        _request(client, 7, "general.getProjectTitle")
        resp = _wait_for_response(client, device_globals)
        assert resp["ok"] and resp["result"] == "Untitled.flp", f"getProjectTitle: {resp}"
        print(f"[smoke] general.getProjectTitle = {resp['result']!r}")

        # --- 8. write-side: channels.setChannelVolume — verify side effect ---
        _record_count_before = len([c for c in _mock_calls if c[0] == "channels.setChannelVolume"])
        _request(client, 8, "channels.setChannelVolume", {"index": 0, "value": 0.9})
        resp = _wait_for_response(client, device_globals)
        assert resp["ok"], f"setChannelVolume: {resp}"
        _record_count_after = len([c for c in _mock_calls if c[0] == "channels.setChannelVolume"])
        assert _record_count_after == _record_count_before + 1, "side effect not recorded"
        last_call = [c for c in _mock_calls if c[0] == "channels.setChannelVolume"][-1]
        assert last_call[1] == (0, 0.9), f"args were {last_call[1]}"
        print(f"[smoke] channels.setChannelVolume(0, 0.9) recorded side effect OK")

        # --- 9. composite: mixer.setRouteTo + afterRoutingChanged ---
        before_set = len([c for c in _mock_calls if c[0] == "mixer.setRouteTo"])
        before_after = len([c for c in _mock_calls if c[0] == "mixer.afterRoutingChanged"])
        _request(client, 9, "mixer.setRouteTo", {"source": 1, "dest": 2, "value": 1})
        resp = _wait_for_response(client, device_globals)
        assert resp["ok"], f"setRouteTo: {resp}"
        after_set = len([c for c in _mock_calls if c[0] == "mixer.setRouteTo"])
        # Caller pattern is two MCP calls (setRouteTo, then afterRoutingChanged separately);
        # bridge.call("mixer.setRouteTo") only dispatches setRouteTo here.
        assert after_set == before_set + 1, "setRouteTo not recorded"
        # afterRoutingChanged is a separate bridge call:
        _request(client, 10, "mixer.afterRoutingChanged")
        resp = _wait_for_response(client, device_globals)
        assert resp["ok"], f"afterRoutingChanged: {resp}"
        after_after = len([c for c in _mock_calls if c[0] == "mixer.afterRoutingChanged"])
        assert after_after == before_after + 1, "afterRoutingChanged not recorded"
        print(f"[smoke] mixer setRouteTo + afterRoutingChanged composite OK")

        # --- 10. bridge-internal: state.setSubscribed + state.drainChanges ---
        _request(client, 11, "state.setSubscribed", {"enabled": True})
        resp = _wait_for_response(client, device_globals)
        assert resp["ok"] and resp["result"]["subscribed"] is True, f"setSubscribed: {resp}"
        print(f"[smoke] state.setSubscribed(True) -> {resp['result']}")

        # Trigger an OnDirty event manually
        if "OnDirtyChannel" in device_globals:
            device_globals["OnDirtyChannel"](0, 0)  # CE_New
            device_globals["OnDirtyMixerTrack"](-1)

        _request(client, 12, "state.drainChanges")
        resp = _wait_for_response(client, device_globals)
        assert resp["ok"], f"drainChanges: {resp}"
        events = resp["result"]
        assert isinstance(events, list) and len(events) >= 2, f"drainChanges events: {events}"
        kinds = {e["kind"] for e in events}
        assert "channel" in kinds and "mixer_track" in kinds, f"missing kinds: {kinds}"
        print(f"[smoke] state.drainChanges -> {len(events)} events: {kinds}")

        # --- 11. bridge composite: general.saveProject -> transport.globalTransport(FPT_Save,...) ---
        before_gt = len([c for c in _mock_calls if c[0] == "transport.globalTransport"])
        _request(client, 13, "general.saveProject")
        resp = _wait_for_response(client, device_globals)
        assert resp["ok"], f"saveProject: {resp}"
        after_gt = len([c for c in _mock_calls if c[0] == "transport.globalTransport"])
        assert after_gt == before_gt + 1, "saveProject did not translate to globalTransport"
        last_call = [c for c in _mock_calls if c[0] == "transport.globalTransport"][-1]
        # First positional arg should be FPT_Save=92
        assert 92 in last_call[1], f"FPT_Save not in args: {last_call[1]}"
        print(f"[smoke] general.saveProject -> globalTransport({last_call[1]}) OK")

        # --- 12. error path: unknown method ---
        _request(client, 99, "channels.thisDoesNotExist")
        resp = _wait_for_response(client, device_globals)
        assert not resp["ok"], f"unknown method should fail: {resp}"
        print(f"[smoke] unknown method correctly errors: {resp.get('error')[:60]}...")

    except AssertionError as e:
        failures.append(str(e))
    except Exception as e:
        import traceback as _tb

        failures.append(f"unexpected: {type(e).__name__}: {e}\n{_tb.format_exc()}")
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass
        try:
            device_globals["OnDeInit"]()
        except Exception as e:
            failures.append(f"OnDeInit raised: {e}")

    if failures:
        print(f"\n[smoke] FAILED ({len(failures)} failures):")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"\n[smoke] ALL OK — {len([c for c in _mock_calls])} mock FL calls recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
