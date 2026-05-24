# Install — Bridging FL Studio to the MCP server

> **Status:** v0.9.2-file-ipc. After completing this guide, ~96 of the 110 MCP tools start working (real-time FL Studio control via the file-IPC bridge). The L7 PyFLP tools (8) work without FL; the L6 piano-roll deploy tools (6) work without the bridge.

## Architecture

```
┌──────────────┐  stdio   ┌──────────────────┐  file IPC  ┌──────────────────────────┐
│ Claude /     │ ───────▶ │ flstudio-mcp     │ ─────────▶ │ device_FLStudioMCP.py    │
│ MCP client   │ ◀─────── │ (this repo)      │ ◀───────── │ (single-threaded IPC     │
└──────────────┘          └──────────────────┘            │  polled from OnIdle)     │
                                                          │  via ipc/req_<id>.json + │
                                                          │      resp_<id>.json      │
                                                          └──────────────────────────┘
```

Bridge transport is a **file-based IPC channel** under FL Studio's settings folder. Node writes `req_<id>.json`; FL reads + dispatches from `OnIdle` + writes `resp_<id>.json`; Node polls + reads + unlinks the response.

Why file IPC and not a TCP socket? The 2026-05-24 live integration probe found that `socket.socket()` in FL's embedded Python 3.12.1 returns `SystemError: NULL without setting an exception` for every socket type (TCP, UDP, low-level `_socket`). Sockets are unusable in the sub-interpreter; file IPC is the only transport that actually works against this FL build. See [PROBE-REPORT.md §"Update: socket creation also blocked"](./PROBE-REPORT.md#update-socket-creation-also-blocked-2026-05-24) for the empirical data.

`os.mkdir` / `pathlib.mkdir` / `os.makedirs` are **also broken** in FL's embedded Python — same NULL-without-exception failure, even with `exist_ok=True` against an existing directory. The IPC folder therefore must be **pre-created externally** (the installer does this; the device script verifies presence on `OnInit` and logs a clear error if missing).

## Prerequisites

- **FL Studio 2024** (Producer Edition or higher). Verified on v24.2.2 build 4597.
- **Node.js 20+** for the MCP server.
- **A MIDI input port FL Studio can see.** Most users plug in any USB MIDI controller. If you don't have one, install [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) (free, ~3 min) — create one virtual port; FL will detect it as an input.
- **(Optional, for L7 PyFLP tools)** Python 3.10+ with `pyflp` installed. See [`L7-PYFLP-SETUP.md`](./L7-PYFLP-SETUP.md).

## One-time setup

### 1. Install the FL Studio device script + pre-create the IPC folder

Copy `bridge/device_FLStudioMCP.py` from this repo to:

```
%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\device_FLStudioMCP.py
```

Then **create the IPC folder** (this is the load-bearing step — FL's embedded Python cannot create directories, so the device script will refuse to start if it's missing):

```powershell
mkdir "$env:USERPROFILE\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\ipc"
```

(The folder name `FLStudio-MCP` matters — FL Studio uses it as the device label in the controller-type dropdown.)

If you cloned this repo and ran the setup once, both may already be deployed.

### 2. Assign the bridge to a MIDI input port in FL Studio

1. Open FL Studio.
2. **F10** (or Options → MIDI Settings).
3. In the **Input** list at the top, click any input device row to select it. Pick one you're NOT using as a real controller (e.g. the loopMIDI port, or an unused MIDI input).
4. Below the Input list, find the **Controller type** dropdown. Set it to **"FLStudio MCP Bridge"**.
5. Click the **Enable** button below it (turns from grey to orange).
6. Close the MIDI Settings dialog.
7. Open Script Output (`Ctrl+F12` or View → Script output).
8. You should see a new tab labeled **"FLStudio MCP Bridge"** next to "Interpreter".
9. The tab should show: `[mcp-bridge] MCP file-IPC bridge ready at ...\FLStudio-MCP\ipc`. Confirms the FL side is up.
10. A heartbeat file `bridge_alive.txt` will appear inside the `ipc/` folder.

If the tab doesn't appear, see [Troubleshooting](#troubleshooting) below. If you see `IPC directory does not exist`, you skipped the `mkdir` step above.

### 3. Run the MCP server

