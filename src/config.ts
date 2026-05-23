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
    mode: "stub",
    host: "127.0.0.1",
    port: 9876,
    connectTimeoutMs: 3000,
    requestTimeoutMs: 10000,
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
