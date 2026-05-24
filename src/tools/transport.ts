import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

export function registerTransportTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "transport_play",
    {
      description: "Start FL Studio transport playback.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("transport.start")),
  );

  server.registerTool(
    "transport_stop",
    {
      description: "Stop FL Studio transport playback.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("transport.stop")),
  );

  server.registerTool(
    "transport_is_playing",
    {
      description: "Query whether FL Studio transport is currently playing.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("transport.isPlaying")),
  );

  server.registerTool(
    "transport_set_tempo",
    {
      description:
        "[UNVERIFIED — pending probe] Set the FL Studio project tempo in BPM. Uses mixer.setCurrentTempo, which is listed in the online manual but has ZERO precedent in any of the 14 bundled vendor controller scripts. Vendor pattern for tempo is encoder-delta via REC_Tempo (general.processRECEvent), not an absolute setter. May AttributeError when the bridge lands until probe confirms the absolute setter exists.",
      inputSchema: {
        bpm: z.number().min(10).max(999).describe("Tempo in BPM (absolute value)."),
      },
    },
    async ({ bpm }) => jsonResult(await bridge.call("mixer.setCurrentTempo", { bpm })),
  );

  server.registerTool(
    "transport_toggle_metronome",
    {
      description:
        "Toggle the FL Studio metronome on/off. Bridge-side composite: translates to vendor-confirmed transport.globalTransport(midi.FPT_Metronome, 1, pmeFlags) — pattern from device_Fire.py:1893, KLEss3Process.py:536, device_SSL.py:430. No args.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("transport.toggleMetronome")),
  );

  server.registerTool(
    "transport_tap_tempo",
    {
      description:
        "Send a tap-tempo pulse. Repeated calls converge FL on the tapped tempo. Bridge-side composite: translates to vendor-confirmed transport.globalTransport(midi.FPT_TapTempo, 1, pmeFlags) — pattern from device_Fire.py:1966, KeyLabEssProcess.py:448. No args.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("transport.tapTempo")),
  );

  server.registerTool(
    "transport_record",
    {
      description:
        "Toggle FL Studio record arm. Used to start AND stop arm (same toggle). Pair with transport_play to begin recording.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("transport.record")),
  );

  server.registerTool(
    "transport_set_loop_mode",
    {
      description:
        "TOGGLE the FL Studio transport loop mode (Song <-> Pattern). This is a toggle — calling it flips the current mode; there is no explicit on/off argument. No args.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("transport.setLoopMode")),
  );

  server.registerTool(
    "transport_set_song_pos",
    {
      description:
        "Set the current song position. `position` is interpreted in the unit given by `mode` (SONGLENGTH_* enum). Default mode is 2 (AbsTicks).",
      inputSchema: {
        position: z
          .number()
          .int()
          .min(0)
          .describe("Target song position in the unit specified by `mode`."),
        mode: z
          .number()
          .int()
          .min(0)
          .max(5)
          .default(2)
          .describe("SONGLENGTH unit: 0=MS, 1=Sec, 2=AbsTicks (default), 3=Bars, 4=Steps, 5=Ticks"),
      },
    },
    async ({ position, mode }) =>
      jsonResult(await bridge.call("transport.setSongPos", { position, mode })),
  );
}
