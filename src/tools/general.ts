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
    async () => jsonResult(await bridge.call("general.getProjectTitle")),
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

  server.registerTool(
    "general_save_project",
    {
      description:
        "Save the current FL Studio project. Bridge-side composite: translates to vendor-confirmed transport.globalTransport(midi.FPT_Save, 1, pmeFlags) — pattern from KLEss3Process.py:660 (FPT_Save=92 per midi.py:411). Use general_get_changed_flag first to check whether a save is needed.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("general.saveProject")),
  );

  server.registerTool(
    "general_get_changed_flag",
    {
      description:
        "Return the FL Studio project's changed-since-save flag. 0 = no changes, 1 = changes, 2 = first save needed (untitled). Useful as a guard for general_save_project.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("general.getChangedFlag")),
  );
}
