import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

export function registerArrangementTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "arrangement_current_time",
    {
      description:
        "[UNVERIFIED — manual-only] Get the current arrangement playhead time. `arrangement.currentTime(snap)` is documented but no vendor script calls it; vendor pattern uses the sibling `arrangement.currentTimeHint(mode)` (Novation\\script\\fl.py:505). `snap` is a snap-mode flag (0 = no snap, non-zero = snap to grid), NOT a SONGLENGTH unit. For unit-controlled time, use `transport_get_song_pos` instead.",
      inputSchema: {
        snap: z
          .number()
          .int()
          .min(0)
          .default(0)
          .describe("Snap mode flag (0 = no snap; non-zero = snap to grid)"),
      },
    },
    async ({ snap }) => jsonResult(await bridge.call("arrangement.currentTime", { snap })),
  );
}
