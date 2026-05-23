// L1 smoke test. Wires the full tool graph against an in-memory mock of
// McpServer, then invokes the `ping` handler. Exits 0 if the StubBridge
// round-trips and returns pong: true. Run via `npx tsx scripts/smoke.ts`.
//
// We don't boot the real stdio server because that blocks on stdin. The
// goal here is "does the registration graph wire up + does StubBridge.call
// resolve" — not transport conformance.

import { loadConfig } from "../src/config.js";
import { registerTools } from "../src/server.js";

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

async function main(): Promise<void> {
  const config = loadConfig();
  const mock = new MockMcpServer();
  // The McpServer type is structurally compatible enough for the .registerTool
  // calls in our tool modules; cast at the boundary.
  registerTools(mock as unknown as Parameters<typeof registerTools>[0], config);

  const names = [...mock.tools.keys()];
  process.stdout.write(`registered ${names.length} tools: ${names.join(", ")}\n`);

  const ping = mock.tools.get("ping");
  if (!ping) throw new Error("ping tool was not registered");

  const result = await ping.handler({}, {});
  process.stdout.write(`ping result: ${JSON.stringify(result)}\n`);

  // Result shape from MCP convention: { content: [{ type: "text", text: "<json>" }] }
  const resultObj = result as { content?: Array<{ text?: string }> };
  const text = resultObj.content?.[0]?.text;
  if (!text) throw new Error("ping handler returned no text content");

  const parsed = JSON.parse(text) as { pong?: boolean; ts?: number };
  if (parsed.pong !== true) {
    throw new Error(`expected pong: true, got ${JSON.stringify(parsed)}`);
  }
  process.stdout.write(`OK pong: true (ts=${parsed.ts})\n`);
}

main().catch((err) => {
  process.stderr.write(`smoke FAILED: ${err instanceof Error ? err.stack ?? err.message : String(err)}\n`);
  process.exit(1);
});
