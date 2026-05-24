import type { Config } from "../config.js";
import { logger } from "../utils/logger.js";
import { SocketBridge } from "./socket.js";
import { StubBridge } from "./stub.js";
import type { Bridge } from "./types.js";

export type { Bridge, BridgeErrorOptions } from "./types.js";
export { BridgeError } from "./types.js";
export { SocketBridge } from "./socket.js";
export { StubBridge } from "./stub.js";

// Factory. Switches on config.bridge.mode. `socket` is the v1.0 primary path
// (single-threaded non-blocking server polled from OnIdle on the FL side —
// see docs/PROBE-REPORT.md §3). `midi` is the L8c fallback, still TBD.
// `stub` keeps the rest of the stack bootable while FL Studio is offline.
export function makeBridge(config: Config): Bridge {
  switch (config.bridge.mode) {
    case "socket":
      return new SocketBridge({
        host: config.bridge.host,
        port: config.bridge.port,
        connectTimeoutMs: config.bridge.connectTimeoutMs,
        requestTimeoutMs: config.bridge.requestTimeoutMs,
      });
    case "midi":
      // Future fallback path (Q1=broken means socket is primary; MIDI is L8c).
      // For now, log warning and stub it.
      logger.warn("bridge mode='midi' not yet implemented, falling back to stub");
      return new StubBridge();
    case "stub":
    default:
      return new StubBridge();
  }
}
