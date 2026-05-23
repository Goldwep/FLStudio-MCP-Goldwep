import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

export function registerChannelsStepsTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "channel_get_step_bit",
    {
      description:
        "Read a single step-sequencer grid bit. Returns 1 if the step is on, 0 if off. Step-seq channels only — non-step channels (audio clips, automation, some generators) will return junk; gate with channels.isGridBitAssigned upstream when in doubt.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        position: z
          .number()
          .int()
          .min(0)
          .max(255)
          .describe("Step position (0-based) within the pattern; FL supports up to 256 steps"),
      },
    },
    async ({ index, position }) =>
      jsonResult(await bridge.call("channels.getGridBit", { index, position })),
  );

  server.registerTool(
    "channel_set_step_bit",
    {
      description:
        "Write a single step-sequencer grid bit. value=1 turns the step on, value=0 turns it off. Step-seq channels only.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        position: z
          .number()
          .int()
          .min(0)
          .max(255)
          .describe("Step position (0-based) within the pattern; FL supports up to 256 steps"),
        value: z.number().int().min(0).max(1).describe("0 = step off, 1 = step on"),
      },
    },
    async ({ index, position, value }) =>
      jsonResult(await bridge.call("channels.setGridBit", { index, position, value })),
  );

  server.registerTool(
    "channel_toggle_step",
    {
      description:
        "Toggle a single step-sequencer grid bit. Server-side composite: reads the current bit via channels.getGridBit, then writes the inverse via channels.setGridBit. Returns the bridge response from the write.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        position: z
          .number()
          .int()
          .min(0)
          .max(255)
          .describe("Step position (0-based) within the pattern; FL supports up to 256 steps"),
      },
    },
    async ({ index, position }) => {
      const current = await bridge.call("channels.getGridBit", { index, position });
      const next = current ? 0 : 1;
      return jsonResult(await bridge.call("channels.setGridBit", { index, position, value: next }));
    },
  );

  server.registerTool(
    "channel_get_step_param",
    {
      description:
        "Read a per-step parameter (pitch, velocity, pan, mod, etc.) from the CURRENT pattern's step grid. Wraps channels.getCurrentStepParam.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        step: z
          .number()
          .int()
          .min(0)
          .max(255)
          .describe("Step position (0-based) within the pattern; FL supports up to 256 steps"),
        param: z
          .number()
          .int()
          .min(0)
          .max(7)
          .describe(
            "Step parameter index: 0=Pitch, 1=Velocity, 2=Release, 3=Fine, 4=Pan, 5=ModX, 6=ModY, 7=Shift — see midi.py",
          ),
      },
    },
    async ({ index, step, param }) =>
      jsonResult(await bridge.call("channels.getCurrentStepParam", { index, step, param })),
  );

  server.registerTool(
    "channel_set_step_param",
    {
      description:
        "Write a per-step parameter (pitch, velocity, pan, mod, etc.) on a step in the given pattern. SILENT NO-OP IF STEP BIT=0: setStepParameterByIndex does nothing on a step that is off. This tool force-sets the bit to 1 first via channels.setGridBit, then calls channels.setStepParameterByIndex. Returns the bridge response from the param write.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        pattern: z.number().int().min(1).describe("Pattern index (1-based)"),
        step: z
          .number()
          .int()
          .min(0)
          .max(255)
          .describe("Step position (0-based) within the pattern; FL supports up to 256 steps"),
        param: z
          .number()
          .int()
          .min(0)
          .max(7)
          .describe(
            "Step parameter index: 0=Pitch, 1=Velocity, 2=Release, 3=Fine, 4=Pan, 5=ModX, 6=ModY, 7=Shift — see midi.py",
          ),
        value: z
          .number()
          .describe("Param value range depends on which step param — typically 0..1 normalized"),
      },
    },
    async ({ index, pattern, step, param, value }) => {
      await bridge.call("channels.setGridBit", { index, position: step, value: 1 });
      return jsonResult(
        await bridge.call("channels.setStepParameterByIndex", { index, pattern, step, param, value }),
      );
    },
  );

  server.registerTool(
    "channel_clear_pattern_steps",
    {
      description:
        "Clear the first N step-sequencer grid bits on a channel by writing 0 to positions 0..length-1. Composite: loops channels.setGridBit. Returns { ok: true, count } on success or throws on first error.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        length: z
          .number()
          .int()
          .min(1)
          .max(256)
          .default(16)
          .describe("How many step positions to clear, starting from 0 (default 16)"),
      },
    },
    async ({ index, length }) => {
      for (let position = 0; position < length; position++) {
        await bridge.call("channels.setGridBit", { index, position, value: 0 });
      }
      return jsonResult({ ok: true, count: length });
    },
  );

  server.registerTool(
    "channel_set_step_row",
    {
      description:
        "Write a full step row in one tool call. `bits` is an array of booleans (true=on, false=off); position p gets bits[p]. Composite: loops channels.setGridBit. High-leverage LLM tool — build a 16-step drum row in one call. Returns { ok: true, count } on success or throws on first error.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        bits: z
          .array(z.boolean())
          .min(1)
          .max(256)
          .describe("Sequence of step on/off booleans, position 0..N-1"),
      },
    },
    async ({ index, bits }) => {
      for (let position = 0; position < bits.length; position++) {
        const value = bits[position] ? 1 : 0;
        await bridge.call("channels.setGridBit", { index, position, value });
      }
      return jsonResult({ ok: true, count: bits.length });
    },
  );

  server.registerTool(
    "pattern_set_length",
    {
      description:
        "Set the length of a pattern. UNITS UNCERTAIN: the FL manual documents pattern length as beats, but Novation's vendor script treats it as steps; resolution likely depends on pattern mode. Raw value is passed through to patterns.setPatternLength. Patterns are 1-indexed.",
      inputSchema: {
        index: z.number().int().min(1).describe("Pattern index (1-based)"),
        length: z
          .number()
          .int()
          .min(1)
          .describe(
            "Pattern length (units uncertain — beats per docs, steps per Novation vendor; raw value passed through)",
          ),
      },
    },
    async ({ index, length }) =>
      jsonResult(await bridge.call("patterns.setPatternLength", { index, length })),
  );

  server.registerTool(
    "channel_step_pattern_build",
    {
      description:
        "TOP composition tool: build an entire step-sequencer pattern from a JSON spec in one call. `pattern.steps[p]` toggles the grid bit at position p; if `pattern.pitches` and/or `pattern.velocities` are given, those per-step params are written too (param 0 = pitch, param 1 = velocity). Param writes only fire for positions where steps[p] is true — the underlying setStepParameterByIndex requires the bit be on. Composite: loops channels.setGridBit + channels.setStepParameterByIndex against the current pattern (patterns.patternNumber on the bridge side). Returns { ok: true, count } where count = number of step positions processed.",
      inputSchema: {
        index: z.number().int().min(0).describe("Channel rack index (0-based)"),
        pattern: z
          .object({
            steps: z.array(z.boolean()).min(1).max(256),
            pitches: z.array(z.number()).optional(),
            velocities: z.array(z.number()).optional(),
          })
          .describe(
            "Full grid spec. steps: boolean[] of on/off per position. pitches/velocities: optional same-length numeric arrays applied only where steps[p]=true.",
          ),
      },
    },
    async ({ index, pattern }) => {
      const { steps, pitches, velocities } = pattern;
      const patNum = (await bridge.call("patterns.patternNumber")) as number;
      for (let position = 0; position < steps.length; position++) {
        const on = steps[position];
        await bridge.call("channels.setGridBit", { index, position, value: on ? 1 : 0 });
        if (on) {
          if (pitches && position < pitches.length) {
            await bridge.call("channels.setStepParameterByIndex", {
              index,
              pattern: patNum,
              step: position,
              param: 0,
              value: pitches[position],
            });
          }
          if (velocities && position < velocities.length) {
            await bridge.call("channels.setStepParameterByIndex", {
              index,
              pattern: patNum,
              step: position,
              param: 1,
              value: velocities[position],
            });
          }
        }
      }
      return jsonResult({ ok: true, count: steps.length });
    },
  );
}
