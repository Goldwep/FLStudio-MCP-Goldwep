import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

import {
  generateAddNotes,
  generateClearPattern,
  generateTranspose,
  generateQuantize,
  generateVelocitySet,
} from "../pyscript/generator.js";
import {
  deployPyscript,
  listDeployedScripts,
  resolveScriptsDir,
} from "../pyscript/deployer.js";

// L6 — Piano Roll `.pyscript` dispatch (v1.0: deploy-only).
//
// Auto-trigger is deferred to v1.1 pending L0 probe data on whether
// `processRECEvent(REC_Chan_NoteOn,...)` accepts note events (which would
// collapse L6 into L5). Until then, these tools WRITE a `.pyscript` file
// into FL Studio's scripts directory; the user invokes it manually from
// the Piano Roll via Ctrl+Alt+Y or Tools > Macros.
//
// Bridge is unused here — L6 tools are pure file I/O. The signature still
// takes a Bridge to keep `registerXTools(server, bridge)` symmetric across
// every tool module.

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

const scriptNameSchema = z
  .string()
  .min(1)
  .max(64)
  .optional()
  .describe(
    "Output .pyscript filename without extension. Auto-generated if omitted.",
  );

const noteEntrySchema = z.object({
  pitch: z
    .number()
    .int()
    .min(0)
    .max(127)
    .describe("MIDI pitch 0..127 (60=C4)"),
  position: z
    .number()
    .int()
    .min(0)
    .describe("Note start in ticks (PPQ-based; FL piano-roll PPQ=96)"),
  length: z
    .number()
    .int()
    .min(1)
    .describe("Note length in ticks (PPQ=96, so 96 = quarter note)"),
  velocity: z
    .number()
    .int()
    .min(1)
    .max(127)
    .describe(
      "MIDI velocity 1..127. Generator converts to flpianoroll's 0.0..1.0 float.",
    ),
});

export function registerPianoRollTools(
  server: McpServer,
  _bridge: Bridge,
): void {
  // Suppress unused-arg lint without changing the public signature.
  void _bridge;

  server.registerTool(
    "piano_roll_deploy_add_notes",
    {
      description:
        "DEPLOYS a `.pyscript` file that adds notes to the current piano-roll pattern. You must invoke it manually from FL Studio's Piano Roll (Ctrl+Alt+Y) to apply. Notes are tuples of {pitch (MIDI 0..127), position (ticks; FL PPQ=96), length (ticks), velocity (MIDI 1..127 — generator converts to flpianoroll's 0.0..1.0 float)}. Returns the deployed file path.",
      inputSchema: {
        notes: z
          .array(noteEntrySchema)
          .min(1)
          .max(1000)
          .describe("Up to 1000 notes per dispatch."),
        script_name: scriptNameSchema,
      },
    },
    async ({ notes, script_name }) => {
      const source = generateAddNotes(notes);
      const result = await deployPyscript(source, script_name, "add_notes");
      return jsonResult(result);
    },
  );

  server.registerTool(
    "piano_roll_deploy_clear_pattern",
    {
      description:
        "DEPLOYS a `.pyscript` file that removes all notes from the current piano-roll pattern. You must invoke it manually from FL Studio's Piano Roll (Ctrl+Alt+Y) to apply. Returns the deployed file path.",
      inputSchema: {
        script_name: scriptNameSchema,
      },
    },
    async ({ script_name }) => {
      const source = generateClearPattern();
      const result = await deployPyscript(
        source,
        script_name,
        "clear_pattern",
      );
      return jsonResult(result);
    },
  );

  server.registerTool(
    "piano_roll_deploy_transpose",
    {
      description:
        "DEPLOYS a `.pyscript` file that transposes every note in the current piano-roll pattern by N semitones (negative = down). Generated script clamps each note's pitch to MIDI range 0..127. You must invoke it manually from FL Studio's Piano Roll (Ctrl+Alt+Y) to apply.",
      inputSchema: {
        semitones: z
          .number()
          .int()
          .min(-48)
          .max(48)
          .describe("Transpose offset in semitones (-48..+48). Negative = down."),
        script_name: scriptNameSchema,
      },
    },
    async ({ semitones, script_name }) => {
      const source = generateTranspose(semitones);
      const result = await deployPyscript(source, script_name, "transpose");
      return jsonResult(result);
    },
  );

  server.registerTool(
    "piano_roll_deploy_quantize",
    {
      description:
        "DEPLOYS a `.pyscript` file that snaps every note's start position to a grid. grid_division is steps per beat: 1 = beat, 2 = 1/8, 4 = 1/16, 8 = 1/32, 16 = 1/64, 32 = 1/128. Generated script uses FL piano-roll PPQ=96 and round-to-nearest snap. You must invoke it manually from FL Studio's Piano Roll (Ctrl+Alt+Y) to apply.",
      inputSchema: {
        grid_division: z
          .union([
            z.literal(1),
            z.literal(2),
            z.literal(4),
            z.literal(8),
            z.literal(16),
            z.literal(32),
          ])
          .describe(
            "Grid resolution as steps per beat: 1,2,4,8,16,32. PPQ=96 so snap=96/division.",
          ),
        script_name: scriptNameSchema,
      },
    },
    async ({ grid_division, script_name }) => {
      const source = generateQuantize(grid_division);
      const result = await deployPyscript(source, script_name, "quantize");
      return jsonResult(result);
    },
  );

  server.registerTool(
    "piano_roll_deploy_velocity_set",
    {
      description:
        "DEPLOYS a `.pyscript` file that sets every note in the current piano-roll pattern to a single velocity. Velocity is MIDI 1..127 at the tool boundary; the generated script converts to flpianoroll's 0.0..1.0 float. You must invoke it manually from FL Studio's Piano Roll (Ctrl+Alt+Y) to apply.",
      inputSchema: {
        velocity: z
          .number()
          .int()
          .min(1)
          .max(127)
          .describe("Target MIDI velocity 1..127."),
        script_name: scriptNameSchema,
      },
    },
    async ({ velocity, script_name }) => {
      const source = generateVelocitySet(velocity);
      const result = await deployPyscript(
        source,
        script_name,
        "velocity_set",
      );
      return jsonResult(result);
    },
  );

  server.registerTool(
    "piano_roll_list_deployed",
    {
      description:
        "Lists `.pyscript` files currently deployed in FL Studio's piano-roll scripts directory (resolved from FLSTUDIO_MCP_SCRIPTS_DIR override or %USERPROFILE%\\Documents\\Image-Line\\FL Studio\\Settings\\Scripts). Returns `{ dir, scripts: Array<{ name, size_bytes, modified_at }> }` sorted newest-first. Does NOT execute any script — read-only.",
      inputSchema: {},
    },
    async () => {
      const scripts = await listDeployedScripts();
      return jsonResult({ dir: resolveScriptsDir(), scripts });
    },
  );
}
