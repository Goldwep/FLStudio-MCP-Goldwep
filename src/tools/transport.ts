import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

export function registerTransportTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "transport_play",
    {
      description: "Start FL Studio transport playback.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("transport.start")),
  );

  server.registerTool(
    "transport_stop",
    {
      description: "Stop FL Studio transport playback.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("transport.stop")),
  );

  server.registerTool(
    "transport_is_playing",
    {
      description: "Query whether FL Studio transport is currently playing.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("transport.isPlaying")),
  );
}
