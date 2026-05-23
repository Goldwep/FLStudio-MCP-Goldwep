import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

export function registerUiTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "ui_get_visible",
    {
      description:
        "Return whether the FL Studio window identified by `widget` is currently visible (boolean). Widget IDs (widX): 0=Mixer, 1=ChannelRack, 2=Playlist, 3=PianoRoll, 4=Browser, 5=Plugin, 6=PluginEffect, 7=PluginGenerator.",
      inputSchema: {
        widget: z
          .number()
          .int()
          .min(0)
          .max(7)
          .describe("FL widget ID (0-7) - see midi.py widXxx constants"),
      },
    },
    async ({ widget }) => jsonResult(await bridge.call("ui.getVisible", { widget })),
  );

  server.registerTool(
    "ui_get_focused_form_id",
    {
      description:
        "Return the FL form/window ID currently focused (integer). Returns -1 when no focusable form is active. Useful for discovering which plugin/editor has keyboard focus.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("ui.getFocusedFormID")),
  );
}
