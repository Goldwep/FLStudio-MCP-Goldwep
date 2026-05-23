# bridge/

Holds the in-FL Studio Python device script that exposes FL's scripting API to the MCP server over a localhost TCP socket.

## Install location (Windows)

When implemented, the script is copied to:

```
%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\device_FLStudioMCP.py
```

Then in FL Studio: **Options → MIDI settings → Controller type → FLStudio-MCP**, assigned to any input/output port (the script doesn't actually use MIDI traffic — it just needs to be loaded as a "controller" so FL runs its `OnInit` / event loop).

## Runtime

FL Studio 2024 ships its own CPython 3.12 (`C:\Program Files\Image-Line\FL Studio 2024\Shared\Python\python.exe`). The bridge script runs inside that interpreter and has access to FL's scripting modules:

- `channels` — Channel Rack (instruments, samples, step sequencer)
- `mixer` — Mixer tracks, sends, plugins
- `patterns` — Pattern data, notes
- `transport` — Play/stop/record, tempo, position
- `playlist` — Playlist clips and tracks
- `arrangement` — Arrangements, timeline markers
- `plugins` — Plugin parameters, presets
- `ui` — Window focus, navigation
- `general` — Project save/load, undo
- `device` — MIDI I/O (incidental — bridge uses sockets, not MIDI)

## Protocol

To be defined in the first planning phase. Provisional: line-delimited JSON-RPC 2.0 over a single persistent TCP connection to `127.0.0.1:9876` (configurable).

## Status

Empty until planning lands. This README is a placeholder so the folder is tracked.
