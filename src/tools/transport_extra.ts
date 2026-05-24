import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

export function registerTransportExtraTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "transport_get_song_pos",
    {
      description:
        "Get the current song position in the unit specified by `unit` (SONGLENGTH_* enum). Returns a float; numeric scale depends on `unit` (e.g. ms for 0, seconds for 1, absolute ticks for 2).",
      inputSchema: {
        unit: z
          .number()
          .int()
          .min(0)
          .max(5)
          .default(0)
          .describe("SONGLENGTH unit: 0=MS, 1=Sec, 2=AbsTicks, 3=Bars, 4=Steps, 5=Ticks"),
      },
    },
    async ({ unit }) => jsonResult(await bridge.call("transport.getSongPos", { unit })),
  );

  server.registerTool(
    "transport_get_song_length",
    {
      description:
        "[UNVERIFIED] Get the total song length in the unit specified by `unit` (SONGLENGTH_* enum). Returns a float in the requested unit. transport.getSongLength is documented but has zero vendor-script usage — pair-tool transport_get_song_pos IS vendor-confirmed.",
      inputSchema: {
        unit: z
          .number()
          .int()
          .min(0)
          .max(5)
          .default(0)
          .describe("SONGLENGTH unit: 0=MS, 1=Sec, 2=AbsTicks, 3=Bars, 4=Steps, 5=Ticks"),
      },
    },
    async ({ unit }) => jsonResult(await bridge.call("transport.getSongLength", { unit })),
  );
}
