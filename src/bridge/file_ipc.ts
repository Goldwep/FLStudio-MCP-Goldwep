// Node-side file-IPC bridge. Replaces SocketBridge when
// `config.bridge.mode === "file"`. Talks to the in-FL
// `device_FLStudioMCP.py` via a shared folder of request/response JSON
// files.
//
// Why file IPC: the 2026-05-24 live integration probe found that
// `socket.socket()` in FL's embedded Python 3.12.1 returns
// SystemError "NULL without setting an exception" for every socket type.
// `os.mkdir` is also broken (NULL-without-exception even with
// exist_ok=True on existing directories). The IPC folder must be
// pre-created externally — this bridge does NOT create it (would mask
// installation problems).
//
// Wire protocol:
//   ipc/req_<id>.json   {"id": <n>, "method": "...", "args": {...}}
//   ipc/resp_<id>.json  {"id": <n>, "ok": true,  "result": ...}
//                       {"id": <n>, "ok": false, "error": "...",
//                                                "traceback": "..."}
//
// Race-condition notes:
//   * Request files are TRUNCATED (not deleted) by FL after dispatching.
//     FL Python 3.12.1 cannot delete files (every removal primitive hits
//     the NULL bug class) — see PROBE-REPORT.md "remove probe" finding.
//     The Node side cleans up the truncated tombstones by unlinking the
//     request file after the response is received; FL won't re-dispatch
//     a 0-byte req on a later OnIdle tick (it treats them as processed).
//   * Response files are read + parsed + unlinked. If parsing fails the
//     file is unlinked anyway so the next call with the same id doesn't
//     pick up corrupted data. (Ids are monotonic per Node session; FL
//     wipes leftover files on OnInit, so id collisions across sessions
//     are not a concern.)
//   * If we time out, we delete our request file so FL won't dispatch a
//     stale request after the caller has given up. If FL has already
//     read+deleted the request and is mid-dispatch, FL still writes a
//     response file; that file gets cleaned up the next time Node sees
//     a stray resp_ for an id it doesn't recognize (handled in `call`).
//   * Partial writes: FL opens resp_<id>.json, writes the full payload,
//     closes. Between open() and close() on FL's side, Node could see
//     a 0-byte file. Mitigation: a JSON.parse failure on an empty/
//     incomplete file is treated as "not ready yet" -- we keep polling.

