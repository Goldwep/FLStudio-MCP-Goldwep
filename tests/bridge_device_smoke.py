"""
Smoke test for bridge/device_FLStudioMCP.py (file-IPC version).

Mocks the FL-injected modules (channels, mixer, patterns, transport, etc.)
and the FL-side `midi` constants, then runs the device script as a normal
Python program. Exercises EVERY entry in the DISPATCH table (88 total).

File-IPC contract recap:
    ipc/req_<id>.json   — client writes; FL reads + deletes + dispatches
    ipc/resp_<id>.json  — FL writes;     client reads + deletes

Test flow:
    1. Create a temp IPC dir, then redirect the device script's IPC_DIR /
       LOG_PATH / HEARTBEAT_PATH at it via monkey-patching after exec.
    2. Call OnInit -- should drain leftovers (test pre-creates one to
       prove the cleanup happens) and write the heartbeat file.
    3. For every DISPATCH entry, write req_<id>.json, call OnIdle in a
       loop until resp_<id>.json appears, assert ok:true.
    4. Spot-check the original 13 architectural scenarios (composites,
       state.subscribe + drainChanges, unknown-method error path).
    5. Final assertion: 100% DISPATCH coverage (88/88).

Real-FL integration uses `npx tsx scripts/verify-live.ts`.

Run:
    python tests/bridge_device_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEVICE_SCRIPT = REPO_ROOT / "bridge" / "device_FLStudioMCP.py"


# ---------------------------------------------------------------------------
# Mock FL-injected modules (same shape as the socket-era smoke test)
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
# File-IPC client helpers (we play the role of FileBridge here)
# ---------------------------------------------------------------------------


def _send_request(ipc_dir: Path, request_id, method, args=None):
    """Write req_<id>.json. Returns the path used."""
    payload = {"id": request_id, "method": method}
    if args is not None:
        payload["args"] = args
    req_path = ipc_dir / f"req_{request_id}.json"
    with open(req_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload))
    return req_path


def _wait_for_response(ipc_dir: Path, request_id, device_globals, max_ticks=40):
    """Pump OnIdle until resp_<id>.json appears. Returns the parsed dict."""
    resp_path = ipc_dir / f"resp_{request_id}.json"
    for _ in range(max_ticks):
        device_globals["OnIdle"]()
        if resp_path.exists():
            with open(resp_path, "r", encoding="utf-8") as fh:
                raw = fh.read()
            os.remove(resp_path)
            return json.loads(raw)
        time.sleep(0.005)
    raise AssertionError(
        f"no response within {max_ticks} ticks for id={request_id} "
        f"(req file present={ (ipc_dir / f'req_{request_id}.json').exists() }, "
        f"resp file present={resp_path.exists()})"
    )


def _roundtrip(ipc_dir: Path, request_id, method, device_globals, args=None):
    """Send + wait. Returns the response dict."""
    _send_request(ipc_dir, request_id, method, args)
    return _wait_for_response(ipc_dir, request_id, device_globals)


# ---------------------------------------------------------------------------
# Per-dispatch-entry probe table — mirrors scripts/verify-live.ts
# ---------------------------------------------------------------------------

DISPATCH_PROBES: list[tuple[str, dict, str]] = [
    # -- bridge-internal --
    ("ping", {}, "internal"),
    ("state.setSubscribed", {"enabled": False}, "internal"),
    ("state.drainChanges", {}, "internal"),
    # -- channels --
    ("channels.channelCount", {}, "read"),
    ("channels.getChannelName", {"index": 0}, "read"),
    ("channels.getChannelColor", {"index": 0}, "read"),
    ("channels.getChannelVolume", {"index": 0}, "read"),
    ("channels.getChannelPan", {"index": 0}, "read"),
    ("channels.getTargetFxTrack", {"index": 0}, "read"),
    ("channels.getChannelType", {"index": 0}, "read"),
    ("channels.setChannelName", {"index": 0, "name": "Probe"}, "write"),
    ("channels.setChannelVolume", {"index": 0, "value": 0.7}, "write"),
    ("channels.setChannelPan", {"index": 0, "value": 0.0}, "write"),
    ("channels.setChannelColor", {"index": 0, "color": 0x808080}, "write"),
    ("channels.setTargetFxTrack", {"index": 0, "fxIndex": 1}, "write"),
    ("channels.selectChannel", {"index": 0, "value": -1}, "write"),
    ("channels.muteChannel", {"index": 0, "value": -1}, "write"),
    ("channels.soloChannel", {"index": 0}, "write"),
    ("channels.getGridBit", {"index": 0, "position": 0}, "read"),
    ("channels.setGridBit", {"index": 0, "position": 0, "value": 1}, "write"),
    ("channels.getCurrentStepParam", {"index": 0, "step": 0, "param": 0}, "read"),
    (
        "channels.setStepParameterByIndex",
        {"index": 0, "step": 0, "param": 0, "value": 100},
        "write",
    ),
    (
        "channels.midiNoteOn",
        {"channel_index": 0, "note": 60, "velocity": 100, "midi_channel": 0},
        "write",
    ),
    # -- patterns --
    ("patterns.patternCount", {}, "read"),
    ("patterns.patternNumber", {}, "read"),
    ("patterns.getPatternName", {"index": 1}, "read"),
    ("patterns.getPatternColor", {"index": 1}, "read"),
    ("patterns.getPatternLength", {"index": 1}, "read"),
    ("patterns.selectPattern", {"index": 1, "value": -1, "preview": 0}, "write"),
    ("patterns.jumpToPattern", {"index": 1}, "write"),
    ("patterns.setPatternName", {"index": 1, "name": "Probe"}, "write"),
    ("patterns.setPatternColor", {"index": 1, "color": 0x808080}, "write"),
    ("patterns.setPatternLength", {"index": 1, "length": 16}, "write"),
    # -- mixer --
    ("mixer.trackCount", {}, "read"),
    ("mixer.getTrackName", {"index": 0}, "read"),
    ("mixer.getTrackColor", {"index": 0}, "read"),
    ("mixer.getTrackVolume", {"index": 0}, "read"),
    ("mixer.getTrackPan", {"index": 0}, "read"),
    ("mixer.isTrackMuted", {"index": 0}, "read"),
    ("mixer.isTrackSoloed", {"index": 0}, "read"),
    ("mixer.getTrackPeaks", {"index": 0, "mode": 0}, "read"),
    ("mixer.setTrackName", {"index": 1, "name": "Probe"}, "write"),
    ("mixer.setTrackVolume", {"index": 1, "value": 0.8}, "write"),
    ("mixer.setTrackPan", {"index": 1, "value": 0.0}, "write"),
    ("mixer.setTrackColor", {"index": 1, "color": 0x808080}, "write"),
    ("mixer.muteTrack", {"index": 1, "value": -1}, "write"),
    ("mixer.soloTrack", {"index": 1, "value": -1}, "write"),
    ("mixer.armTrack", {"index": 1}, "write"),
    ("mixer.linkChannelToTrack", {"channel": 0, "track": 1, "select": 0}, "write"),
    ("mixer.linkTrackToChannel", {"mode": 0}, "write"),
    ("mixer.setRouteTo", {"source": 1, "dest": 0, "value": -1}, "write"),
    ("mixer.afterRoutingChanged", {}, "write"),
    ("mixer.setRouteToLevel", {"source": 1, "dest": 0, "level": 1.0}, "write"),
    ("mixer.setEqGain", {"index": 1, "band": 0, "value": 0.5}, "write"),
    ("mixer.setEqFrequency", {"index": 1, "band": 0, "value": 0.5}, "write"),
    ("mixer.setCurrentTempo", {"bpm": 120.0}, "write"),
    # -- transport --
    ("transport.start", {}, "write"),
    ("transport.stop", {}, "write"),
    ("transport.isPlaying", {}, "read"),
    ("transport.record", {}, "write"),
    ("transport.isRecording", {}, "read"),
    ("transport.setLoopMode", {}, "write"),
    ("transport.setSongPos", {"position": 0, "mode": 2}, "write"),
    ("transport.getSongPos", {"unit": 2}, "read"),
    ("transport.getSongLength", {"unit": 2}, "read"),
    ("transport.toggleMetronome", {}, "write"),  # composite -> globalTransport
    ("transport.tapTempo", {}, "write"),  # composite -> globalTransport
    # -- general --
    ("general.getProjectTitle", {}, "read"),
    ("general.undo", {}, "write"),
    ("general.saveProject", {}, "write"),  # composite -> globalTransport(FPT_Save, 1)
    ("general.getChangedFlag", {}, "read"),
    ("general.getRecPPB", {}, "read"),
    ("general.getUseMetronome", {}, "read"),
    # -- arrangement --
    ("arrangement.currentTime", {"snap": 0}, "read"),
    # -- playlist --
    ("playlist.trackCount", {}, "read"),
    ("playlist.getTrackName", {"index": 1}, "read"),
    ("playlist.getTrackColor", {"index": 1}, "read"),
    ("playlist.isTrackMuted", {"index": 1}, "read"),
    ("playlist.getDisplayZone", {}, "read"),
    # -- plugins --
    ("plugins.getPluginName", {"index": 0, "slotIndex": -1}, "read"),
    ("plugins.getParamCount", {"index": 0, "slotIndex": -1}, "read"),
    ("plugins.getParamName", {"index": 0, "paramIndex": 0, "slotIndex": -1}, "read"),
    ("plugins.getParamValue", {"index": 0, "paramIndex": 0, "slotIndex": -1}, "read"),
    (
        "plugins.setParamValue",
        {"index": 0, "paramIndex": 0, "value": 0.5, "slotIndex": -1},
        "write",
    ),
    ("plugins.nextPreset", {"channel": 0}, "write"),
    ("plugins.prevPreset", {"channel": 0}, "write"),
    # -- ui --
    ("ui.getVisible", {"widget": 0}, "read"),
    ("ui.getFocusedFormID", {}, "read"),
]


def _run_dispatch_coverage(ipc_dir: Path, device_globals) -> tuple[int, int, int, list[str]]:
    """
    Send every DISPATCH entry once, count successful round-trips.
    Returns (ok_reads, ok_writes, ok_internal, failures).
    """
    next_id = 1000
    ok_reads = 0
    ok_writes = 0
    ok_internal = 0
    failures: list[str] = []

    for method, args, kind in DISPATCH_PROBES:
        next_id += 1
        try:
            resp = _roundtrip(ipc_dir, next_id, method, device_globals, args)
        except AssertionError as e:
            failures.append(f"{method}: timed out — {e}")
            continue
        if not resp.get("ok"):
            failures.append(f"{method}: not ok — {resp.get('error')}")
            continue
        if kind == "read":
            ok_reads += 1
        elif kind == "write":
            ok_writes += 1
        else:
            ok_internal += 1

    return ok_reads, ok_writes, ok_internal, failures


def main() -> int:
    _build_mock_modules()

    # ---- Create a temp IPC dir and patch the device script onto it. ----
    tmpdir = Path(tempfile.mkdtemp(prefix="flstudio-mcp-smoke-"))
    ipc_dir = tmpdir / "ipc"
    ipc_dir.mkdir()  # Normal Python -- works fine here. FL is the one that can't.

    # Pre-create a stale leftover request file. OnInit should drain it.
    leftover = ipc_dir / "req_9999.json"
    leftover.write_text(json.dumps({"id": 9999, "method": "ping"}), encoding="utf-8")

    # Load the device script
    device_globals: dict = {"__name__": "__main__"}
    exec(
        compile(DEVICE_SCRIPT.read_text(encoding="utf-8"), str(DEVICE_SCRIPT), "exec"),
        device_globals,
    )

    # Override the paths to point at our temp dir (Path objects so they
    # work with the same str() conversion the device script uses).
    device_globals["SCRIPT_DIR"] = tmpdir
    device_globals["IPC_DIR"] = ipc_dir
    device_globals["LOG_PATH"] = tmpdir / "bridge.log"
    device_globals["HEARTBEAT_PATH"] = ipc_dir / "bridge_alive.txt"

    dispatch_count = len(device_globals.get("DISPATCH", {}))
    print(f"[smoke] device script loaded ({dispatch_count} dispatch entries)")
    print(f"[smoke] tmp IPC dir: {ipc_dir}")

    # OnInit cleans up leftover and writes heartbeat
    try:
        device_globals["OnInit"]()
    except Exception as e:
        print(f"[smoke] OnInit FAILED: {e}")
        return 1

    failures = []

    # OnInit should have removed the leftover.
    if leftover.exists():
        failures.append(f"OnInit did not drain stale request file {leftover}")
    # And written the heartbeat.
    if not (ipc_dir / "bridge_alive.txt").exists():
        failures.append("OnInit did not write bridge_alive.txt heartbeat")

    try:
        # --- 1. ping ---
        resp = _roundtrip(ipc_dir, 1, "ping", device_globals)
        assert resp["ok"], f"ping not ok: {resp}"
        assert resp["result"]["pong"] is True, f"ping result: {resp}"
        print(f"[smoke] ping OK: {resp['result']}")

        # --- 2. channels.channelCount ---
        resp = _roundtrip(ipc_dir, 2, "channels.channelCount", device_globals)
        assert resp["ok"] and resp["result"] == 3, f"channelCount: {resp}"
        print(f"[smoke] channels.channelCount = {resp['result']}")

        # --- 3. channels.getChannelName ---
        resp = _roundtrip(ipc_dir, 3, "channels.getChannelName", device_globals, {"index": 1})
        assert resp["ok"] and resp["result"] == "Snare", f"getChannelName: {resp}"
        print(f"[smoke] channels.getChannelName(1) = {resp['result']!r}")

        # --- 4. mixer.trackCount ---
        resp = _roundtrip(ipc_dir, 4, "mixer.trackCount", device_globals)
        assert resp["ok"] and resp["result"] == 16, f"mixer.trackCount: {resp}"
        print(f"[smoke] mixer.trackCount = {resp['result']}")

        # --- 5. mixer.getTrackName(0) — Master ---
        resp = _roundtrip(ipc_dir, 5, "mixer.getTrackName", device_globals, {"index": 0})
        assert resp["ok"] and resp["result"] == "Master", f"mixer.getTrackName: {resp}"
        print(f"[smoke] mixer.getTrackName(0) = {resp['result']!r}")

        # --- 6. patterns.patternCount ---
        resp = _roundtrip(ipc_dir, 6, "patterns.patternCount", device_globals)
        assert resp["ok"] and resp["result"] == 1, f"patternCount: {resp}"
        print(f"[smoke] patterns.patternCount = {resp['result']}")

        # --- 7. general.getProjectTitle ---
        resp = _roundtrip(ipc_dir, 7, "general.getProjectTitle", device_globals)
        assert resp["ok"] and resp["result"] == "Untitled.flp", f"getProjectTitle: {resp}"
        print(f"[smoke] general.getProjectTitle = {resp['result']!r}")

        # --- 8. write-side: channels.setChannelVolume — verify side effect ---
        before = len([c for c in _mock_calls if c[0] == "channels.setChannelVolume"])
        resp = _roundtrip(
            ipc_dir,
            8,
            "channels.setChannelVolume",
            device_globals,
            {"index": 0, "value": 0.9},
        )
        assert resp["ok"], f"setChannelVolume: {resp}"
        after = len([c for c in _mock_calls if c[0] == "channels.setChannelVolume"])
        assert after == before + 1, "side effect not recorded"
        last_call = [c for c in _mock_calls if c[0] == "channels.setChannelVolume"][-1]
        assert last_call[1] == (0, 0.9), f"args were {last_call[1]}"
        print(f"[smoke] channels.setChannelVolume(0, 0.9) recorded side effect OK")

        # --- 9. composite: mixer.setRouteTo + afterRoutingChanged ---
        before_set = len([c for c in _mock_calls if c[0] == "mixer.setRouteTo"])
        before_after = len([c for c in _mock_calls if c[0] == "mixer.afterRoutingChanged"])
        resp = _roundtrip(
            ipc_dir,
            9,
            "mixer.setRouteTo",
            device_globals,
            {"source": 1, "dest": 2, "value": 1},
        )
        assert resp["ok"], f"setRouteTo: {resp}"
        after_set = len([c for c in _mock_calls if c[0] == "mixer.setRouteTo"])
        assert after_set == before_set + 1, "setRouteTo not recorded"
        resp = _roundtrip(ipc_dir, 10, "mixer.afterRoutingChanged", device_globals)
        assert resp["ok"], f"afterRoutingChanged: {resp}"
        after_after = len([c for c in _mock_calls if c[0] == "mixer.afterRoutingChanged"])
        assert after_after == before_after + 1, "afterRoutingChanged not recorded"
        print(f"[smoke] mixer setRouteTo + afterRoutingChanged composite OK")

        # --- 10. bridge-internal: state.setSubscribed + state.drainChanges ---
        resp = _roundtrip(
            ipc_dir, 11, "state.setSubscribed", device_globals, {"enabled": True}
        )
        assert resp["ok"] and resp["result"]["subscribed"] is True, f"setSubscribed: {resp}"
        print(f"[smoke] state.setSubscribed(True) -> {resp['result']}")

        # Trigger OnDirty events manually
        if "OnDirtyChannel" in device_globals:
            device_globals["OnDirtyChannel"](0, 0)  # CE_New
            device_globals["OnDirtyMixerTrack"](-1)

        resp = _roundtrip(ipc_dir, 12, "state.drainChanges", device_globals)
        assert resp["ok"], f"drainChanges: {resp}"
        events = resp["result"]
        assert isinstance(events, list) and len(events) >= 2, f"drainChanges events: {events}"
        kinds = {e["kind"] for e in events}
        assert "channel" in kinds and "mixer_track" in kinds, f"missing kinds: {kinds}"
        print(f"[smoke] state.drainChanges -> {len(events)} events: {kinds}")

        # --- 11. bridge composite: general.saveProject -> transport.globalTransport(FPT_Save,...) ---
        before_gt = len([c for c in _mock_calls if c[0] == "transport.globalTransport"])
        resp = _roundtrip(ipc_dir, 13, "general.saveProject", device_globals)
        assert resp["ok"], f"saveProject: {resp}"
        after_gt = len([c for c in _mock_calls if c[0] == "transport.globalTransport"])
        assert after_gt == before_gt + 1, "saveProject did not translate to globalTransport"
        last_call = [c for c in _mock_calls if c[0] == "transport.globalTransport"][-1]
        assert 92 in last_call[1], f"FPT_Save not in args: {last_call[1]}"
        print(f"[smoke] general.saveProject -> globalTransport({last_call[1]}) OK")

        # --- 11b. bridge composites: transport.toggleMetronome + transport.tapTempo ---
        before_gt = len([c for c in _mock_calls if c[0] == "transport.globalTransport"])
        resp = _roundtrip(ipc_dir, 14, "transport.toggleMetronome", device_globals)
        assert resp["ok"], f"toggleMetronome: {resp}"
        after_gt = len([c for c in _mock_calls if c[0] == "transport.globalTransport"])
        assert after_gt == before_gt + 1, "toggleMetronome did not translate"
        last_call = [c for c in _mock_calls if c[0] == "transport.globalTransport"][-1]
        assert 110 in last_call[1], f"FPT_Metronome not in args: {last_call[1]}"

        before_gt = after_gt
        resp = _roundtrip(ipc_dir, 15, "transport.tapTempo", device_globals)
        assert resp["ok"], f"tapTempo: {resp}"
        after_gt = len([c for c in _mock_calls if c[0] == "transport.globalTransport"])
        assert after_gt == before_gt + 1, "tapTempo did not translate"
        last_call = [c for c in _mock_calls if c[0] == "transport.globalTransport"][-1]
        assert 106 in last_call[1], f"FPT_TapTempo not in args: {last_call[1]}"
        print(f"[smoke] toggleMetronome + tapTempo composites OK")

        # --- 12. error path: unknown method ---
        resp = _roundtrip(ipc_dir, 99, "channels.thisDoesNotExist", device_globals)
        assert not resp["ok"], f"unknown method should fail: {resp}"
        print(f"[smoke] unknown method correctly errors: {resp.get('error')[:60]}...")

        # --- 13. FULL DISPATCH COVERAGE — every entry round-trips ----------
        print(f"[smoke] exercising all {len(DISPATCH_PROBES)} DISPATCH entries...")
        ok_reads, ok_writes, ok_internal, probe_failures = _run_dispatch_coverage(
            ipc_dir, device_globals
        )
        for f in probe_failures:
            failures.append(f"dispatch: {f}")
        covered = ok_reads + ok_writes + ok_internal
        pct = (covered * 100) // dispatch_count if dispatch_count else 0
        print(
            f"[smoke] dispatch coverage: {covered} / {dispatch_count} entries exercised ({pct}%)"
        )
        print(f"[smoke] read-side: {ok_reads} OK")
        print(f"[smoke] write-side: {ok_writes} OK (side effects recorded)")
        print(f"[smoke] bridge-internal: {ok_internal} OK")

        # Hard rule: every DISPATCH entry must be probed.
        if len(DISPATCH_PROBES) != dispatch_count:
            failures.append(
                f"probe table has {len(DISPATCH_PROBES)} entries but DISPATCH has "
                f"{dispatch_count} — extend DISPATCH_PROBES to match"
            )
        if covered != dispatch_count:
            failures.append(
                f"only {covered} of {dispatch_count} DISPATCH entries round-tripped successfully"
            )

    except AssertionError as e:
        failures.append(str(e))
    except Exception as e:
        import traceback as _tb

        failures.append(f"unexpected: {type(e).__name__}: {e}\n{_tb.format_exc()}")
    finally:
        try:
            device_globals["OnDeInit"]()
        except Exception as e:
            failures.append(f"OnDeInit raised: {e}")
        # Best-effort tmp cleanup
        try:
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    if failures:
        print(f"\n[smoke] FAILED ({len(failures)} failures):")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"\n[smoke] ALL OK — {len([c for c in _mock_calls])} mock FL calls recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