```powershell
cd C:\Users\<you>\Documents\GitHub\FLStudio-MCP-Goldwep
npm install     # one-time
npm run build
node dist/index.js
```

The MCP server connects to FL's bridge on the first tool call (lazy connect — just checks that the IPC folder exists).

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
    "mode": "file",
    "ipcDir": "C:\\Users\\<you>\\Documents\\Image-Line\\FL Studio\\Settings\\Hardware\\FLStudio-MCP\\ipc",
    "requestTimeoutMs": 1500
  }
}
```

- `mode: "file"` — production transport (default). The only mode that actually works against FL today.
- `mode: "stub"` — offline mode; only `ping` + L6 `.pyscript` deploy + L7 PyFLP tools work.
- `mode: "socket"` — **dormant**; code is kept for the day the FL/Python embedded-socket bug is fixed, but `socket()` returns NULL in FL's Python so this mode cannot connect today.
- `ipcDir` — override the default IPC folder path. Defaults to `%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\ipc` (matches the device script's expectation).
- `requestTimeoutMs: 1500` — set higher if your machine has slow `OnIdle` cadence (L0 probe data shows p99 ~86ms on FL 2024; 1500ms = ~17× p99 plus margin for the additional poll-interval latency of file IPC vs the socket transport).

## Troubleshooting

### `BRIDGE_CONNECT_FAILED` on every non-`ping` tool

The Node side can't find the IPC folder. Check:

1. The folder exists: `dir "$env:USERPROFILE\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\ipc"` should not error.
2. FL Studio is running.
3. The "FLStudio MCP Bridge" tab is visible in FL's Script Output window.
4. The tab shows `[mcp-bridge] MCP file-IPC bridge ready at ...` (no Python traceback).

### `IPC directory does not exist` in FL's Script Output

You skipped step 1's `mkdir`. Create the folder manually (mkdir is broken inside FL's embedded Python, so the device script cannot fix this for you):

```powershell
mkdir "$env:USERPROFILE\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\ipc"
```

Then click **Reload script** in the MIDI Settings dialog or simply restart FL.

### Tab labeled "FLStudio MCP Bridge" doesn't appear in Script Output

- Refresh device list in MIDI Settings (button at the bottom).
- Confirm the file is at the exact path: `%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\device_FLStudioMCP.py`.
- Restart FL Studio — sometimes a fresh `Settings\Hardware\` scan is required.

### `SystemError: ... returned NULL without setting an exception`

You're running an old version of the device script that tries to call `socket.socket()` or `os.mkdir`. The current `device_FLStudioMCP.py` is file-IPC and avoids both. Re-deploy from this repo's `bridge/` folder.

### Bridge logs

The device script writes to `bridge.log` next to itself (direct `open(path, "a")` — the rotating-file handler in Python's `logging` module calls `os.makedirs` internally, which is broken in FL's embedded Python):

```
%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\bridge.log
```

Useful for debugging — shows every OnInit, every dispatched method, and any error responses.

### `[UNVERIFIED]` tools throw `BRIDGE_DISPATCH_ERROR`

Per the audit (`docs/AUDIT-CYCLE.md`), 10 tools call FL APIs that are documented but have zero vendor-script precedent. If `transport_set_tempo`, `mixer_set_send_level`, `mixer_set_eq_gain`, `mixer_set_eq_freq`, `mixer_link_channel_to_track`, `transport_get_song_length`, `general_get_rec_ppb`, `arrangement_current_time`, or `ui_get_focused_form_id` throw with `AttributeError: module 'X' has no attribute 'Y'`, the API doesn't exist in your FL build. Use the documented alternative (e.g. `mixer_link_track_to_channel` instead of `mixer_link_channel_to_track`).

## What's next (post-v0.9.2)

- **Probe-2** — confirm `processRECEvent(REC_Chan_NoteOn, ...)` actually adds a note to the pattern (L0 confirmed the call is accepted; landing is the open question). If yes → L6 collapses into REC-based live composition.
- **Tag v1.0.0** — once bridge round-trip is verified against FL Studio and `[UNVERIFIED]` flags are resolved.
- See [`AUDIT-CYCLE.md`](./AUDIT-CYCLE.md) and [`DOMAIN-MAP.md`](./DOMAIN-MAP.md) for the full roadmap.
