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

  server.registerTool(
    "patterns_select",
    {
      description:
        "Set the Picker-panel selection state of the pattern at the given index. NOTE: this affects PICKER selection only — it does NOT move the playback marker (red arrow). Use patterns_jump_to to set the playback pattern. The two concepts can diverge when the user clicks one pattern but plays another. Patterns are 1-indexed.",
      inputSchema: {
        index: z.number().int().min(1).describe("Pattern index (1-based)"),
        value: z.number().int().min(-1).max(1).default(-1).describe("-1=toggle, 0=deselect, 1=select"),
        preview: z.number().int().min(0).max(1).default(0).describe("If 1, preview the pattern audibly when selecting"),
      },
    },
    async ({ index, value, preview }) =>
      jsonResult(await bridge.call("patterns.selectPattern", { index, value, preview })),
  );

  server.registerTool(
    "patterns_jump_to",
    {
      description:
        "Move the PLAYBACK marker (red arrow) to the pattern at the given index. Distinct from patterns_select, which only affects Picker-panel selection. jumpToPattern aligns both the playback marker and the picker. Patterns are 1-indexed.",
      inputSchema: {
        index: z.number().int().min(1).describe("Pattern index (1-based)"),
      },
    },
    async ({ index }) => jsonResult(await bridge.call("patterns.jumpToPattern", { index })),
  );

  server.registerTool(
    "patterns_set_name",
    {
      description: "Set the name of the pattern at the given index. Patterns are 1-indexed.",
      inputSchema: {
        index: z.number().int().min(1).describe("Pattern index (1-based)"),
        name: z.string().min(1).max(64).describe("New pattern name (1-64 chars)"),
      },
    },
    async ({ index, name }) => jsonResult(await bridge.call("patterns.setPatternName", { index, name })),
  );

  server.registerTool(
    "patterns_set_color",
    {
      description:
        "Set the color of the pattern at the given index. Color is a signed 32-bit int encoded BGRA little-endian (NOT RGB) — matches the read-side encoding from patterns_get_color. Patterns are 1-indexed.",
      inputSchema: {
        index: z.number().int().min(1).describe("Pattern index (1-based)"),
        color: z.number().int().describe("32-bit BGRA little-endian"),
      },
    },
    async ({ index, color }) => jsonResult(await bridge.call("patterns.setPatternColor", { index, color })),
  );
}
