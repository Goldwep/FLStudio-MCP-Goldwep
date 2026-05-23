import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
// Bridge is not used by L7 — these tools shell out to a Python helper that
// reads `.flp` files off disk via PyFLP, fully out-of-process from FL.
// Keep the parameter in the function signature for symmetry with every
// other tool module so server.ts wiring stays uniform.
import type { Bridge } from "../bridge/index.js";
import { runPyflp } from "../pyflp/runner.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

// L7 — PyFLP project intelligence.
// All paths are absolute; PyFLP requires real files on disk. The helper is
// READ-ONLY: no tool here ever calls `pyflp.save()`. Per upstream issues
// #200/#203/#197, writes against FL 2025 are unsafe and parsing of post-
// FL-2024 projects may degrade gracefully (errors surface per-file in the
// `errors` array of `scan_folder` / `tempo_distribution` / `plugin_inventory`
// rather than aborting the whole scan).
export function registerFlpTools(server: McpServer, _bridge: Bridge): void {
  server.registerTool(
    "flp_scan_folder",
    {
      description:
        "Recursively scan a folder for FL Studio `.flp` project files and return a one-line summary per file: { path, title, tempo, time_signature, channel_count, mixer_track_count, pattern_count, file_size_bytes }. Out-of-process — does NOT require FL Studio to be running. Files that fail to parse surface in an `errors` array rather than aborting the scan. Pass an absolute folder path.",
      inputSchema: {
        folder: z
          .string()
          .min(1)
          .describe("Absolute path to a folder containing .flp files (scanned recursively)."),
      },
    },
    async ({ folder }) => jsonResult(await runPyflp("scan_folder", { folder })),
  );

  server.registerTool(
    "flp_inspect",
    {
      description:
        "Deep-inspect a single .flp file. Returns { title, artist, genre, comments, version, tempo, time_signature, channel_count, mixer_track_count, pattern_count, sample_paths_count }. Read-only; does NOT require FL Studio. Fields may be null for older or non-standard projects.",
      inputSchema: {
        path: z.string().min(1).describe("Absolute path to a .flp file."),
      },
    },
    async ({ path }) => jsonResult(await runPyflp("inspect", { path })),
  );

  server.registerTool(
    "flp_get_plugins",
    {
      description:
        "List every plugin instance referenced by a .flp file. Returns [{ name, type, channel_or_mixer, index, slot_index }]. `channel_or_mixer` = 'channel' for channel-rack instruments (slot_index=null), 'mixer' for mixer-insert effect slots. Read-only; does NOT require FL Studio.",
      inputSchema: {
        path: z.string().min(1).describe("Absolute path to a .flp file."),
      },
    },
    async ({ path }) => jsonResult(await runPyflp("plugins", { path })),
  );

  server.registerTool(
    "flp_get_samples",
    {
      description:
        "List every sample-path reference (sampler channel `sample_path`) in a .flp file. Paths are returned as stored — they may be absolute, relative to FL's user data folder, or stale. Use `flp_check_missing_samples` to check which ones resolve. Read-only.",
      inputSchema: {
        path: z.string().min(1).describe("Absolute path to a .flp file."),
      },
    },
    async ({ path }) => jsonResult(await runPyflp("samples", { path })),
  );

  server.registerTool(
    "flp_check_missing_samples",
    {
      description:
        "Resolve every sample-path reference in a .flp file against the filesystem. Returns { missing: [...absolute paths that don't exist], present_count, missing_count }. Read-only.",
      inputSchema: {
        path: z.string().min(1).describe("Absolute path to a .flp file."),
      },
    },
    async ({ path }) => jsonResult(await runPyflp("check_missing_samples", { path })),
  );

  server.registerTool(
    "flp_tempo_distribution",
    {
      description:
        "Recursively scan a folder of .flp files and build a tempo histogram in 5-BPM buckets. Returns { buckets: { '120-124': n, '125-129': n, ... }, total, errors }. Useful for understanding the tempos a user writes at. Read-only.",
      inputSchema: {
        folder: z
          .string()
          .min(1)
          .describe("Absolute path to a folder containing .flp files (scanned recursively)."),
      },
    },
    async ({ folder }) => jsonResult(await runPyflp("tempo_distribution", { folder })),
  );

  server.registerTool(
    "flp_plugin_inventory",
    {
      description:
        "Recursively scan a folder of .flp files and count plugin instance occurrences across all projects. Returns { plugins: { 'PluginName': count, ... }, files_scanned, errors }. Identifies which plugins the user actually uses most.",
      inputSchema: {
        folder: z
          .string()
          .min(1)
          .describe("Absolute path to a folder containing .flp files (scanned recursively)."),
      },
    },
    async ({ folder }) => jsonResult(await runPyflp("plugin_inventory", { folder })),
  );

  server.registerTool(
    "flp_get_pattern_summary",
    {
      description:
        "Per-pattern summary for a .flp file: [{ index, name, note_count }]. YELLOW: FL Studio 2025 changed playlist/pattern serialization in ways PyFLP doesn't fully understand yet (upstream issue #200) — note_count may be 0 or fields may be null on modern projects even when the pattern has notes. Best-effort. Read-only.",
      inputSchema: {
        path: z.string().min(1).describe("Absolute path to a .flp file."),
      },
    },
    async ({ path }) => jsonResult(await runPyflp("pattern_summary", { path })),
  );
}
