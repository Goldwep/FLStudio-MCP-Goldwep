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

  server.registerTool(
    "general_undo",
    {
      description:
        "Undo the last action in FL Studio. Bridge-side calls general.undo() directly; FL maintains its own undo stack, so we do not call saveUndo() to checkpoint first. No args.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("general.undo")),
  );
}
