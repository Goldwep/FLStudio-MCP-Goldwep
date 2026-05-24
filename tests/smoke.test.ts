// Vitest mirror of scripts/smoke.ts. Wires the tool graph against a mock
// McpServer, exercises `ping`, and characterizes one pure-TS generator.
//
// Goal: prove the test harness works end-to-end without booting the real
// stdio server (which blocks on stdin). The MockMcpServer below is a
// structural twin of the one in scripts/smoke.ts.

import { describe, it, expect } from "vitest";
import { loadConfig } from "../src/config.js";
import { registerTools } from "../src/server.js";
import { generateAddNotes } from "../src/pyscript/generator.js";

type Handler = (args: unknown, extra: unknown) => Promise<unknown> | unknown;

interface RegisteredTool {
  description?: string;
  inputSchema?: unknown;
  handler: Handler;
}

class MockMcpServer {
  public readonly tools = new Map<string, RegisteredTool>();

  registerTool(
    name: string,
    config: { description?: string; inputSchema?: unknown },
    handler: Handler,
  ): void {
    if (this.tools.has(name)) {
      throw new Error(`duplicate tool registration: ${name}`);
    }
    this.tools.set(name, {
      description: config.description,
      inputSchema: config.inputSchema,
      handler,
    });
  }
}

describe("smoke: tool registration graph", () => {
  const config = loadConfig();
  const mock = new MockMcpServer();
  registerTools(mock as unknown as Parameters<typeof registerTools>[0], config);

  it("registers at least one tool", () => {
    expect(mock.tools.size).toBeGreaterThan(0);
  });

  it("registers the ping tool", () => {
    expect(mock.tools.has("ping")).toBe(true);
  });

  it("ping handler returns pong: true via StubBridge", async () => {
    const ping = mock.tools.get("ping");
    expect(ping).toBeDefined();

    const result = await ping!.handler({}, {});
    const resultObj = result as { content?: Array<{ text?: string }> };
    const text = resultObj.content?.[0]?.text;
    expect(text).toBeDefined();

    const parsed = JSON.parse(text!) as { pong?: boolean; ts?: number };
    expect(parsed.pong).toBe(true);
  });
});

describe("characterization: pyscript generator", () => {
  it("generateAddNotes emits a script that calls score.addNote", () => {
    const out = generateAddNotes([{ pitch: 60, position: 0, length: 96, velocity: 100 }]);
    expect(out).toContain("score.addNote");
  });
});
