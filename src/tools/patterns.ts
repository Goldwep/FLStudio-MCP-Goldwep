import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

export function registerPatternsTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "patterns_count",
    {
      description: "Return the number of patterns the user has touched in the project (occupied patterns; not the maximum index).",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("patterns.patternCount")),
  );

  server.registerTool(
    "patterns_current_number",
    {
      description:
        "Return the current PLAYBACK pattern number (the red-arrow / playback marker). NOTE: this is NOT the Picker-panel selected pattern — the two can diverge when the user clicks one pattern but plays another. Patterns are 1-indexed.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("patterns.patternNumber")),
  );

  server.registerTool(
    "patterns_get_name",
    {
      description: "Return the name of the pattern at the given index. Patterns are 1-indexed.",
      inputSchema: {
        index: z.number().int().min(1).describe("Pattern index (1-based)"),
      },
    },
    async ({ index }) => jsonResult(await bridge.call("patterns.getPatternName", { index })),
  );

  server.registerTool(
    "patterns_get_color",
    {
      description:
        "Return the color of the pattern at the given index as a signed 32-bit int encoded BGRA little-endian (NOT RGB). Decode with bytes-little-endian to recover (B, G, R, A). Patterns are 1-indexed.",
      inputSchema: {
        index: z.number().int().min(1).describe("Pattern index (1-based)"),
      },
    },
    async ({ index }) => jsonResult(await bridge.call("patterns.getPatternColor", { index })),
  );

  server.registerTool(
    "patterns_get_length",
    {
      description:
        "Return the length of the pattern at the given index as a raw integer. UNITS UNCERTAIN: the FL manual documents this as beats, but Novation's vendor script treats the return as steps. Likely depends on whether the pattern is in step-seq vs piano-roll mode. Treat as a raw value and resolve units out-of-band. Patterns are 1-indexed.",
      inputSchema: {
        index: z.number().int().min(1).describe("Pattern index (1-based)"),
      },
    },
    async ({ index }) => jsonResult(await bridge.call("patterns.getPatternLength", { index })),
  );
}
