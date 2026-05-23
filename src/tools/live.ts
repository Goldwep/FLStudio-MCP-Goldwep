import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

// L8a — live composition (real-time note dispatch, record arm, state polling).
// state_subscribe / streaming state_sync is L8b, deferred until a bidirectional
// bridge transport lands. These six tools are sufficient for an LLM to play
// FL Studio "live": arm record, fire notes/chords, stream melodies, and poll
// the record-arm guard before destructive sequences.

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

const channelIndexSchema = z
  .number()
  .int()
  .min(0)
  .describe("Channel rack index (0-based)");

const noteSchema = z
  .number()
  .int()
  .min(0)
  .max(127)
  .describe("MIDI note 0..127 (60=C4)");

const velocitySchema = z
  .number()
  .int()
  .min(0)
  .max(127)
  .describe("MIDI velocity (0=note-off, 1..127=note-on intensity)");

const midiChannelSchema = z
  .number()
  .int()
  .min(-1)
  .max(15)
  .default(-1)
  .describe("MIDI channel 0..15; -1 = global (channels.midiNoteOn convention)");

export function registerLiveTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "live_arm_record",
    {
      description:
        "Toggle FL Studio's record arm. Idempotent if FL is already armed (same toggle as transport_record). Pair with transport_play to begin actually recording.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("transport.record")),
  );

  server.registerTool(
    "live_get_record_state",
    {
      description:
        "Query whether FL Studio is currently armed/recording. Returns truthy when armed. Useful as a guard before issuing live_play_* or live_stream_notes if the caller cares whether notes will be captured.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("transport.isRecording")),
  );

  server.registerTool(
    "live_play_note_now",
    {
      description:
        "Trigger a single MIDI note on a channel rack channel. If FL is armed AND transport is playing, FL records the note; otherwise it plays as audible preview. Velocity 0 acts as note-off; prefer live_release_note for explicit note-off semantics.",
      inputSchema: {
        channel_index: channelIndexSchema,
        note: noteSchema,
        velocity: velocitySchema,
        midi_channel: midiChannelSchema,
      },
    },
    async ({ channel_index, note, velocity, midi_channel }) =>
      jsonResult(
        await bridge.call("channels.midiNoteOn", {
          channel_index,
          note,
          velocity,
          midi_channel,
        }),
      ),
  );

  server.registerTool(
    "live_release_note",
    {
      description:
        "Explicitly release a held MIDI note (velocity=0 note-off convention). Use after live_play_note_now if you held a note open and need to end it cleanly.",
      inputSchema: {
        channel_index: channelIndexSchema,
        note: noteSchema,
        midi_channel: midiChannelSchema,
      },
    },
    async ({ channel_index, note, midi_channel }) =>
      jsonResult(
        await bridge.call("channels.midiNoteOn", {
          channel_index,
          note,
          velocity: 0,
          midi_channel,
        }),
      ),
  );

  server.registerTool(
    "live_play_chord_now",
    {
      description:
        "Trigger up to 16 simultaneous notes on a single channel (server-side composite — multiple midiNoteOn calls fired in order). Same record/preview semantics as live_play_note_now.",
      inputSchema: {
        channel_index: channelIndexSchema,
        notes: z
          .array(z.number().int().min(0).max(127))
          .min(1)
          .max(16)
          .describe("Up to 16 simultaneous notes"),
        velocity: velocitySchema,
        midi_channel: midiChannelSchema,
      },
    },
    async ({ channel_index, notes, velocity, midi_channel }) => {
      for (const n of notes) {
        await bridge.call("channels.midiNoteOn", {
          channel_index,
          note: n,
          velocity,
          midi_channel,
        });
      }
      return jsonResult({ ok: true, played: notes.length });
    },
  );

  server.registerTool(
    "live_stream_notes",
    {
      description:
        "Stream a melody as a sequence of {note, velocity, hold_ms}. Each item fires note-on, sleeps hold_ms, then note-off before the next item — i.e. monophonic by default. Timing is BEST-EFFORT: the bridge has no precision scheduler, so hold_ms is a setTimeout delay subject to event-loop jitter and bridge round-trip latency. Up to 256 steps per call.",
      inputSchema: {
        channel_index: channelIndexSchema,
        sequence: z
          .array(
            z.object({
              note: z.number().int().min(0).max(127),
              velocity: z.number().int().min(0).max(127),
              hold_ms: z.number().int().min(0).max(10000),
            }),
          )
          .min(1)
          .max(256)
          .describe(
            "Note sequence with per-note hold duration (best-effort timing)",
          ),
        midi_channel: midiChannelSchema,
      },
    },
    async ({ channel_index, sequence, midi_channel }) => {
      for (const item of sequence) {
        await bridge.call("channels.midiNoteOn", {
          channel_index,
          note: item.note,
          velocity: item.velocity,
          midi_channel,
        });
        await new Promise((r) => setTimeout(r, item.hold_ms));
        await bridge.call("channels.midiNoteOn", {
          channel_index,
          note: item.note,
          velocity: 0,
          midi_channel,
        });
      }
      return jsonResult({ ok: true, played: sequence.length });
    },
  );
}
