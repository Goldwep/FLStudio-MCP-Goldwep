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
    "mixer_arm_track",
    {
      description: "Arm or disarm a mixer track for recording. Bridge translates to mixer.armTrack(index).",
      inputSchema: {
        index: trackIndex,
      },
    },
    async ({ index }) => jsonResult(await bridge.call("mixer.armTrack", { index })),
  );

  server.registerTool(
    "mixer_link_channel_to_track",
    {
      description:
        "Route a channel-rack channel to a mixer track (direct alternative to channel_set_target_fx_track). Bridge translates to mixer.linkChannelToTrack(channel, track, select).",
      inputSchema: {
        channel: z.number().int().min(0).describe("Channel rack index (0-based)"),
        track: z.number().int().min(0).describe("Mixer track index (0=Master)"),
        select: z
          .number()
          .int()
          .min(0)
          .max(1)
          .default(0)
          .describe("Select the channel after routing (0/1)"),
      },
    },
    async ({ channel, track, select }) =>
      jsonResult(await bridge.call("mixer.linkChannelToTrack", { channel, track, select })),
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
      description:
        "Set the absolute send level from source to destination mixer track. Uses mixer.setRouteToLevel (direct setter, 0..1 float). For automatable knob-style sends use a future automate-send tool with REC plumbing.",
      inputSchema: {
        source: z.number().int().min(0).describe("Source mixer track"),
        dest: z.number().int().min(0).describe("Destination mixer track"),
        level: z.number().min(0).max(1).describe("Send level (0.0 = silent, 1.0 = unity)"),
      },
    },
    async ({ source, dest, level }) =>
      jsonResult(await bridge.call("mixer.setRouteToLevel", { source, dest, level })),
  );

  server.registerTool(
    "mixer_set_eq_gain",
    {
      description:
        "Set the EQ gain for a mixer track band using the direct setter mixer.setEqGain(index, band, value). The built-in strip EQ has 3 visible bands (0=low, 1=mid, 2=high); the underlying REC space allots 8 but only the first 3 affect the visible strip.",
      inputSchema: {
        index: z.number().int().min(0).describe("Mixer track index"),
        band: z
          .number()
          .int()
          .min(0)
          .max(2)
          .describe("EQ band: 0=low, 1=mid, 2=high"),
        value: z.number().min(0).max(1).describe("Normalized gain (0..1)"),
      },
    },
    async ({ index, band, value }) =>
      jsonResult(await bridge.call("mixer.setEqGain", { index, band, value })),
  );

  server.registerTool(
    "mixer_set_eq_freq",
    {
      description:
        "Set the EQ frequency for a mixer track band using the direct setter mixer.setEqFrequency(index, band, value).",
      inputSchema: {
        index: z.number().int().min(0).describe("Mixer track index"),
        band: z
          .number()
          .int()
          .min(0)
          .max(2)
          .describe("EQ band: 0=low, 1=mid, 2=high"),
        value: z.number().min(0).max(1).describe("Normalized frequency (0..1)"),
      },
    },
    async ({ index, band, value }) =>
      jsonResult(await bridge.call("mixer.setEqFrequency", { index, band, value })),
  );
}
