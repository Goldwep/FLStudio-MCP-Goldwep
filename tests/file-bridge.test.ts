// Unit tests for FileBridge. Simulates the FL side with an in-process
// poller that watches the IPC folder and writes responses. No real FL
// needed.
//
// File IPC contract recap:
//   ipc/req_<id>.json   — Node writes; FL reads + deletes + dispatches
//   ipc/resp_<id>.json  — FL writes;   Node reads + deletes
// FileBridge times out by deleting its own request file (cancel) and
// the response file (if a late response slipped in).
//
// We use a unique tmp dir per test so concurrent test files don't trip
// over each other's IPC traffic.

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync, readdirSync, readFileSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { FileBridge, isBridgeAlive } from "../src/bridge/file_ipc.js";
import { BridgeError } from "../src/bridge/types.js";

// ---------------------------------------------------------------------------
// Fake-FL poller. Watches the IPC folder; for each req_*.json it sees,
// deletes the request and writes a response according to a per-method
// rule supplied by the test.
// ---------------------------------------------------------------------------

type ReqHandler = (req: {
  id: number;
  method: string;
  args?: unknown;
}) => { ok: true; result: unknown } | { ok: false; error: string; code?: string } | "stall"; // intentionally no response (used for timeout tests)

interface FakeFL {
  dir: string;
  stop: () => void;
}

function startFakeFL(dir: string, handle: ReqHandler, intervalMs = 5): FakeFL {
  // Real FL writes a heartbeat from OnInit + refreshes it from OnIdle;
  // FileBridge.call() fails fast with BRIDGE_NOT_READY without a fresh
  // one, so the fake FL must provide it too.
  writeFileSync(join(dir, "bridge_alive.txt"), String(Date.now()), "utf8");
  const timer = setInterval(() => {
    let entries: string[];
    try {
      entries = readdirSync(dir);
    } catch {
      return;
    }
    for (const name of entries) {
      if (!name.startsWith("req_") || !name.endsWith(".json")) continue;
      const reqPath = join(dir, name);
      let raw: string;
      try {
        raw = readFileSync(reqPath, "utf8");
      } catch {
        continue;
      }
      let req: { id: number; method: string; args?: unknown };
      try {
        req = JSON.parse(raw) as typeof req;
      } catch {
        continue;
      }
      // FL deletes the request file BEFORE dispatching -- mirror that.
      try {
        rmSync(reqPath);
      } catch {
        // race ok
      }
      const verdict = handle(req);
      if (verdict === "stall") continue;
      const respPath = join(dir, `resp_${req.id}.json`);
      const payload = verdict.ok
        ? { id: req.id, ok: true, result: verdict.result }
        : { id: req.id, ok: false, error: verdict.error, code: verdict.code };
      try {
        writeFileSync(respPath, JSON.stringify(payload), "utf8");
      } catch {
        // race ok
      }
    }
  }, intervalMs);

  return {
    dir,
    stop: () => clearInterval(timer),
  };
}

// ---------------------------------------------------------------------------
// Per-test scratch dir
// ---------------------------------------------------------------------------

describe("FileBridge: missing IPC folder", () => {
  it("rejects with BRIDGE_CONNECT_FAILED when the folder does not exist", async () => {
    // A path under tmpdir that definitely doesn't exist.
    const ghost = join(tmpdir(), `flstudio-mcp-test-ghost-${Date.now()}`);
    const bridge = new FileBridge({
      ipcDir: ghost,
      requestTimeoutMs: 500,
    });
    expect(bridge.isConnected()).toBe(false);
    await expect(bridge.call("ping")).rejects.toMatchObject({
      name: "BridgeError",
      code: "BRIDGE_CONNECT_FAILED",
    });
  });
});

