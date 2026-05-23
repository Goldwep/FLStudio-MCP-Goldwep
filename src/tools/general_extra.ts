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
        "Get the project's pulses-per-beat (PPB = timebase x numerator). Returns an integer tick count per beat. Distinct from PPQ (pulses-per-quarter-note).",
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
