import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

export function registerGeneralTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "general_get_project_title",
    {
      description: "Return the title of the currently open FL Studio project.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("general.getCurrentProjectTitle")),
  );
}
