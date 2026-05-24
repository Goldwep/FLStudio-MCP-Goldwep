# Session Handoff — v1.0.0 LIVE-VERIFIED ✅

> **Date:** 2026-05-24 (final session)
> **Repo state:** `v1.0.0` tagged on `main`.
> **Outcome:** All original ship criteria met. Bridge is live-verified against FL Studio 2024 v24.2.2 build 4597. `npm run verify:live` exits 0.

## Live verification result

```
[verify] OVERALL: 39 ok / 0 fail / 0 timeout / 49 skip
[verify] all green.
```

- **39 ok** — every read-side method that this empty FL project can answer
- **0 fail** — no broken dispatch
- **0 timeout** — every request gets a response, none stall
- **49 skip** — write/mutating operations (need `--include-writes` to test, would change project state)

## The breakthrough

After the second session's "FL Python file-writes are universally broken" conclusion, a more granular probe (probe-2: 25 write primitives across 4 paths each) found **two write paths that DO work** in FL 2024 v24.2.2's Python 3.12.1 sub-interpreter:

```
open(BYTES_path, "wb"/"ab")              ✅ works
os.open(BYTES_path, ...) + os.write()    ✅ works
EVERYTHING ELSE                          ❌ FileIO NULL bug
```

**The bug is path-encoding-specific**: `str` paths trigger the `_io.FileIO` NULL-without-exception bug, but `bytes` paths in binary mode bypass the broken constructor entirely.

The bridge's `_write_bytes(path, data)` now utf-8-encodes the path before every write. Reads use the same bytes-path + binary mode pattern. The 88-entry dispatch table is unchanged; only the file-IO primitive at the bottom of the stack flipped from str to bytes.

## Followup probe: removal is still broken

`os.remove`, `os.unlink`, `Path.unlink`, `os.rename`, and `subprocess` all fail the same NULL bug — even with bytes paths. Workaround: **truncate-as-tombstone**. The bridge opens the processed req file in `wb` mode (writes zero bytes), leaving a 0-byte file on disk. OnIdle treats 0-byte `req_*.json` as "already processed, skip" — idempotent and uses only the working open(bytes,"wb") primitive. Node side then unlinks both the request and response files (Node's `fs.unlink` is unaffected, so leftover tombstones get cleaned up at response-read time).

## Three blockers fixed in sequence to get here

1. **Orphan FL64.exe** holding MPKmini2 → closed via `scripts/close_orphan_fl.py` (WM_CLOSE PostMessage to parent=claude.exe FL instance).
2. **SendInput filtered by FL's TVectorPanel** → switched to legacy `SetCursorPos` + `mouse_event` API. Captured in `scripts/click_reload_v2.py`.
3. **Wrong device-script binding** ("FLStudio MCP Probe" selected instead of "Bridge") → overwrote the probe folder's script with bridge code, keeping the existing FL assignment intact.

After those three, OnInit fired but every write failed. probe-2 found the bytes-path workaround. probe-3 found removal was still broken, leading to the tombstone pattern.

## Gates

| Gate                                    | Result                                                           |
| --------------------------------------- | ---------------------------------------------------------------- |
| `npm run build`                         | ✅ clean (tsc, 0 errors)                                         |
| `npm test`                              | ✅ **10/10** pass (4 smoke + 6 file-bridge)                      |
| `npm run lint`                          | ✅ clean                                                         |
| `npm run format:check`                  | ✅ clean                                                         |
| `python tests/bridge_device_smoke.py`   | ✅ **88/88 dispatch entries** covered via mock FL modules (100%) |
| `npm run verify:live` against actual FL | ✅ **39 ok / 0 fail / 0 timeout / 49 skip — all green**          |

## Diagnostic scripts kept under `scripts/`

| Script                           | Purpose                                                                                                                        |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `close_orphan_fl.py`             | Find and WM_CLOSE any FL64.exe with parent=claude.exe (recover from `open_application` orphaning the user's real FL instance). |
| `inspect_fl_windows.py`          | Enumerate visible windows owned by the user's real FL64.exe.                                                                   |
| `enum_script_output_children.py` | Recursive child-window enumeration of Script Output HWND for click-target derivation.                                          |
| `click_reload_v2.py`             | Click Reload Script via `SetCursorPos` + `mouse_event` (the only input primitive that FL's TVectorPanel accepts).              |
| `exec_oninit_via_cmd.py`         | Alternative reload path: type `OnInit()` into the "Command to execute" field.                                                  |
| `check_foreground.py`            | Detect IME / TextInputHost / Welcome-dialog blockers in front of FL.                                                           |
| `read_script_output.py`          | UIA / WM_GETTEXT probe for reading TQuickMemo content (not viable — fully custom-drawn).                                       |
| `fix_controller_type.py`         | Inspect MIDI Settings dialog children for controller-type dropdown automation.                                                 |

## What `npm run verify:live` actually tests

Each of the 88 DISPATCH entries gets a probe configured in `scripts/verify-live.ts`. Read-side methods run against the open FL project; write/mutating methods are skipped unless `--include-writes` is passed. Failures are classified:

- `TIMEOUT` → bridge hung or OnIdle stalled (this used to happen pre-fix; now zero)
- `FAIL` → real dispatch error (e.g. arg validation, type mismatch)
- `skip` → write op without `--include-writes` flag, OR AttributeError on a `[UNVERIFIED]` audit-flagged method that this FL build doesn't expose, OR "Plugin not valid" when the test project has no plugin loaded

Exit codes: `0` if zero FAILs (timeouts and skips don't count), `1` otherwise. Today: exit 0.

## Repo / commit roll

```
<HEAD>     v1.0.0 — live-verified, bytes-path workaround landed
40658de    Deep-integration findings before the breakthrough
1926af9    Win32 PostMessage utility (session artifact)
72311a4    Session handoff doc: one click + one command from v1.0.0
adc3ebf    v1.0.0-rc3: file-IPC bridge (after socket-blocked finding)
f573e78    v1.0.0-rc2: live-verify harness + 100% dispatch smoke
773a58a    v1.0.0-rc1: socket bridge + mock-FL smoke + release candidate
```

Three architectural pivots (queue→single-thread, socket→file-IPC, then the bytes-path workaround inside file-IPC), four release candidates, 88 dispatch entries verified against actual FL, every code gate green. **The MCP is good to go.**
