// Node-side TCP socket bridge. Replaces StubBridge when
// `config.bridge.mode === "socket"`. Connects to the in-FL
// `device_FLStudioMCP.py` server on `127.0.0.1:9876` (default).
//
// Wire protocol: newline-delimited JSON. Requests carry an `id`; responses
// MUST echo the same `id` so the bridge can route them back to the awaiting
// caller — multiple requests can be in flight concurrently, and FL may reply
// out of order. See docs/PROBE-REPORT.md §3 for the architecture lock
// (single-threaded non-blocking socket polled from OnIdle, 750ms timeout
// budget tuned to 10× the Q5 p99 OnIdle cadence).

import { Socket } from "node:net";
import { type Bridge, BridgeError } from "./types.js";

export interface SocketBridgeOptions {
  host: string;
  port: number;
  connectTimeoutMs: number;
  requestTimeoutMs: number;
}

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
  timer: NodeJS.Timeout;
}

interface WireResponse {
  id?: number;
  ok?: boolean;
  result?: unknown;
  error?: string;
  code?: string;
}

export class SocketBridge implements Bridge {
  private readonly host: string;
  private readonly port: number;
  private readonly connectTimeoutMs: number;
  private readonly requestTimeoutMs: number;

  private socket: Socket | null = null;
  private connected = false;
  private connecting: Promise<void> | null = null;
  private readBuffer = "";
  private nextId = 1;
  private readonly pending = new Map<number, PendingRequest>();

  constructor(opts: SocketBridgeOptions) {
    this.host = opts.host;
    this.port = opts.port;
    this.connectTimeoutMs = opts.connectTimeoutMs;
    this.requestTimeoutMs = opts.requestTimeoutMs;
  }

  isConnected(): boolean {
    return this.connected;
  }

  async call(method: string, args?: unknown): Promise<unknown> {
    // Lazy connect on first call (and on every re-call after a drop).
    if (!this.connected) {
      try {
        await this.ensureConnected();
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        throw new BridgeError(
          `failed to connect to FL Studio socket bridge at ${this.host}:${this.port}: ${msg}. ` +
            `Install device_FLStudioMCP.py into FL Studio's MIDI script folder and reload.`,
          { code: "BRIDGE_CONNECT_FAILED", cause: err },
        );
      }
    }

    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, args: args ?? {} }) + "\n";

    return new Promise<unknown>((resolve, reject) => {
      const timer = setTimeout(() => {
        // Drop the in-flight slot before rejecting so a late response is
        // discarded silently rather than tripping a "no pending" warning.
        this.pending.delete(id);
        reject(
          new BridgeError(
            `bridge request timed out after ${this.requestTimeoutMs}ms (method="${method}", id=${id})`,
            { code: "BRIDGE_TIMEOUT" },
          ),
        );
      }, this.requestTimeoutMs);

      this.pending.set(id, { resolve, reject, timer });

      const sock = this.socket;
      if (!sock || !this.connected) {
        // Lost connection between ensureConnected() and the write — fail fast.
        this.pending.delete(id);
        clearTimeout(timer);
        reject(
          new BridgeError("bridge disconnected before request could be sent", {
            code: "BRIDGE_DISCONNECTED",
          }),
        );
        return;
      }

      sock.write(payload, (err) => {
        if (err) {
          this.pending.delete(id);
          clearTimeout(timer);
          reject(
            new BridgeError(`failed to write to bridge socket: ${err.message}`, {
              code: "BRIDGE_DISCONNECTED",
              cause: err,
            }),
          );
        }
      });
    });
  }

  private ensureConnected(): Promise<void> {
    if (this.connected && this.socket) return Promise.resolve();
    if (this.connecting) return this.connecting;

    this.connecting = new Promise<void>((resolve, reject) => {
      const sock = new Socket();
      let settled = false;

      const connectTimer = setTimeout(() => {
        if (settled) return;
        settled = true;
        sock.destroy();
        reject(new Error(`connect timeout after ${this.connectTimeoutMs}ms`));
      }, this.connectTimeoutMs);

      sock.once("connect", () => {
        if (settled) return;
        settled = true;
        clearTimeout(connectTimer);
        this.socket = sock;
        this.connected = true;
        resolve();
      });

      sock.once("error", (err) => {
        if (settled) return;
        settled = true;
        clearTimeout(connectTimer);
        sock.destroy();
        reject(err);
      });

      // Late errors (after connect) → treat as a disconnect.
      sock.on("error", (err) => {
        if (!settled) return; // pre-connect error already handled above
        this.handleDisconnect(err);
      });

      sock.on("close", () => {
        if (!settled) return; // pre-connect failure already rejected
        this.handleDisconnect(new Error("socket closed"));
      });

      sock.on("data", (chunk) => this.onData(chunk));

      sock.connect(this.port, this.host);
    });

    // Clear the in-flight connecting handle once it settles, so a later
    // reconnect attempt (after a drop) starts fresh. We swallow the
    // rejection on this side-channel (the caller's await sees it).
    const tracked = this.connecting;
    tracked.then(
      () => {
        if (this.connecting === tracked) this.connecting = null;
      },
      () => {
        if (this.connecting === tracked) this.connecting = null;
      },
    );

    return this.connecting;
  }

  private onData(chunk: Buffer): void {
    this.readBuffer += chunk.toString("utf8");

    // Split off complete lines. FL Studio frames each response with `\n`.
    // A partial trailing line stays in the buffer for the next data event.
    let newlineIdx: number;
    while ((newlineIdx = this.readBuffer.indexOf("\n")) !== -1) {
      const line = this.readBuffer.slice(0, newlineIdx);
      this.readBuffer = this.readBuffer.slice(newlineIdx + 1);
      if (line.length === 0) continue;
      this.dispatchResponse(line);
    }
  }

  private dispatchResponse(line: string): void {
    let parsed: WireResponse;
    try {
      parsed = JSON.parse(line) as WireResponse;
    } catch {
      // Malformed frame — nothing we can do (no id to fail). Drop it.
      // The caller's request will still time out, which is the right signal.
      return;
    }

    if (typeof parsed.id !== "number") return;

    const slot = this.pending.get(parsed.id);
    if (!slot) {
      // Response arrived after the request already timed out / was rejected.
      // Silently drop — the caller already heard "BRIDGE_TIMEOUT".
      return;
    }

    this.pending.delete(parsed.id);
    clearTimeout(slot.timer);

    if (parsed.ok === true) {
      slot.resolve(parsed.result);
    } else {
      slot.reject(
        new BridgeError(parsed.error ?? "bridge call failed (no error message)", {
          code: parsed.code ?? "FL_DISPATCH_ERROR",
        }),
      );
    }
  }

  private handleDisconnect(reason: Error): void {
    // Idempotent — `error` + `close` will both fire on a real drop, and we
    // only want to fail the in-flight requests once.
    if (!this.connected && this.pending.size === 0 && !this.socket) return;

    this.connected = false;
    const sock = this.socket;
    this.socket = null;
    this.readBuffer = "";

    if (sock) {
      sock.removeAllListeners();
      sock.destroy();
    }

    const err = new BridgeError(`bridge disconnected: ${reason.message}`, {
      code: "BRIDGE_DISCONNECTED",
      cause: reason,
    });

    for (const [, slot] of this.pending) {
      clearTimeout(slot.timer);
      slot.reject(err);
    }
    this.pending.clear();
  }
}
