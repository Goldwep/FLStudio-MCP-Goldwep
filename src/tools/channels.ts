import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

export function registerChannelsTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "channels_count",
    {
      description:
        "Return the number of channels in the current Channel Rack group (group-respecting count; not the global count).",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("channels.channelCount")),
  );

  server.registerTool(
    "channel_get_name",
    {
      description: "Get the display name of a channel rack channel.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
      },
    },
    async ({ index }) =>
      jsonResult(await bridge.call("channels.getChannelName", { index })),
  );

  server.registerTool(
    "channel_get_color",
    {
      description:
        "Get the channel color as a packed 32-bit integer (BGRA little-endian: blue in the low byte, then green, then red, then alpha).",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
      },
    },
    async ({ index }) =>
      jsonResult(await bridge.call("channels.getChannelColor", { index })),
  );

  server.registerTool(
    "channel_get_volume",
    {
      description:
        "Get the channel's normalized volume in the range [0.0, 1.0]. Default channel volume is 1000/1280 (~0.781).",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
      },
    },
    async ({ index }) =>
      jsonResult(await bridge.call("channels.getChannelVolume", { index })),
  );

  server.registerTool(
    "channel_get_pan",
    {
      description:
        "Get the channel pan in the range [-1.0, +1.0] (negative = left, positive = right).",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
      },
    },
    async ({ index }) =>
      jsonResult(await bridge.call("channels.getChannelPan", { index })),
  );

  server.registerTool(
    "channel_get_target_fx_track",
    {
      description:
        "Get the mixer track index this channel routes to (0 = Master).",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
      },
    },
    async ({ index }) =>
      jsonResult(await bridge.call("channels.getTargetFxTrack", { index })),
  );

  server.registerTool(
    "channel_get_type",
    {
      description:
        "Get the channel type as a CT_* enum int (per midi.py:679-684): 0=Sampler, 1=Hybrid, 2=Generator (CT_GenPlug — VST/native plugin instrument), 3=Layer, 4=Audio clip, 5=Automation clip. (midi.py:555-560 also defines an older table where 1=TS404 — superseded.)",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
      },
    },
    async ({ index }) =>
      jsonResult(await bridge.call("channels.getChannelType", { index })),
  );

  server.registerTool(
    "channel_set_name",
    {
      description: "Set the display name of a channel rack channel.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        name: z.string().min(1).max(64).describe("New channel name (1-64 chars)"),
      },
    },
    async ({ index, name }) =>
      jsonResult(await bridge.call("channels.setChannelName", { index, name })),
  );

  server.registerTool(
    "channel_set_volume",
    {
      description:
        "Set the channel's normalized volume in the range [0.0, 1.0]. Default channel volume is 1000/1280 (~0.781).",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        value: z.number().min(0).max(1).describe("Normalized volume [0.0, 1.0]"),
      },
    },
    async ({ index, value }) =>
      jsonResult(await bridge.call("channels.setChannelVolume", { index, value })),
  );

  server.registerTool(
    "channel_set_pan",
    {
      description:
        "Set the channel pan in the range [-1.0, +1.0] (negative = left, positive = right).",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        value: z.number().min(-1).max(1).describe("Pan [-1.0, +1.0]; negative=left, positive=right"),
      },
    },
    async ({ index, value }) =>
      jsonResult(await bridge.call("channels.setChannelPan", { index, value })),
  );

  server.registerTool(
    "channel_set_color",
    {
      description:
        "Set the channel color as a packed 32-bit integer (BGRA little-endian: blue in the low byte, then green, then red, then alpha).",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        color: z
          .number()
          .int()
          .describe("32-bit BGRA little-endian (blue low byte, then green, then red, then alpha)"),
      },
    },
    async ({ index, color }) =>
      jsonResult(await bridge.call("channels.setChannelColor", { index, color })),
  );

  server.registerTool(
    "channel_set_target_fx_track",
    {
      description:
        "Route this channel to a mixer track. 0 = Master, >=1 = numbered mixer track.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        fxIndex: z
          .number()
          .int()
          .min(-2)
          .describe("Mixer track index; -2 = none, -1 = current, 0 = Master, >=1 = mixer track"),
      },
    },
    async ({ index, fxIndex }) =>
      jsonResult(await bridge.call("channels.setTargetFxTrack", { index, fxIndex })),
  );

  server.registerTool(
    "channel_select",
    {
      description: "Select, deselect, or toggle selection on a channel rack channel.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        value: z
          .number()
          .int()
          .min(-1)
          .max(1)
          .default(-1)
          .describe("-1 = toggle (default), 0 = off, 1 = on"),
      },
    },
    async ({ index, value }) =>
      jsonResult(await bridge.call("channels.selectChannel", { index, value })),
  );

  server.registerTool(
    "channel_mute",
    {
      description: "Mute, unmute, or toggle mute on a channel rack channel.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        value: z
          .number()
          .int()
          .min(-1)
          .max(1)
          .default(-1)
          .describe("-1 = toggle (default), 0 = off, 1 = on"),
      },
    },
    async ({ index, value }) =>
      jsonResult(await bridge.call("channels.muteChannel", { index, value })),
  );

  server.registerTool(
    "channel_solo",
    {
      description: "Toggle solo on a channel rack channel.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
      },
    },
    async ({ index }) =>
      jsonResult(await bridge.call("channels.soloChannel", { index })),
  );
}
