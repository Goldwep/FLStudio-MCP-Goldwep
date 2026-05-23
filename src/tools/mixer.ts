import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

const trackIndex = z.number().int().min(0).describe("Mixer track index (0=Master)");

export function registerMixerTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "mixer_track_count",
    {
      description: "Get the current FL Studio mixer track count, including Master (index 0) and all insert tracks.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("mixer.trackCount")),
  );

  server.registerTool(
    "mixer_get_track_name",
    {
      description: "Get the display name of a mixer track.",
      inputSchema: { index: trackIndex },
    },
    async ({ index }) => jsonResult(await bridge.call("mixer.getTrackName", { index })),
  );

  server.registerTool(
    "mixer_get_track_color",
    {
      description: "Get the color of a mixer track as a packed integer (BGRA little-endian).",
      inputSchema: { index: trackIndex },
    },
    async ({ index }) => jsonResult(await bridge.call("mixer.getTrackColor", { index })),
  );

  server.registerTool(
    "mixer_get_track_volume",
    {
      description: "Get the volume of a mixer track. Returns a normalized float 0.0..1.0 (NOT MIDI 0..127, NOT dB).",
      inputSchema: { index: trackIndex },
    },
    async ({ index }) => jsonResult(await bridge.call("mixer.getTrackVolume", { index })),
  );

  server.registerTool(
    "mixer_get_track_pan",
    {
      description: "Get the pan of a mixer track. Returns a float in -1.0..+1.0 (-1=full left, 0=center, +1=full right).",
      inputSchema: { index: trackIndex },
    },
    async ({ index }) => jsonResult(await bridge.call("mixer.getTrackPan", { index })),
  );

  server.registerTool(
    "mixer_is_track_muted",
    {
      description: "Query whether a mixer track is muted. Returns a boolean.",
      inputSchema: { index: trackIndex },
    },
    async ({ index }) => jsonResult(await bridge.call("mixer.isTrackMuted", { index })),
  );

  server.registerTool(
    "mixer_is_track_soloed",
    {
      description: "Query whether a mixer track is soloed. Returns a boolean.",
      inputSchema: { index: trackIndex },
    },
    async ({ index }) => jsonResult(await bridge.call("mixer.isTrackSoloed", { index })),
  );

  server.registerTool(
    "mixer_get_track_peaks",
    {
      description: "Get the current peak meter value for a mixer track. Returns a float; values may exceed 1.0 (cap is ~1.1, not 1.0).",
      inputSchema: {
        index: trackIndex,
        mode: z
          .number()
          .int()
          .min(0)
          .max(2)
          .default(0)
          .describe("0=L peak, 1=R peak, 2=L+R"),
      },
    },
    async ({ index, mode }) => jsonResult(await bridge.call("mixer.getTrackPeaks", { index, mode })),
  );
}