describe("FileBridge: round-trip against fake-FL poller", () => {
  let dir: string;
  let fl: FakeFL;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "flstudio-mcp-test-"));
  });

  afterEach(() => {
    try {
      fl?.stop();
    } catch {
      // ignore
    }
    try {
      rmSync(dir, { recursive: true, force: true });
    } catch {
      // ignore
    }
  });

  it("resolves with result on ok:true", async () => {
    fl = startFakeFL(dir, (req) => {
      if (req.method === "ping") {
        return { ok: true, result: { pong: true, ts: 1234 } };
      }
      return { ok: false, error: `UnknownMethod: ${req.method}` };
    });
    const bridge = new FileBridge({ ipcDir: dir, requestTimeoutMs: 2000 });
    expect(bridge.isConnected()).toBe(true);
    const result = (await bridge.call("ping")) as { pong: boolean; ts: number };
    expect(result.pong).toBe(true);
    expect(result.ts).toBe(1234);
  });

  it("rejects with BridgeError carrying the error message on ok:false", async () => {
    fl = startFakeFL(dir, (req) => {
      if (req.method === "fail") {
        return { ok: false, error: "boom" };
      }
      return { ok: false, error: `unexpected ${req.method}` };
    });
    const bridge = new FileBridge({ ipcDir: dir, requestTimeoutMs: 2000 });
    await expect(bridge.call("fail")).rejects.toMatchObject({
      name: "BridgeError",
      message: "boom",
    });
  });

  it("times out with BRIDGE_TIMEOUT when FL never writes a response", async () => {
    fl = startFakeFL(dir, () => "stall");
    const bridge = new FileBridge({
      ipcDir: dir,
      requestTimeoutMs: 200,
      pollIntervalMs: 10,
    });
    let caught: unknown = null;
    try {
      await bridge.call("stall");
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(BridgeError);
    expect((caught as BridgeError).code).toBe("BRIDGE_TIMEOUT");
    // After timeout, our own request file should be cleaned up (so a
    // delayed FL dispatch doesn't process a stale request).
    const leftovers = readdirSync(dir).filter((n) => n.startsWith("req_") || n.startsWith("resp_"));
    expect(leftovers).toEqual([]);
  });

  it("routes concurrent in-flight requests by id (out-of-order responses ok)", async () => {
    // Stash "a" responses; flush them only after we see "b" so the
    // response order is b-then-a even though the calls were a-then-b.
    const pendingA: Array<() => void> = [];
    fl = startFakeFL(dir, (req) => {
      if (req.method === "a") {
        // Defer: capture a closure that writes the A response when we
        // later receive B.
        pendingA.push(() => {
          const respPath = join(dir, `resp_${req.id}.json`);
          writeFileSync(respPath, JSON.stringify({ id: req.id, ok: true, result: "A" }), "utf8");
        });
        return "stall"; // poller skips writing a response this tick
      }
      if (req.method === "b") {
        // Flush pending A responses BEFORE writing B.
        for (const fn of pendingA.splice(0)) fn();
        return { ok: true, result: "B" };
      }
      return { ok: false, error: `unexpected ${req.method}` };
    });
    const bridge = new FileBridge({
      ipcDir: dir,
      requestTimeoutMs: 2000,
      pollIntervalMs: 10,
    });
    const [a, b] = await Promise.all([bridge.call("a"), bridge.call("b")]);
    expect(a).toBe("A");
    expect(b).toBe("B");
  });

  it("isBridgeAlive: fresh non-empty heartbeat is alive; stale or empty is dead", async () => {
    const hb = join(dir, "bridge_alive.txt");

    // No heartbeat file at all -> dead.
    expect(await isBridgeAlive(dir)).toBe(false);

    // Fresh, non-empty heartbeat -> alive.
    writeFileSync(hb, String(Date.now()), "utf8");
    expect(await isBridgeAlive(dir)).toBe(true);

    // 0-byte heartbeat (OnDeInit tombstone) -> dead, even though fresh.
    writeFileSync(hb, "", "utf8");
    expect(await isBridgeAlive(dir)).toBe(false);

    // Non-empty but stale mtime (FL closed; file can't be deleted from
    // FL's side) -> dead.
    writeFileSync(hb, String(Date.now()), "utf8");
    const staleSec = (Date.now() - 60_000) / 1000;
    utimesSync(hb, staleSec, staleSec);
    expect(await isBridgeAlive(dir)).toBe(false);
  });

  it("survives a transient empty/partial response file", async () => {
    // Simulate FL writing the response in two steps: empty file first
    // (Node should keep polling), then full payload.
    fl = startFakeFL(dir, (req) => {
      if (req.method === "slow") {
        const respPath = join(dir, `resp_${req.id}.json`);
        // First write zero bytes (Node sees stat.size === 0 and skips).
        writeFileSync(respPath, "", "utf8");
        // After a short delay, overwrite with the real payload.
        setTimeout(() => {
          writeFileSync(respPath, JSON.stringify({ id: req.id, ok: true, result: 42 }), "utf8");
        }, 50);
        return "stall"; // we already wrote the file ourselves
      }
      return { ok: false, error: `unexpected ${req.method}` };
    });
    const bridge = new FileBridge({
      ipcDir: dir,
      requestTimeoutMs: 2000,
      pollIntervalMs: 10,
    });
    const result = await bridge.call("slow");
    expect(result).toBe(42);
  });
});
