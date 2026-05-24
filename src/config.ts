import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

export type BridgeMode = "stub" | "file" | "socket" | "midi";

export interface Config {
  bridge: {
    mode: BridgeMode;
    /** File-IPC mode: absolute path to the shared request/response folder. */
    ipcDir?: string;
    /** Socket mode: hostname (kept for future use; sockets are broken in FL today). */
    host: string;
    /** Socket mode: port (kept for future use). */
    port: number;
    /** Socket mode: connect timeout. */
    connectTimeoutMs: number;
    /** Per-call timeout for the bridge transport. */
    requestTimeoutMs: number;
  };
}

const DEFAULTS: Config = {
  bridge: {
    // Default to "file" — the ONLY transport that actually works against
    // FL Studio today (2026-05-24). The live-FL probe found that
    // socket.socket() returns NULL-without-exception in FL's embedded
    // Python 3.12.1 sub-interpreter, so the socket mode cannot bind even
    // though its code is correct. See docs/PROBE-REPORT.md §"Update".
    //
    // File-IPC mode uses a shared folder of req_<id>.json / resp_<id>.json
    // files at the path below. The Node side polls every 25ms; the FL
    // side scans on OnIdle (~50ms p50, ~86ms p99).
    //
    // Users who want pure-offline operation (L7 PyFLP + L6 .pyscript only)
    // can override with `{"bridge": {"mode": "stub"}}` in flstudio-mcp.config.json.
    mode: "file",
    // ipcDir intentionally undefined here -- FileBridge resolves the
    // default from the user's home directory at construction time so the
    // config object stays portable.
    ipcDir: undefined,
    host: "127.0.0.1",
    port: 9876,
    connectTimeoutMs: 3000,
    // 1500ms = ~17× Q5 p99 (86ms × 17 ≈ 1462) plus a margin to absorb
    // the additional poll-interval latency of file IPC. File polling
    // adds at most one pollInterval (25ms) per round-trip vs the socket
    // bridge's instant push, so we widen the budget over the socket-era
    // 750ms.
    requestTimeoutMs: 1500,
  },
};

export function loadConfig(path = "flstudio-mcp.config.json"): Config {
  const abs = resolve(process.cwd(), path);
  if (!existsSync(abs)) return DEFAULTS;
  try {
    const raw = JSON.parse(readFileSync(abs, "utf8")) as Partial<Config>;
    return {
      bridge: { ...DEFAULTS.bridge, ...(raw.bridge ?? {}) },
    };
  } catch {
    return DEFAULTS;
  }
}
