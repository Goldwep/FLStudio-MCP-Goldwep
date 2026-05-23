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

  server.registerTool(
    "mixer_set_track_name",
    {
      description: "Set the display name of a mixer track. Master rename may be silently rejected by FL.",
      inputSchema: { index: trackIndex, name: z.string().min(1).max(64) },
    },
    async ({ index, name }) => jsonResult(await bridge.call("mixer.setTrackName", { index, name })),
  );

  server.registerTool(
    "mixer_set_track_volume",
    {
      description: "Set the volume of a mixer track. Value is a normalized float 0.0..1.0 (NOT MIDI 0..127, NOT dB). 0.8 is approximately unity gain.",
      inputSchema: { index: trackIndex, value: z.number().min(0).max(1) },
    },
    async ({ index, value }) => jsonResult(await bridge.call("mixer.setTrackVolume", { index, value })),
  );

  server.registerTool(
    "mixer_set_track_pan",
    {
      description: "Set the pan of a mixer track. Value is a float -1.0..+1.0 (-1=full left, 0=center, +1=full right).",
      inputSchema: { index: trackIndex, value: z.number().min(-1).max(1) },
    },
    async ({ index, value }) => jsonResult(await bridge.call("mixer.setTrackPan", { index, value })),
  );

  server.registerTool(
    "mixer_set_track_color",
    {
      description: "Set the color of a mixer track. Color is a 32-bit BGRA little-endian packed integer (matches read-side mixer_get_track_color).",
      inputSchema: {
        index: trackIndex,
        color: z.number().int().describe("32-bit BGRA little-endian"),
      },
    },
    async ({ index, color }) => jsonResult(await bridge.call("mixer.setTrackColor", { index, color })),
  );

  server.registerTool(
    "mixer_mute_track",
    {
      description: "Mute, unmute, or toggle mute on a mixer track. value: -1=toggle (default), 0=unmute, 1=mute.",
      inputSchema: {
        index: trackIndex,
        value: z.number().int().min(-1).max(1).default(-1),
      },
    },
    async ({ index, value }) => jsonResult(await bridge.call("mixer.muteTrack", { index, value })),
  );

  server.registerTool(
    "mixer_solo_track",
    {
      description: "Solo, unsolo, or toggle solo on a mixer track. value: -1=toggle (default), 0=unsolo, 1=solo.",
      inputSchema: {
        index: trackIndex,
        value: z.number().int().min(-1).max(1).default(-1),
      },
    },
    async ({ index, value }) => jsonResult(await bridge.call("mixer.soloTrack", { index, value })),
  );

  server.registerTool(
    "mixer_set_route",
    {
      description: "Enable or disable a mixer routing from source track to destination track. value: 1=enable route, 0=disable route. Performs two FL calls atomically: setRouteTo then afterRoutingChanged (required — without the notify, the change silently fails to propagate).",
      inputSchema: {
        source: z.number().int().min(0).describe("Source track index"),
        dest: z.number().int().min(0).describe("Destination track index"),
        value: z.number().int().min(0).max(1).describe("1=enable, 0=disable"),
      },
    },
    async ({ source, dest, value }) => {
      await bridge.call("mixer.setRouteTo", { source, dest, value });
      return jsonResult(await bridge.call("mixer.afterRoutingChanged", {}));
    },
  );

  server.registerTool(
    "mixer_set_send_level",
    {
      description: "Set the send level from a mixer track to a destination track. Bridge composes the REC event via getTrackPluginId + REC_Mixer_Send_First + dest. Value is normalized 0..1 typically.",
      inputSchema: {
        track: z.number().int().min(0).describe("Source mixer track"),
        dest: z.number().int().min(0).describe("Destination mixer track"),
        value: z.number().describe("Normalized 0..1 typically; depends on REC encoding"),
      },
    },
    async ({ track, dest, value }) => jsonResult(await bridge.call("mixer.setSendLevel", { track, dest, value })),
  );

  server.registerTool(
    "mixer_set_eq_gain",
    {
      description: "Set the EQ gain for a mixer track band. Bridge composes via getTrackPluginId + REC_Mixer_EQ_Gain + band. The built-in strip EQ has 3 visible bands (low/mid/high); bands 3..7 likely no-op on the default strip.",
      inputSchema: {
        track: z.number().int().min(0),
        band: z
          .number()
          .int()
          .min(0)
          .max(7)
          .describe("EQ band: 0..2 = visible strip EQ (low/mid/high); 3..7 = extended (likely no-op on default strip)"),
        value: z.number().describe("Normalized 0..1 typically; depends on REC encoding"),
      },
    },
    async ({ track, band, value }) => jsonResult(await bridge.call("mixer.setEqGain", { track, band, value })),
  );

  server.registerTool(
    "mixer_set_eq_freq",
    {
      description: "Set the EQ frequency for a mixer track band. Bridge composes via getTrackPluginId + REC_Mixer_EQ_Freq + band. The built-in strip EQ has 3 visible bands (low/mid/high); bands 3..7 likely no-op on the default strip.",
      inputSchema: {
        track: z.number().int().min(0),
        band: z
          .number()
          .int()
          .min(0)
          .max(7)
          .describe("EQ band: 0..2 = visible strip EQ (low/mid/high); 3..7 = extended (likely no-op on default strip)"),
        value: z.number().describe("Normalized 0..1 typically; depends on REC encoding"),
      },
    },
    async ({ track, band, value }) => jsonResult(await bridge.call("mixer.setEqFreq", { track, band, value })),
  );
}
