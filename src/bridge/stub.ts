import { type Bridge, BridgeError } from "./types.js";

// Stand-in bridge used until the L0 probe selects a real transport. Every
// call short-circuits with BRIDGE_NOT_READY except "ping", which round-trips
// locally so smoke tests + tool-graph wiring can be exercised without FL
// Studio running.

export class StubBridge implements Bridge {
  async call(method: string, _args?: unknown): Promise<unknown> {
    if (method === "ping") {
      return { pong: true, ts: Date.now() };
    }
    throw new BridgeError("L0 probe pending — bridge transport not yet selected", {
      code: "BRIDGE_NOT_READY",
    });
  }

  isConnected(): boolean {
    return false;
  }
}
