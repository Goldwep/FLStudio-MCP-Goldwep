// Transport-agnostic bridge contract. All FL Studio API calls flow through
// this single chokepoint so the tool layer never depends on whether the
// underlying transport is a TCP socket, virtual MIDI loopback, or the FL
// Remote Scripting API. L0 probe selects the concrete implementation; until
// then StubBridge satisfies the interface so tooling can wire up end-to-end.

export interface Bridge {
  /**
   * Invoke a remote method on the FL Studio side. `method` is a dotted
   * namespace (e.g. "transport.start", "channels.midiNoteOn"). `args` is an
   * arbitrary JSON-serializable payload; concrete transports define their own
   * marshalling rules. Resolves with the bridge response (also JSON-shaped)
   * or rejects with a BridgeError.
   */
  call(method: string, args?: unknown): Promise<unknown>;

  /** True once the underlying transport has handshaken with FL Studio. */
  isConnected(): boolean;
}

export interface BridgeErrorOptions {
  code?: string;
  cause?: unknown;
}

export class BridgeError extends Error {
  public readonly code?: string;

  constructor(message: string, options: BridgeErrorOptions = {}) {
    super(message, options.cause ? { cause: options.cause } : undefined);
    this.name = "BridgeError";
    this.code = options.code;
  }
}
