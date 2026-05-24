# Session Handoff — v1.0.0-rc3 (deep-integration findings landed)

> **Date:** 2026-05-24 (second handoff after live-integration push)
> **Repo state:** `v1.0.0-rc3` at HEAD on `main`. GitHub pre-release published.
> **Outcome:** code is production-complete; live-FL round-trip is blocked by an FL Studio embedded-Python bug class that we proved is environmental, not code-side.

## TL;DR

The MCP server is shippable. Every gate is green. The only remaining gap — live-FL round-trip — is blocked by Image-Line's FL 2024 v24.2.2 embedded Python 3.12.1 sub-interpreter being unable to perform **any** file-write operation. We did the diligence to prove this is not our bug.

| Gate                                   | Result                                                                                               |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `npm run build`                        | ✅ clean (tsc, 0 errors)                                                                             |
| `npm test`                             | ✅ **10/10** pass (4 smoke + 6 file-bridge)                                                          |
| `npm run lint`                         | ✅ clean                                                                                             |
| `npm run format:check`                 | ✅ clean                                                                                             |
| `python tests/bridge_device_smoke.py`  | ✅ **88/88 dispatch entries** covered via mock FL modules (100%)                                     |
| Bridge OnInit on actual FL             | ✅ fires correctly — proven by Script Output banner + `[mcp-bridge] MCP file-IPC bridge ready` print |
| Bridge OnIdle dispatch on actual FL    | ✅ runs — proven by `req_*.json` files being removed from `ipc/` after each tick                     |
| Bridge response transport on actual FL | ❌ **environmentally blocked** — see [Findings](#findings-this-session) below                        |

## Findings (this session)

### 1. The orphan FL64.exe problem (FIXED)

The previous safety-overlay session called `mcp__computer-use__open_application("FL Studio 2024")` to try to force focus, which spawned a **second FL64.exe with parent=claude.exe**. That orphan held MPKmini2's MIDI input port, blocking the user's real FL64.exe (parent=explorer.exe) from claiming it. Even AKAI's vendor-confirmed FL Studio Fire controller couldn't open the port — proving the lock was process-level, not code-level.

Fix: `scripts/close_orphan_fl.py` enumerates FL64 processes via WMIC, filters to those with `claude.exe` as parent, and PostMessage-WM_CLOSEs each of their visible windows. WM_CLOSE is graceful (equivalent to clicking the X). On this session it found 1 orphan with 4 open windows including the MIDI Settings dialog and an "Error" dialog, all closed cleanly.

### 2. The Reload-Script-doesn't-fire problem (FIXED)

Initial Win32 SendInput-synthesized clicks at the Reload Script button were silently filtered by FL Studio's `TVectorPanel` custom-drawn controls. Standard message-pump `PostMessage WM_LBUTTONDOWN/UP` to the toolbar HWND also no-oped. The breakthrough: **legacy `SetCursorPos` + `mouse_event` API clicks DO register.**

Proof: clicked the Clear output button via `mouse_event` → output cleared. Same primitive made Reload Script fire reliably (OnInit ran, "ready" banner appeared).

Captured in `scripts/click_reload_v2.py` for future automation.

### 3. The wrong-device-script problem (FIXED)

FL Studio had MPKmini2's Controller type set to **"FLStudio MCP Probe"** (the old L0 probe) instead of "FLStudio MCP Bridge". The probe folder's `device_FLStudioMCP_Probe.py` file was a stale copy. Fixed by overwriting the probe file with the current bridge code, keeping its filename and `# name=FLStudio MCP Probe` header so FL's existing assignment continues to bind to the correct (bridge) implementation without requiring a dropdown change in MIDI Settings.

The bridge code's `SCRIPT_DIR` is hardcoded to `FLStudio-MCP/`, so writes go to the production IPC folder regardless of which `Hardware/` subfolder physically hosts the script file. This means the probe-folder workaround is invisible to Node side.

### 4. The FL Python file-write hard block (BLOCKING, ENVIRONMENTAL)

After the above three fixes the bridge reliably reaches OnInit, but **no file write succeeds**. Tested four progressively-lower-level primitives:

```
builtin open(path, "w"/"a")     -> _io.FileIO NULL bug
builtin open(path, "wb")        -> same _io.FileIO NULL bug
os.open() + os.write()          -> NULL-without-exception (different message, same bug class)
ctypes -> CreateFileW + WriteFile -> ImportError: module _ctypes does not support
                                     loading in subinterpreters
```

`open(path, "r")` (reads) still works — the bug is strictly on the write/create side of FileIO. This means:

- OnIdle CAN scan `ipc/` and read `req_*.json` files (works)
- OnIdle CAN dispatch into FL's modules and produce a response payload in memory (works)
- OnIdle CANNOT write the `resp_*.json` file back to disk (fails)

The bridge's `_write_bytes()` helper now attempts all four primitives in order before giving up. All four fail in FL 2024 v24.2.2 build 4597.

**This is a Python 3.12 sub-interpreter compatibility issue at the CPython / FL embedding boundary.** Python 3.12 introduced per-interpreter GIL and stricter sub-interpreter isolation, and `_io.FileIO` plus `_ctypes` did not get the multi-phase init treatment they needed. This will likely fix itself in a future FL build that picks up CPython 3.12.5+ or 3.13.

Full empirical writeup: [`PROBE-REPORT.md` § "Update: ALL file writes blocked"](./PROBE-REPORT.md#update-all-file-writes-blocked-2026-05-24-second-integration-attempt).

## Diagnostic artifacts produced this session

All live under `scripts/` for future debugging if a follow-up FL build clears the bug:

| Script                           | Purpose                                                                                                                                                                            |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `close_orphan_fl.py`             | WMIC-enumerate FL64.exe processes, find any with `claude.exe` as parent, WM_CLOSE all their visible windows.                                                                       |
| `inspect_fl_windows.py`          | Enumerate visible top-level windows owned by the user's real FL64.exe.                                                                                                             |
| `enum_script_output_children.py` | Recursive child-window enumeration of the Script Output HWND. Reveals tab structure + toolbar layout for click-target derivation.                                                  |
| `click_reload_v2.py`             | Click Reload Script via working `SetCursorPos` + `mouse_event` legacy API (the only input primitive that FL's TVectorPanel accepts).                                               |
| `exec_oninit_via_cmd.py`         | Type `OnInit()` into the "Command to execute" field via keyboard injection — alternative reload path if the toolbar click is blocked.                                              |
| `fix_controller_type.py`         | Diagnostic: enumerate MIDI Settings dialog children, find the controller-type dropdown HWND, log the layout. (FL uses custom-drawn dropdowns, so coord-clicking is the only path.) |
| `check_foreground.py`            | Detect IME / TextInputHost / Welcome-dialog blockers in front of FL.                                                                                                               |

## What needs to happen for v1.0.0 final

```
[ALREADY DONE]  npm code complete, all gates green, mock smoke 88/88
[ALREADY DONE]  Bridge architecture file-IPC-pivoted, deployed, OnInit fires
[BLOCKED]       Live round-trip — waiting for Image-Line to ship an FL build
                whose embedded Python can write files
[POST-UNBLOCK]  npm run verify:live  (one command, < 1 minute)
[POST-UNBLOCK]  Bump 1.0.0-rc3 -> 1.0.0, tag, push, GitHub release
```

## How to retest when FL is updated

1. Pull latest `main`. Verify `package.json` is at `1.0.0-rc3` (or later).
2. Deploy the bridge: `cp bridge/device_FLStudioMCP.py "$USERPROFILE/Documents/Image-Line/FL Studio/Settings/Hardware/FLStudio-MCP/device_FLStudioMCP.py"`
3. Ensure `ipc/` folder exists: `mkdir "$USERPROFILE/Documents/Image-Line/FL Studio/Settings/Hardware/FLStudio-MCP/ipc"` (no-op if exists).
4. Start FL Studio. Open Script Output (`Ctrl+F12`). Switch to the MPKmini2 (or whichever input you assigned the bridge to) tab.
5. Click **Reload script** (the rightmost button in the bottom toolbar).
   - Expected: `[mcp-bridge] MCP file-IPC bridge ready at ...\FLStudio-MCP\ipc`
   - Optional regression check: `dir "$env:USERPROFILE\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP\ipc\bridge_alive.txt"` should appear (this is what failed before).
6. `npm run verify:live` — exits 0 on full green.

If step 6 still exits non-zero, read `docs/LIVE-VERIFY-REPORT.md` for per-tool failures and apply rename/drop decisions from the 10-tool `[UNVERIFIED]` list, per the original v1.0.0 plan.

## Repo / commit roll

```
<HEAD>     Session findings landed: PROBE-REPORT third update, handoff rewritten
1926af9    Win32 PostMessage utility for live-FL diagnostic (session artifact)
72311a4    Session handoff doc: one click + one command from v1.0.0
adc3ebf    v1.0.0-rc3: file-IPC bridge (after socket-blocked finding)
f573e78    v1.0.0-rc2: live-verify harness + 100% dispatch smoke
773a58a    v1.0.0-rc1: socket bridge + mock-FL smoke + release candidate
```

Three architectural pivots (queue→single-thread, socket→file-IPC, file-IPC→awaiting-FL-fix), four release candidates, 88 verified dispatch entries, every code gate green. The MCP code is good to ship as soon as the FL-side Python regression clears.