import { readFile, stat, unlink, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { type Bridge, BridgeError } from "./types.js";

export interface FileBridgeOptions {
  ipcDir?: string;
  requestTimeoutMs?: number;
  /** Poll interval for the response file. Default 25ms. */
  pollIntervalMs?: number;
}

interface WireResponse {
  id?: number;
  ok?: boolean;
  result?: unknown;
  error?: string;
  traceback?: string;
  code?: string;
}

const DEFAULT_IPC_DIR = join(
  homedir(),
  "Documents",
  "Image-Line",
  "FL Studio",
  "Settings",
  "Hardware",
  "FLStudio-MCP",
  "ipc",
);

const DEFAULT_REQUEST_TIMEOUT_MS = 1500;
const DEFAULT_POLL_INTERVAL_MS = 25;

export class FileBridge implements Bridge {
  private readonly ipcDir: string;
  private readonly requestTimeoutMs: number;
  private readonly pollIntervalMs: number;
  private nextId = 1;

  constructor(opts: FileBridgeOptions = {}) {
    this.ipcDir = opts.ipcDir ?? DEFAULT_IPC_DIR;
    this.requestTimeoutMs = opts.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
    this.pollIntervalMs = opts.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  }

  /**
   * Returns true if the IPC folder exists on disk. The folder is created
   * by the installer (not by Node, not by FL — mkdir is broken in FL's
   * embedded Python). A missing folder almost certainly means the device
   * script was never installed.
   */
  isConnected(): boolean {
    return existsSync(this.ipcDir);
  }

  async call(method: string, args?: unknown): Promise<unknown> {
    if (!existsSync(this.ipcDir)) {
      throw new BridgeError(
        `FL Studio bridge IPC folder missing: ${this.ipcDir}. ` +
          `Install device_FLStudioMCP.py into FL Studio's MIDI script folder, ` +
          `ensure the ipc/ subfolder exists (the installer creates it), and ` +
          `reload the device script.`,
        { code: "BRIDGE_CONNECT_FAILED" },
      );
    }

    // Fail fast when the heartbeat says FL is dead. The bridge rewrites
    // bridge_alive.txt every ~5s from OnIdle; a missing/empty/stale
    // heartbeat means no OnIdle pump is running, so a request would just
    // sit unprocessed until the timeout. Failing here converts a
    // guaranteed 1500ms "timed out" into an instant, accurate error.
    if (!(await isBridgeAlive(this.ipcDir))) {
      throw new BridgeError(
        `FL Studio bridge is not running (heartbeat missing or stale in ${this.ipcDir}). ` +
          `Start FL Studio, ensure the "FLStudio MCP Bridge" controller is enabled in ` +
          `MIDI Settings, and check FL's Script Output for "[mcp-bridge] ... ready".`,
        { code: "BRIDGE_NOT_READY" },
      );
    }

    const id = this.nextId++;
    const reqPath = join(this.ipcDir, `req_${id}.json`);
    const respPath = join(this.ipcDir, `resp_${id}.json`);
    const payload = JSON.stringify({ id, method, args: args ?? {} });

    try {
      await writeFile(reqPath, payload, "utf8");
    } catch (err) {
      throw new BridgeError(
        `failed to write request file ${reqPath}: ${err instanceof Error ? err.message : String(err)}`,
        { code: "BRIDGE_DISCONNECTED", cause: err },
      );
    }

    const deadline = Date.now() + this.requestTimeoutMs;
    while (Date.now() < deadline) {
      const respText = await tryReadResponse(respPath);
      if (respText !== null) {
        // Parse + unlink. We unlink the response file BEFORE returning so
        // a future request with the same id (after a restart) doesn't
        // accidentally pick up stale data.
        let parsed: WireResponse;
        try {
          parsed = JSON.parse(respText) as WireResponse;
        } catch {
          // Empty or truncated file — FL is mid-write. Keep polling.
          await sleep(this.pollIntervalMs);
          continue;
        }
        // We have a complete parse. Unlink BOTH files (FL can't delete --
        // see header comment) and route the result.
        await safeUnlink(respPath);
        await safeUnlink(reqPath);
        if (parsed.ok === true) {
          return parsed.result;
        }
        throw new BridgeError(parsed.error ?? "bridge call failed (no error message)", {
          code: parsed.code ?? "FL_DISPATCH_ERROR",
        });
      }
      await sleep(this.pollIntervalMs);
    }

    // Timeout. Best-effort cleanup of our request file -- FL may not have
    // picked it up yet, in which case we want to cancel rather than leak.
    // If FL already deleted it (dispatch in flight), unlink is a no-op.
    await safeUnlink(reqPath);
    // Also try to clean up a late response that might land between our
    // last poll and the unlink -- that response would otherwise stay
    // forever as garbage in ipc/.
    await safeUnlink(respPath);

    throw new BridgeError(
      `bridge request timed out after ${this.requestTimeoutMs}ms (method="${method}", id=${id})`,
      { code: "BRIDGE_TIMEOUT" },
    );
  }
}

async function tryReadResponse(path: string): Promise<string | null> {
  try {
    const s = await stat(path);
    if (s.size === 0) {
      // Zero-byte file: FL has open()'d for write but not flushed yet.
      // Keep polling -- a JSON.parse on "" would fail anyway.
      return null;
    }
    return await readFile(path, "utf8");
  } catch (err) {
    if (isENOENT(err)) {
      return null;
    }
    // Any other error (EACCES, EBUSY) -- treat as "not ready yet" and
    // keep polling. If it's a real permissions issue the request will
    // time out, which is the correct user surface.
    return null;
  }
}

async function safeUnlink(path: string): Promise<void> {
  try {
    await unlink(path);
  } catch (err) {
    if (!isENOENT(err)) {
      // Best-effort -- non-existence is fine; anything else we swallow
      // so callers don't get a secondary failure during cleanup.
    }
  }
}

function isENOENT(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    "code" in err &&
    (err as { code?: string }).code === "ENOENT"
  );
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Heartbeat freshness window. The FL bridge rewrites bridge_alive.txt
// every ~5s from OnIdle. FL's Python cannot delete files, so the file
// SURVIVES FL closing — existence alone is meaningless. A live bridge is
// one whose heartbeat is non-empty and recently modified.
const HEARTBEAT_FRESH_MS = 20_000;

// Liveness probe for the FL bridge (e.g. verify-live's wait-for-bridge
// loop). Returns true only when the heartbeat file exists, is non-empty
// (a 0-byte file is a tombstone left by OnDeInit), and was modified
// within the freshness window (a stale mtime means FL is closed — the
// file cannot be deleted from FL's side, so staleness is the only
// death signal).
export async function isBridgeAlive(ipcDir: string = DEFAULT_IPC_DIR): Promise<boolean> {
  try {
    const s = await stat(join(ipcDir, "bridge_alive.txt"));
    if (s.size === 0) return false;
    return Date.now() - s.mtimeMs < HEARTBEAT_FRESH_MS;
  } catch {
    return false;
  }
}

export { DEFAULT_IPC_DIR };
