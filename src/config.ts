import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

export type BridgeMode = "stub" | "socket" | "midi";

export interface Config {
  bridge: {
    mode: BridgeMode;
    host: string;
    port: number;
    connectTimeoutMs: number;
    requestTimeoutMs: number;
  };
}

const DEFAULTS: Config = {
  bridge: {
    // Default to "socket" — the production transport. Per probe data, the FL
    // device script at bridge/device_FLStudioMCP.py listens on 127.0.0.1:9876.
    // If FL isn't running OR the controller script isn't assigned, the
    // SocketBridge returns a clean BRIDGE_CONNECT_FAILED with an install hint
    // rather than the confusing BRIDGE_NOT_READY of the StubBridge.
    // Users who want pure-offline operation (L7 PyFLP + L6 .pyscript only)
    // can override with `{"bridge": {"mode": "stub"}}` in flstudio-mcp.config.json.
    mode: "socket",
    host: "127.0.0.1",
    port: 9876,
    connectTimeoutMs: 3000,
    // 750ms = 10× Q5 p99 from probe (86ms × 10 ≈ 860, rounded down to 750
    // for tighter stall-detection while still absorbing the 90ms outliers).
    requestTimeoutMs: 750,
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
