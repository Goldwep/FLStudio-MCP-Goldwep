import type { Config } from "../config.js";
import { logger } from "../utils/logger.js";
import { StubBridge } from "./stub.js";
import type { Bridge } from "./types.js";

export type { Bridge, BridgeErrorOptions } from "./types.js";
export { BridgeError } from "./types.js";
export { StubBridge } from "./stub.js";

// Factory. Switches on config.bridge.mode once real transports land. Until
// L0 probe picks a winner, every mode falls through to StubBridge so the
// rest of the stack can boot.
export function makeBridge(config: Config): Bridge {
  const mode = config.bridge.mode;
  if (mode !== "stub") {
    logger.warn(`bridge mode "${mode}" not yet implemented — falling back to stub`);
  }
  return new StubBridge();
}
