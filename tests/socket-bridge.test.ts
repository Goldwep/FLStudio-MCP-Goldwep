// Unit tests for SocketBridge. Spins up an in-process Node TCP server to act
// as the FL Studio side, exercising the happy path, an error response, and
// the timeout + unreachable-server failure modes. No real FL Studio needed.

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { createServer, type Server, type Socket as NetSocket } from "node:net";
import { SocketBridge } from "../src/bridge/socket.js";
import { BridgeError } from "../src/bridge/types.js";

interface ServerHandle {
  server: Server;
  port: number;
  sockets: NetSocket[];
}

type LineHandler = (req: { id: number; method: string; args?: unknown }, sock: NetSocket) => void;

async function startServer(handle: LineHandler): Promise<ServerHandle> {
  return new Promise((resolve, reject) => {
    const sockets: NetSocket[] = [];
    const server = createServer((sock) => {
      sockets.push(sock);
      let buf = "";
      sock.on("data", (chunk) => {
        buf += chunk.toString("utf8");
        let idx: number;
        while ((idx = buf.indexOf("\n")) !== -1) {
          const line = buf.slice(0, idx);
          buf = buf.slice(idx + 1);
          if (!line) continue;
          try {
            const req = JSON.parse(line) as { id: number; method: string; args?: unknown };
            handle(req, sock);
          } catch {
            // ignore malformed lines in tests
          }
        }
      });
      sock.on("error", () => {
        /* swallow */
      });
    });
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      if (!addr || typeof addr === "string") {
        reject(new Error("no server address"));
        return;
      }
      resolve({ server, port: addr.port, sockets });
    });
  });
}

async function stopServer(handle: ServerHandle): Promise<void> {
  for (const s of handle.sockets) {
    try {
      s.destroy();
    } catch {
      /* swallow */
    }
  }
  await new Promise<void>((resolve) => handle.server.close(() => resolve()));
}

describe("SocketBridge: connect failure", () => {
  it("rejects with BRIDGE_CONNECT_FAILED when nothing is listening", async () => {
    // Port 1 on localhost is virtually guaranteed not to have anything bound
    // for a regular user; use a tight connect timeout so the test stays quick.
    const bridge = new SocketBridge({
      host: "127.0.0.1",
      port: 1,
      connectTimeoutMs: 250,
      requestTimeoutMs: 500,
    });
    await expect(bridge.call("ping")).rejects.toMatchObject({
      name: "BridgeError",
      code: "BRIDGE_CONNECT_FAILED",
    });
    expect(bridge.isConnected()).toBe(false);
  });
});

describe("SocketBridge: round-trip against in-process server", () => {
  let handle: ServerHandle;

  beforeEach(async () => {
    handle = await startServer((req, sock) => {
      if (req.method === "ping") {
        const resp = { id: req.id, ok: true, result: { pong: true, ts: 1234 } };
        sock.write(JSON.stringify(resp) + "\n");
      } else if (req.method === "fail") {
        const resp = { id: req.id, ok: false, error: "boom" };
        sock.write(JSON.stringify(resp) + "\n");
      }
      // "stall" — intentionally no response (used by timeout test below).
    });
  });

  afterEach(async () => {
    await stopServer(handle);
  });

  it("resolves with result on ok:true", async () => {
    const bridge = new SocketBridge({
      host: "127.0.0.1",
      port: handle.port,
      connectTimeoutMs: 1000,
      requestTimeoutMs: 1000,
    });
    const result = (await bridge.call("ping")) as { pong: boolean; ts: number };
    expect(result.pong).toBe(true);
    expect(result.ts).toBe(1234);
    expect(bridge.isConnected()).toBe(true);
  });

  it("rejects with BridgeError carrying the error message on ok:false", async () => {
    const bridge = new SocketBridge({
      host: "127.0.0.1",
      port: handle.port,
      connectTimeoutMs: 1000,
      requestTimeoutMs: 1000,
    });
    await expect(bridge.call("fail")).rejects.toMatchObject({
      name: "BridgeError",
      message: "boom",
    });
  });

  it("times out with BRIDGE_TIMEOUT when the server does not respond", async () => {
    const bridge = new SocketBridge({
      host: "127.0.0.1",
      port: handle.port,
      connectTimeoutMs: 1000,
      requestTimeoutMs: 150,
    });
    let caught: unknown = null;
    try {
      await bridge.call("stall");
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(BridgeError);
    expect((caught as BridgeError).code).toBe("BRIDGE_TIMEOUT");
  });

  it("routes concurrent in-flight requests by id (out-of-order responses ok)", async () => {
    // Replace the server handler to deliberately respond to "b" before "a".
    await stopServer(handle);
    const pendingA: Array<() => void> = [];
    handle = await startServer((req, sock) => {
      if (req.method === "a") {
        // Defer response until we've already answered "b".
        pendingA.push(() => {
          sock.write(JSON.stringify({ id: req.id, ok: true, result: "A" }) + "\n");
        });
      } else if (req.method === "b") {
        sock.write(JSON.stringify({ id: req.id, ok: true, result: "B" }) + "\n");
        // Now flush A.
        for (const fn of pendingA.splice(0)) fn();
      }
    });

    const bridge = new SocketBridge({
      host: "127.0.0.1",
      port: handle.port,
      connectTimeoutMs: 1000,
      requestTimeoutMs: 1000,
    });
    const [a, b] = await Promise.all([bridge.call("a"), bridge.call("b")]);
    expect(a).toBe("A");
    expect(b).toBe("B");
  });
});
