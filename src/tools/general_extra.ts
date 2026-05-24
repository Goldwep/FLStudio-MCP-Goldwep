import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

export function registerGeneralExtraTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "general_get_rec_ppb",
    {
      description:
        "[UNVERIFIED — manual-only] Get the project's pulses-per-beat (PPB = timebase x numerator). general.getRecPPB is documented but vendor scripts uniformly use the sibling general.getRecPPQ instead. May not be present in current FL builds; consider getRecPPQ as a fallback.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("general.getRecPPB")),
  );

  server.registerTool(
    "general_get_use_metronome",
    {
      description:
        "Return whether the FL Studio metronome is currently enabled (boolean). Note: ui.isMetronomeEnabled() exposes the same state via the UI module.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("general.getUseMetronome")),
  );
}
