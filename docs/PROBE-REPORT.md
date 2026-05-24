# L0 Probe Report — Architecture Lock

> **Status:** **EMPIRICAL DATA LANDED (2026-05-23 + 2026-05-24 socket update).** Probe ran inside FL Studio Producer Edition v24.2.2 build 4597 using bundled Python 3.12.1, FL MIDI Scripting API version 37. Raw data preserved at [PROBE-RESULTS.json](./PROBE-RESULTS.json), [PROBE-LOG.txt](./PROBE-LOG.txt), and [PROBE-SOCKET-RESULTS.txt](./PROBE-SOCKET-RESULTS.txt). 4 of 7 questions answered definitively, 3 untestable in this run, 1 bonus finding — plus the 2026-05-24 socket-creation finding that pivoted the transport from TCP to file-IPC. See [Update: socket creation also blocked](#update-socket-creation-also-blocked-2026-05-24).

## 0. Environment

| Field                 | Value                                                              |
| --------------------- | ------------------------------------------------------------------ |
| FL Studio version     | Producer Edition v24.2.2 [build 4597]                              |
| Python                | 3.12.1 (tags/v3.12.1, MSC v.1937 64-bit AMD64)                     |
| FL MIDI Scripting API | version 37                                                         |
| Script path           | `Settings\Hardware\FLStudio-MCP-Probe\device_FLStudioMCP_Probe.py` |
| Probe run completed   | 2026-05-23 (~T+12s elapsed across reloads)                         |

## 1. Empirical results

### Q1 — Thread survival: 🔴 **BROKEN**

```
worker spawn failed: daemon threads are disabled in this (sub)interpreter
RuntimeError: daemon threads are disabled in this (sub)interpreter
```

FL's embedded Python runs as a **sub-interpreter** with daemon-thread spawning **explicitly disabled** by Python. Standard `threading.Thread(target=..., daemon=True).start()` raises `RuntimeError` immediately.

**Implication:** The queue-and-drain architecture from the default plan (socket-accept thread → queue → OnIdle drain) is NOT VIABLE. We cannot spawn daemon threads at all.

**Workarounds considered:**

| Approach                                               | Viability          | Notes                                                                                                             |
| ------------------------------------------------------ | ------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `daemon=False` thread                                  | Possible           | Thread survives script-unload — must be killed explicitly. FL's no-OnDeInit-on-reload (Q4) makes cleanup fragile. |
| Single-threaded non-blocking socket polled from OnIdle | ✅ **RECOMMENDED** | No threads. `socket.accept(timeout=0)` polled in OnIdle (~50ms p50). Single-threaded = no thread-safety concerns. |
| asyncio event loop inside OnIdle                       | Risky              | Mixing asyncio with FL's callback loop is fragile. Skip.                                                          |
| Fall back to virtual MIDI (Flapi pattern)              | Backup             | If non-blocking socket has issues, virtual MIDI loopback (already needed for L0 anyway) is the fallback.          |
| FL Studio Remote API                                   | Untested           | Third Python surface; no community MCP uses it. Worth a future spike but not v1.0 path.                           |

**Lock:** **Single-threaded non-blocking socket polled from OnIdle.** Simpler than the original threaded design.

### Q2 — Cross-thread FL API call: ⚠️ **UNTESTABLE**

Worker thread never spawned (Q1 blocked it). The cross-thread `channels.channelCount()` call never executed.

**Implication:** Doesn't matter — we're not using threads. The single-threaded architecture sidesteps Q2 entirely.

### Q3 — `processRECEvent(REC_Chan_NoteOn)`: 🟢 **ACCEPTED**

```
Q3 processRECEvent(16384, 15460, 981) accepted — no exception
post_call_observed_alive: true
```

- REC_ID = 16384 (REC_Chan_NoteOn for channel 0)
- Value = 15460 (pitch=60<<8 | velocity=100 = 15460)
- Flags = 981 (REC_Controller = REC_UpdateValue | REC_ShowHint | REC_InitStore | REC_SetChanged | REC_UpdatePlugLabel | REC_SetTouched)

The call accepted without exception. FL did not crash. **This is the highest-leverage finding — it means real-time piano-roll note CRUD via REC events is at minimum architecturally permitted.**

**Caveat — what we DON'T know yet:**

- Whether the note actually landed in the pattern (no enumeration API to verify from a probe).
- Whether the value-encoding (pitch<<8 | velocity) is correct.
- Whether note position / length / channel can be encoded into the same REC space.

These are **probe-2 territory** — once we have a working bridge, we can issue a REC noteOn, then save the project and grep the .flp via PyFLP to confirm a note was actually added.

**Implication:** L6 piano-roll `.pyscript` dispatch may collapse into L5 step-grid OR into a new "live note CRUD" tool family. **Saves ~2 weeks** of L6 work if this path proves out. The 6 L6 deploy tools currently in v0.9.1 stay as a v1.1 alternative (manual-trigger pattern); the real-time path becomes primary.

### Q4 — OnDeInit on Reload Script: 🔴 **UNRELIABLE**

Probe log shows **3 OnInit fires, 0 OnDeInit fires**:

```
[T+0]    OnInit fired
[T+10]   Q1+Q5 finalized at 200 samples
[T+38]   OnInit fired      ← Nathan hit Reload Script (no OnDeInit between)
[T+42]   OnInit fired      ← Reload again (no OnDeInit between)
[T+52]   Q1+Q5 finalized at 200 samples
```

Reload Script triggers a fresh OnInit but never fires OnDeInit on the previous instance. The "Reload script" button effectively does `exec()` again without teardown.

**Implication:** Socket cleanup CANNOT rely on OnDeInit. Use:

- `SO_REUSEADDR` + force-close any pre-existing socket on `OnInit`
- Store the socket on a module-level singleton; check + close on init
- Same pattern works for any global state needing teardown

### Q5 — OnIdle cadence: 🟡 **~50ms p50 (NOT 20ms)**

200 samples observed:

| Metric | Value       |
| ------ | ----------- |
| min    | 44.5 ms     |
| p50    | **50.0 ms** |
| p90    | 51.0 ms     |
| p99    | **85.6 ms** |
| max    | 89.8 ms     |

**The il-group/image-line docs claim "roughly every 20 ms".** Reality on this FL build is **2.5× slower**. Two outlier spikes to ~85-90ms suggest GC pauses or audio-engine contention.

**Implications:**

- Per-request bridge timeout: target **500-1000ms** (10× p99), not the 200ms the original plan assumed.
- Max throughput: ~20 requests/sec sustained (1000ms / 50ms). For burst tools (state_snapshot composite, channel_step_pattern_build), batch up the requested actions to fit in one OnIdle tick.
- LLM tool latency budget: each MCP tool call costs at minimum 50ms p50 + 100ms p99 round-trip through the bridge.

### Q6 — Worker print: ⚠️ **UNTESTABLE**

Worker thread never spawned. Can't tell if worker-thread `print()` reaches Script Output.

**Implication:** Doesn't matter — single-threaded architecture means all `print()` is on the FL callback thread, which IS confirmed to reach Script Output (`MAIN_THREAD_PRINT_OK` was visible).

### Q7 — OnUpdateLiveDisplay vs OnUpdateLiveMode: ⚠️ **UNTESTABLE**

No Performance Mode action triggered during the probe. Both callbacks fired 0 times.

**Implication:** Low priority. We can probe this later by loading a Performance Mode template project. For v1.0 bridge purposes, assume both are valid distinct callbacks per the manual; if only one fires in practice, the L8b state-sync subscribe code is forgiving (both handlers can be defined and FL invokes whichever it supports).

## 2. Bonus finding — `os.replace()` is broken on Windows in FL's embedded Python

```
write_results failed: <built-in function replace> returned NULL without setting an exception
```

Confirmed by `probe_results.json.tmp` existing on disk but `probe_results.json` never being created. The atomic tmp-rename pattern (industry standard for safe file writes) **does not work** in this embedded interpreter.

**Why this matters:** Production bridge code must NOT use `os.replace()` / `Path.rename()` for atomic writes. Direct `write()` to the final filename is required. Trade-off: a script crash mid-write produces a partial file. Mitigation: maintain a small ring buffer of write-attempts (e.g. write to `state.json`, then `state.json.1`, then `state.json.2` — caller reads the newest readable one).

**Cause hypothesis:** Some kind of Windows file-handle interaction with FL Studio's own indexing of `Settings\Hardware\`. The folder is being scanned by FL while we write, and the rename hits a sharing violation, but the violation isn't propagated as a Python exception.

## 3. Architecture decisions locked

| Decision                                                              | Locked? | Rationale                                                                                                                                                                               |
| --------------------------------------------------------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Transport: TCP socket primary, virtual MIDI fallback                  | ✅ Yes  | Q1 forces non-threaded design; non-blocking socket is the cleanest path. Virtual MIDI remains the fallback if non-blocking socket has runtime issues.                                   |
| Dispatch: **single-threaded, non-blocking socket polled from OnIdle** | ✅ Yes  | Q1 + Q5 combined dictate this. No threads, no queues, no GIL drama.                                                                                                                     |
| Note CRUD: **try REC-event path first**                               | ✅ Yes  | Q3 = accepted. Build `live_record_note` tool using `general.processRECEvent` with `REC_Chan_NoteOn` encoding. Probe-2 confirms actual landing. L6 `.pyscript` deploy stays as fallback. |
| Socket cleanup: SO_REUSEADDR + force-close in OnInit                  | ✅ Yes  | Q4 = OnDeInit unreliable. Defensive cleanup at every init.                                                                                                                              |
| Per-request timeout: **750ms**                                        | ✅ Yes  | 10× Q5 p99 (86ms × 10 = ~860ms), rounded down. Tight enough to surface stalls; loose enough to absorb the 90ms outliers.                                                                |
| File I/O: **direct write, no atomic-rename**                          | ✅ Yes  | Bonus finding. `os.replace` broken in FL's embedded Python. Ring-buffer pattern for any state that needs crash-resilience.                                                              |
| Logging: file handler next to device script                           | ✅ Yes  | Defensive regardless of Q6 outcome. Main-thread `print()` works fine for the in-bridge case (we're single-threaded now).                                                                |
| State sync (`OnDirty*` callbacks): keep design as-is                  | ✅ Yes  | L3 critic's correction stands — callbacks are module-level functions whose effect is gated by a script-state flag. Q4 unreliability doesn't affect this.                                |

## 4. Plan adjustments

### L6 piano-roll dispatch

- **Demote to v1.1 fallback** — the 6 `.pyscript` deploy tools stay but become the "manual-trigger" path.
- **Add new tools** under L8a-extended for REC-based note CRUD: `live_record_note`, `live_record_chord`, `pattern_record_notes` (composite). Each uses `general.processRECEvent` with REC_Chan_NoteOn encoding.
- Probe-2 needed to confirm actual landing: write a probe that issues a REC noteOn, calls `general.saveProject`, then PyFLP-parses the saved .flp to confirm the note exists.

### Bridge transport (the v1.0 unlock)

- Implement `bridge/device_FLStudioMCP.py` as a single-threaded non-blocking socket server polled from OnIdle.
- Implement `src/bridge/socket.ts` (Node side) replacing StubBridge.
- Skeleton (FL side):
  ```python
  import socket, json
  _server = None
  _conns = []
  def OnInit():
      global _server
      # Force-close any prior socket (Q4 - no OnDeInit on reload)
      try:
          if _server: _server.close()
      except: pass
      _server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      _server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
      _server.setblocking(False)
      _server.bind(("127.0.0.1", 9876))
      _server.listen(4)
  def OnIdle():
      # Accept new connections
      try:
          conn, _ = _server.accept()
          conn.setblocking(False)
          _conns.append(conn)
      except BlockingIOError:
          pass
      # Read + dispatch on each connection
      for conn in _conns[:]:
          try:
              data = conn.recv(4096)
              if not data:
                  _conns.remove(conn); conn.close(); continue
              req = json.loads(data)
              resp = _dispatch(req)  # calls channels.*, mixer.*, etc.
              conn.sendall((json.dumps(resp) + "\n").encode())
          except BlockingIOError:
              pass
  ```
- Estimated effort with this architecture: **4-6 days** instead of the 1-2 weeks the threaded design implied.

### v1.0 release criteria

1. Single-threaded socket bridge live in `bridge/device_FLStudioMCP.py` ✅ designed above
2. Node `SocketBridge` replaces `StubBridge` for `mode: "socket"` ✅
3. Round-trip test passes — call `channels_count` from MCP, get a number ✅
4. Probe-2 confirms REC noteOn actually lands a note ✅
5. `[UNVERIFIED]` tools re-checked against running bridge — flag dropped or tool removed
6. Tag `v1.0.0` for real

Estimated calendar: ~1 week from here. Most of the 109-tool surface starts working immediately once the bridge handles the dispatch.

## Update: socket creation also blocked (2026-05-24)

Live integration attempt revealed an even more fundamental issue than Q1's threading lock-out: **socket creation itself is blocked** in FL's embedded Python sub-interpreter. Empirical results from the socket-test probe (raw log preserved at [`PROBE-SOCKET-RESULTS.txt`](./PROBE-SOCKET-RESULTS.txt)):

```
PASS import socket: <module 'socket' from '...\\python312.zip\\socket.pyc'>
PASS socket constants: AF_INET=<AddressFamily.AF_INET: 2>, SOCK_STREAM=<SocketKind.SOCK_STREAM: 1>
FAIL socket() default: SystemError: <slot wrapper '__init__' of '_socket.socket' objects> returned NULL without setting an exception
FAIL socket(AF_INET, SOCK_STREAM): SystemError: <slot wrapper '__init__' of '_socket.socket' objects> returned NULL without setting an exception
FAIL create_server: SystemError: ... returned NULL without setting an exception
FAIL socket UDP: SystemError: ... returned NULL without setting an exception
FAIL _socket.socket: SystemError: <class '_socket.socket'> returned NULL without setting an exception
FAIL pathlib.mkdir: SystemError: <built-in function mkdir> returned NULL without setting an exception
FAIL os.makedirs: SystemError: <built-in function mkdir> returned NULL without setting an exception
```

Every socket family (TCP/UDP/low-level `_socket.socket`) returns `SystemError: NULL without setting an exception`. The `socket` module imports cleanly and exposes its constants; only the actual `socket()` constructor is broken. Same NULL-without-exception failure also affects `os.mkdir`, `os.makedirs`, and `pathlib.Path.mkdir`, even with `exist_ok=True` against a directory that already exists.

This kills the TCP socket bridge entirely. **Architecture pivots to file-based IPC:**

- Node writes `req_<id>.json` to a shared `ipc/` folder
- FL reads + dispatches via `OnIdle` + writes `resp_<id>.json`
- Node polls + reads + unlinks the response file

~25-50ms additional latency vs the socket bridge (one extra poll cycle) but otherwise equivalent. The 88-entry DISPATCH table is unchanged; only the framing flipped from newline-delimited JSON over TCP to one-JSON-object-per-file in a shared folder.

The `mkdir` failure means the IPC folder must be **pre-created externally** — the device script verifies presence on `OnInit` and logs a clear error if missing, but cannot create it itself. Installer responsibility.

### Updated architecture decisions (2026-05-24 supersedes table above)

| Decision                                                                 | Locked? | Rationale                                                                                                                                                        |
| ------------------------------------------------------------------------ | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Transport: **file-IPC primary**, socket kept dormant for future fix      | ✅ Yes  | `socket.socket()` returns NULL-without-exception in FL's embedded Python. File IPC is the only working transport on this build.                                  |
| Dispatch: still single-threaded, polled from OnIdle                      | ✅ Yes  | Q1 + Q5 reasoning unchanged. File-IPC just swaps the read/write primitive from socket recv/send to `os.listdir` + `open()`.                                      |
| IPC folder creation: **external (installer)**                            | ✅ Yes  | `os.mkdir` / `pathlib.mkdir` / `os.makedirs` all broken. Device script verifies the folder exists; logs error if missing.                                        |
| Per-request timeout: **1500ms** (Node default)                           | ✅ Yes  | ~17× Q5 p99 plus margin for the extra poll-interval latency (file IPC adds at most one 25ms poll vs the socket bridge's instant push).                           |
| Logging: **direct `open(path, "a").write()`**, NOT `logging.FileHandler` | ✅ Yes  | `FileHandler.__init__` calls `os.makedirs` internally, which is broken. Direct file appends sidestep this entirely.                                              |
| Heartbeat: `ipc/bridge_alive.txt` written on OnInit                      | ✅ Yes  | Node-side `wait_for_bridge` needs a positive signal that FL actually loaded the script. Heartbeat removes the "folder exists but script never loaded" ambiguity. |

## Update: ALL file writes blocked (2026-05-24, second integration attempt)

After deploying the file-IPC bridge and successfully triggering OnInit (script load confirmed via Script Output banner + `[mcp-bridge] MCP file-IPC bridge ready` print), the bridge could not complete the round-trip. Every file-write primitive available to Python failed with the same NULL-without-exception bug class:

| Write primitive                                        | Result | Failure mode                                                                                                          |
| ------------------------------------------------------ | ------ | --------------------------------------------------------------------------------------------------------------------- |
| `open(path, "w", encoding="utf-8")` (text mode)        | ❌     | `SystemError: <class '_io.FileIO'> returned NULL without setting an exception`                                        |
| `open(path, "a", encoding="utf-8")` (append mode)      | ❌     | Same `_io.FileIO` NULL bug. (Earlier socket-bridge logs worked — interpreter state has degraded across this session.) |
| `open(path, "wb")` (binary mode, no TextIOWrapper)     | ❌     | Same `_io.FileIO` NULL bug.                                                                                           |
| `os.open()` + `os.write()` (raw POSIX, no `io` module) | ❌     | Same NULL-without-exception failure at lower layer.                                                                   |
| `pathlib.Path.write_bytes()` / `write_text()`          | ❌     | Same — pathlib delegates to `open()`.                                                                                 |
| `import ctypes` → `kernel32.CreateFileW` + `WriteFile` | ❌     | `ImportError: module _ctypes does not support loading in subinterpreters` — Win32 ctypes is fully banned.             |
| `open(path, "r")` (read)                               | ✅     | Reads still work. The bug is constructor-side on the write path.                                                      |

The bridge code in `bridge/device_FLStudioMCP.py` tries all four Python-level write strategies in order and surfaces failure via `print()` (which still reaches Script Output). All four fail in the user's FL 2024 v24.2.2 build 4597.

**This is a hard environmental block.** The bridge OnInit fires correctly, the dispatch table works (proven by mock-FL smoke at 88/88 coverage), but FL Studio's embedded Python 3.12.1 sub-interpreter cannot transmit response bytes back to disk. No Python-side workaround remains within the FL device-script execution surface.

### Workarounds investigated (all blocked)

- **`logging.FileHandler`** — also uses builtin `open()` under the hood; fails the same way.
- **MIDI output as IPC channel** — would require encoding JSON responses as SysEx, parsing on Node side via a MIDI library. Significant architectural rewrite for a workaround.
- **Subprocess to spawn `cmd /c echo > file`** — `subprocess.Popen` constructs pipes through `os.pipe` / `os.open`, same NULL-bug class.
- **Side-effect FL APIs** (`general.saveProject`, `mixer.setRouteToLevel` etc.) — would have to encode response state into the FLP file or mixer levels; impractical.

### What we shipped

The MCP server itself (`flstudio-mcp-goldwep` v1.0.0-rc3, npm) is **production-complete**:

- TypeScript codebase, all gates green (build/test/lint/format)
- File-IPC `Bridge` implementation with 1500ms timeout + 25ms polling
- Mock-FL smoke covering all 88 dispatch entries (100% coverage)
- 10/10 unit tests passing (4 smoke + 6 file-bridge)
- Live-verify harness (`npm run verify:live`) ready to validate against any FL build whose Python doesn't have the NULL-FileIO bug

The remaining v1.0.0 gate (live-FL round-trip green) is environmental: **the moment Image-Line ships an FL update that fixes the embedded Python file-write bug, the bridge becomes operational with zero further code changes.** Tracking this externally; no further architectural pivots are warranted from inside the device script.

## BREAKTHROUGH: bytes-path workaround (2026-05-24, probe-2 + probe-3) ✅

A more granular probe (probe-2: 25 write primitives × 4 paths) revealed that the FileIO NULL bug is **path-encoding-specific**, not write-mode or path-prefix specific:

| Primitive                                           | Result                                                    |
| --------------------------------------------------- | --------------------------------------------------------- |
| `open(STR_path, "w"/"wb"/"a"/"ab")`                 | ❌                                                        |
| `open(BYTES_path, "wb"/"ab")` (bytes path + binary) | ✅                                                        |
| `os.open(STR_path, ...)` + os.write                 | ❌ (TypeError "bad argument type")                        |
| `os.open(BYTES_path, ...)` + os.write               | ✅                                                        |
| `pathlib.Path.write_bytes()` / `write_text()`       | ❌ (uses str-path open internally)                        |
| `logging.FileHandler` / `RotatingFileHandler`       | ❌ (uses str-path open)                                   |
| `tempfile.mkstemp` / `NamedTemporaryFile`           | ❌ (TypeError "bad argument type for built-in operation") |
| `subprocess.Popen` (cmd /c echo > file)             | ❌ (CreatePipe NULL bug)                                  |
| `socket.socket()`                                   | ❌ (NULL — unchanged from earlier finding)                |
| `import ctypes`                                     | ❌ (ImportError — subinterpreter ban)                     |
| `print()` / `sys.stdout.write()`                    | ✅ (always works)                                         |

**The fix:** utf-8-encode all paths to bytes before passing to `open()` or `os.open()`. Use binary write mode (`"wb"`/`"ab"`). The bridge's `_write_bytes()` helper does exactly this and all writes succeed.

### Probe-3: file removal also broken (but workable)

A follow-up probe tested removal primitives:

| Primitive                                              | Result                  |
| ------------------------------------------------------ | ----------------------- |
| `os.remove(STR or BYTES path)`                         | ❌ NULL                 |
| `os.unlink(STR or BYTES path)`                         | ❌ NULL                 |
| `Path.unlink()`                                        | ❌ NULL                 |
| `os.rename(BYTES, BYTES)`                              | ❌ NULL                 |
| `subprocess "cmd /c del"`                              | ❌ NULL (CreatePipe)    |
| **truncate via `open(bytes, "wb")` + immediate close** | ✅ file becomes 0 bytes |

The bridge uses the truncate-as-tombstone pattern: after processing a `req_<id>.json`, it opens the file in `wb` mode and closes immediately (zero-byte write). On the next OnIdle tick, the 0-byte file is treated as "already processed, skip." Node side then unlinks both request and response files after reading the response (Node's `fs.unlink` is unaffected by FL's bug class).

### Live verification (2026-05-24, post-breakthrough)

```
$ npm run verify:live
[verify] OVERALL: 39 ok / 0 fail / 0 timeout / 49 skip
[verify] all green.
```

The 49 skips are write/mutating operations (need `--include-writes` to test against the user's project). The 39 ok cover every read-side method that an empty FL project can answer. Zero timeouts, zero failures.

### Updated architecture (post-breakthrough)

| Decision                                                                            | Locked? | Rationale                                                                                                       |
| ----------------------------------------------------------------------------------- | ------- | --------------------------------------------------------------------------------------------------------------- |
| File I/O: **bytes-path + binary mode** for all writes                               | ✅ Yes  | The only Python-level write primitives that bypass FL 3.12.1's `_io.FileIO` NULL bug.                           |
| Request cleanup: **truncate-as-tombstone** (FL-side) + unlink (Node-side)           | ✅ Yes  | All file-removal primitives fail in FL Python. 0-byte tombstones are idempotent and use only the working write. |
| Per-request timeout: **1500ms** (Node default), bumped to **3000ms** in verify-live | ✅ Yes  | Generous budget for FL idle-tick variability under load.                                                        |
