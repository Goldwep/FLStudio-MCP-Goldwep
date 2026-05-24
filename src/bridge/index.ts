import type { Config } from "../config.js";
import { logger } from "../utils/logger.js";
import { FileBridge } from "./file_ipc.js";
import { SocketBridge } from "./socket.js";
import { StubBridge } from "./stub.js";
import type { Bridge } from "./types.js";

export type { Bridge, BridgeErrorOptions } from "./types.js";
export { BridgeError } from "./types.js";
export { FileBridge, isBridgeAlive, DEFAULT_IPC_DIR } from "./file_ipc.js";
export { SocketBridge } from "./socket.js";
export { StubBridge } from "./stub.js";

// Factory. Switches on config.bridge.mode.
//
// * `file` — production transport (default). Node writes req_<id>.json
//   into a shared folder; FL reads + dispatches + writes resp_<id>.json.
//   Required because socket.socket() returns NULL-without-exception in
//   FL's embedded Python sub-interpreter (live-probe finding 2026-05-24).
//
// * `socket` — KEPT for the day FL or Python fixes the embedded-socket
//   bug. Implementation is complete and tested; it just can't bind in
//   FL today.
//
// * `midi` — L8c fallback, still TBD.
//
// * `stub` — keeps the rest of the stack bootable while FL Studio is
//   offline. Smoke tests use this.
export function makeBridge(config: Config): Bridge {
  switch (config.bridge.mode) {
    case "file":
      return new FileBridge({
        ipcDir: config.bridge.ipcDir,
        requestTimeoutMs: config.bridge.requestTimeoutMs,
      });
    case "socket":
      return new SocketBridge({
        host: config.bridge.host,
        port: config.bridge.port,
        connectTimeoutMs: config.bridge.connectTimeoutMs,
        requestTimeoutMs: config.bridge.requestTimeoutMs,
      });
    case "midi":
      // Future fallback path (Q1=broken means file is primary; MIDI is L8c).
      // For now, log warning and stub it.
      logger.warn("bridge mode='midi' not yet implemented, falling back to stub");
      return new StubBridge();
    case "stub":
    default:
      return new StubBridge();
  }
}
