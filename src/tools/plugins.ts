import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

// Dual addressing model for the FL `plugins` module:
//   slotIndex === -1  -> `index` is a channel-rack channel; targets the
//                        generator/instrument plugin on that channel.
//   slotIndex >=  0   -> `index` is a mixer track; `slotIndex` is the
//                        effect slot on that track (stock FL exposes 0..9).
// Passing slotIndex=0 against an instrument silently misaddresses to mixer
// track `index` slot 0 — callers must use -1 explicitly for channel-rack
// instruments. See _scratch/flstudio-mcp-research/06-plugins.md gotcha #4.

const indexSchema = z
  .number()
  .int()
  .min(0)
  .describe("Channel rack index (when slotIndex=-1) or mixer track index (when slotIndex>=0)");

const slotIndexSchema = z
  .number()
  .int()
  .describe("-1 = channel-rack instrument; 0..N = mixer effect slot");

const paramIndexSchema = z.number().int().min(0).describe("Plugin parameter index (0-based)");

export function registerPluginsTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "plugins_get_name",
    {
      description:
        "Get a plugin's display name. Dual addressing: slotIndex=-1 targets the channel-rack instrument at channel `index`; slotIndex>=0 targets the effect at mixer track `index`, slot `slotIndex`.",
      inputSchema: {
        index: indexSchema,
        slotIndex: slotIndexSchema,
      },
    },
    async ({ index, slotIndex }) =>
      jsonResult(await bridge.call("plugins.getPluginName", { index, slotIndex })),
  );

  server.registerTool(
    "plugins_get_param_count",
    {
      description:
        "Get total parameter count for a plugin. Dual addressing: slotIndex=-1 targets the channel-rack instrument at channel `index`; slotIndex>=0 targets the effect at mixer track `index`, slot `slotIndex`. Note: count includes NKS metadata params at strides of 2048 for NI Komplete Kontrol plugins.",
      inputSchema: {
        index: indexSchema,
        slotIndex: slotIndexSchema,
      },
    },
    async ({ index, slotIndex }) =>
      jsonResult(await bridge.call("plugins.getParamCount", { index, slotIndex })),
  );

  server.registerTool(
    "plugins_get_param_name",
    {
      description:
        "Get the name of a single parameter on a plugin. Dual addressing: slotIndex=-1 targets the channel-rack instrument at channel `index`; slotIndex>=0 targets the effect at mixer track `index`, slot `slotIndex`. paramIndex is 0-based and is the first positional arg on the underlying FL API.",
      inputSchema: {
        paramIndex: paramIndexSchema,
        index: indexSchema,
        slotIndex: slotIndexSchema,
      },
    },
    async ({ paramIndex, index, slotIndex }) =>
      jsonResult(
        await bridge.call("plugins.getParamName", {
          paramIndex,
          index,
          slotIndex,
        }),
      ),
  );

  server.registerTool(
    "plugins_get_param_value",
    {
      description:
        "Get a plugin parameter's normalized value (float 0.0..1.0). Dual addressing: slotIndex=-1 targets the channel-rack instrument at channel `index`; slotIndex>=0 targets the effect at mixer track `index`, slot `slotIndex`. Despite docs claiming int return, the value is a normalized float per vendor-script usage.",
      inputSchema: {
        paramIndex: paramIndexSchema,
        index: indexSchema,
        slotIndex: slotIndexSchema,
      },
    },
    async ({ paramIndex, index, slotIndex }) =>
      jsonResult(
        await bridge.call("plugins.getParamValue", {
          paramIndex,
          index,
          slotIndex,
        }),
      ),
  );

  server.registerTool(
    "plugins_set_param",
    {
      description:
        "Set a plugin parameter's normalized value (float 0.0..1.0). Dual addressing: slotIndex=-1 targets the channel-rack instrument at channel `index`; slotIndex>=0 targets the effect at mixer track `index`, slot `slotIndex`. Full FL signature: setParamValue(value, paramIndex, index, slotIndex=-1, pickupMode=PIM_None, useGlobalIndex=False). PickupMode controls hardware-fader pickup semantics (0=None, 1=Pickup, 2=FollowGlobal); useGlobalIndex toggles channel-rack addressing between group-relative and project-global. Out-of-range value handling is the plugin's responsibility — FL does not clamp universally.",
      inputSchema: {
        value: z
          .number()
          .min(0)
          .max(1)
          .describe("Normalized 0..1 (docs say int but actual is float per research)"),
        paramIndex: paramIndexSchema,
        index: indexSchema,
        slotIndex: slotIndexSchema,
        pickupMode: z
          .number()
          .int()
          .min(0)
          .max(2)
          .default(0)
          .describe(
            "PIM_* pickup mode: 0=None (default), 1=Pickup, 2=FollowGlobal. KL3Plugin.py uses 2 for fader writes; default 0 is safest for MCP scripted writes.",
          ),
        useGlobalIndex: z
          .boolean()
          .default(false)
          .describe(
            "If true, treat `index` as a project-global channel index (API v26+). Default false uses group-relative addressing — match this to your channels_count call's frame of reference.",
          ),
      },
    },
    async ({ value, paramIndex, index, slotIndex, pickupMode, useGlobalIndex }) =>
      jsonResult(
        await bridge.call("plugins.setParamValue", {
          value,
          paramIndex,
          index,
          slotIndex,
          pickupMode,
          useGlobalIndex,
        }),
      ),
  );

  // Vendor-confirmed preset stepping uses two distinct FL API calls:
  //   plugins.nextPreset(channel)  — heavy use in Arturia/Novation/NI scripts
  //   plugins.prevPreset(channel)  — same
  // There is no FL API for "change preset by index" or a generic "changePreset"
  // method. The previous combined `plugins_change_preset` was a bridge-side
  // invention; replacing it with two thin tools that map 1:1 to vendor calls.
  server.registerTool(
    "plugins_next_preset",
    {
      description:
        "Step the plugin's preset forward by one. Dual addressing: slotIndex=-1 targets the channel-rack instrument at channel `index`; slotIndex>=0 targets the effect at mixer track `index`, slot `slotIndex`. Third-party VSTs may no-op if their wrapper does not expose preset banks (Arturia gates this on a known-controllable plugin list).",
      inputSchema: {
        index: indexSchema,
        slotIndex: slotIndexSchema,
      },
    },
    async ({ index, slotIndex }) =>
      jsonResult(
        await bridge.call("plugins.nextPreset", {
          index,
          slotIndex,
        }),
      ),
  );

  server.registerTool(
    "plugins_prev_preset",
    {
      description:
        "Step the plugin's preset backward by one. Same addressing + plugin-coverage caveats as plugins_next_preset.",
      inputSchema: {
        index: indexSchema,
        slotIndex: slotIndexSchema,
      },
    },
    async ({ index, slotIndex }) =>
      jsonResult(
        await bridge.call("plugins.prevPreset", {
          index,
          slotIndex,
        }),
      ),
  );
}
