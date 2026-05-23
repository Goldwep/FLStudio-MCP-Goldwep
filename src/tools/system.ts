import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

// Bridge result is always JSON-serializable; surface it as a single text
// content block so MCP clients can parse it back into a structure.
function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

export function registerSystemTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "ping",
    {
      description:
        "Round-trip the bridge to confirm wiring. Returns { pong: true, ts: <epoch ms> }.",
      inputSchema: {},
    },
    async () => {
      const result = await bridge.call("ping");
      return jsonResult(result);
    },
  );
}
