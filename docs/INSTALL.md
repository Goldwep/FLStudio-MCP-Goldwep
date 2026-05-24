# Install — Bridging FL Studio to the MCP server

> **Status:** v0.9.1-pre-bridge. After completing this guide, ~96 of the 110 MCP tools start working (real-time FL Studio control via the socket bridge). The L7 PyFLP tools (8) work without FL; the L6 piano-roll deploy tools (6) work without the bridge.

## Architecture

```
┌──────────────┐  stdio   ┌──────────────────┐    TCP    ┌─────────────────────────┐
│ Claude /     │ ───────▶ │ flstudio-mcp     │ ────────▶ │ device_FLStudioMCP.py   │
│ MCP client   │ ◀─────── │ (this repo)      │ ◀──────── │ (single-threaded socket │
└──────────────┘          └──────────────────┘           │  polled from OnIdle,    │
                                                         │  127.0.0.1:9876)        │
                                                         └─────────────────────────┘
```

Bridge transport is a single-threaded non-blocking TCP socket polled from FL's `OnIdle` callback. Architecture is locked by the L0 probe data in [`PROBE-REPORT.md`](./PROBE-REPORT.md) — see §3.

## Prerequisites

- **FL Studio 2024** (Producer Edition or higher). Verified on v24.2.2 build 4597.
- **Node.js 20+** for the MCP server.
- **A MIDI input port FL Studio can see.** Most users plug in any USB MIDI controller. If you don't have one, install [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) (free, ~3 min) — create one virtual port; FL will detect it as an input.
- **(Optional, for L7 PyFLP tools)** Python 3.10+ with `pyflp` installed. See [`L7-PYFLP-SETUP.md`](./L7-PYFLP-SETUP.md).

## One-time setup

### 1. Install the FL Studio device script

Copy `bridge/device_FLStudioMCP.py` from this repo to:

```
%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\device_FLStudioMCP.py
```

(The folder name `FLStudio-MCP` matters — FL Studio uses it as the device label in the controller-type dropdown.)

If you cloned this repo and ran the setup once, this file may already be deployed.

### 2. Assign the bridge to a MIDI input port in FL Studio

1. Open FL Studio.
2. **F10** (or Options → MIDI Settings).
3. In the **Input** list at the top, click any input device row to select it. Pick one you're NOT using as a real controller (e.g. the loopMIDI port, or an unused MIDI input).
4. Below the Input list, find the **Controller type** dropdown. Set it to **"FLStudio MCP Bridge"**.
5. Click the **Enable** button below it (turns from grey to orange).
6. Close the MIDI Settings dialog.
7. Open Script Output (`Ctrl+F12` or View → Script output).
8. You should see a new tab labeled **"FLStudio MCP Bridge"** next to "Interpreter".
9. The tab should show: `[mcp-bridge] listening on 127.0.0.1:9876`. Confirms the FL side is up.

If the tab doesn't appear, see [Troubleshooting](#troubleshooting) below.

### 3. Run the MCP server

```powershell
cd C:\Users\<you>\Documents\GitHub\FLStudio-MCP-Goldwep
npm install     # one-time
npm run build
node dist/index.js
```

The MCP server connects to FL's bridge on the first tool call (lazy connect).

### 4. Wire to Claude

**Claude Code (Windows):**

```powershell
claude mcp add --scope user flstudio-mcp -- cmd /c node "C:\Users\<you>\Documents\GitHub\FLStudio-MCP-Goldwep\dist\index.js"
```

**Claude Desktop:** add to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "flstudio-mcp": {
      "command": "node",
      "args": ["C:\\Users\\<you>\\Documents\\GitHub\\FLStudio-MCP-Goldwep\\dist\\index.js"]
    }
  }
}
```

Restart Claude. Verify with `/mcp`.

## Verify it works

In Claude, ask:

- _"Run the `ping` tool"_ → should return `{ pong: true, ts: <ms> }`
- _"How many channels are in my FL project?"_ → calls `channels_count`; should return an integer
- _"What's the master mixer track named?"_ → calls `mixer_get_track_name` with index 0; should return "Master" or your custom name

If `ping` works but `channels_count` returns `BRIDGE_CONNECT_FAILED`, the FL side isn't listening — check the Script Output tab (step 2 above).

## Config overrides

Put a `flstudio-mcp.config.json` next to where you run the server:

```json
{
  "bridge": {
    "mode": "socket",
    "host": "127.0.0.1",
    "port": 9876,
    "connectTimeoutMs": 3000,
    "requestTimeoutMs": 750
  }
}
```

- `mode: "socket"` — production transport (default).
- `mode: "stub"` — offline mode; only `ping` + L6 `.pyscript` deploy + L7 PyFLP tools work.
- `requestTimeoutMs: 750` — set higher if your machine has slow `OnIdle` cadence (L0 probe data shows p99 ~86ms on FL 2024; 750ms = 10× p99 round-down).

## Troubleshooting

### `BRIDGE_CONNECT_FAILED` on every non-`ping` tool

The Node side can't reach the FL device script. Check:

1. FL Studio is running.
2. The "FLStudio MCP Bridge" tab is visible in FL's Script Output window.
3. The tab shows `[mcp-bridge] listening on 127.0.0.1:9876` (no Python traceback).
4. Port 9876 isn't already used by another process: `netstat -ano | findstr :9876`.

### Tab labeled "FLStudio MCP Bridge" doesn't appear in Script Output

- Refresh device list in MIDI Settings (button at the bottom).
- Confirm the file is at the exact path: `%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\device_FLStudioMCP.py`.
- Restart FL Studio — sometimes a fresh `Settings\Hardware\` scan is required.

### `RuntimeError: daemon threads are disabled` in Script Output

You're running an old version of the device script that uses threading. The current `device_FLStudioMCP.py` is single-threaded. Re-deploy from this repo's `bridge/` folder.

### Bridge logs

The device script writes to `bridge.log` in the same folder as the script (uses `RotatingFileHandler`):

```
%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\bridge.log
```

Useful for debugging — shows every accepted connection, every dispatched method, and any error responses.

### `[UNVERIFIED]` tools throw `BRIDGE_DISPATCH_ERROR`

Per the audit (`docs/AUDIT-CYCLE.md`), 10 tools call FL APIs that are documented but have zero vendor-script precedent. If `transport_set_tempo`, `mixer_set_send_level`, `mixer_set_eq_gain`, `mixer_set_eq_freq`, `mixer_link_channel_to_track`, `transport_get_song_length`, `general_get_rec_ppb`, `arrangement_current_time`, or `ui_get_focused_form_id` throw with `AttributeError: module 'X' has no attribute 'Y'`, the API doesn't exist in your FL build. Use the documented alternative (e.g. `mixer_link_track_to_channel` instead of `mixer_link_channel_to_track`).

## What's next (post-v0.9.1)

- **Probe-2** — confirm `processRECEvent(REC_Chan_NoteOn, ...)` actually adds a note to the pattern (L0 confirmed the call is accepted; landing is the open question). If yes → L6 collapses into REC-based live composition.
- **Tag v1.0.0** — once bridge round-trip is verified against FL Studio and `[UNVERIFIED]` flags are resolved.
- See [`AUDIT-CYCLE.md`](./AUDIT-CYCLE.md) and [`DOMAIN-MAP.md`](./DOMAIN-MAP.md) for the full roadmap.
