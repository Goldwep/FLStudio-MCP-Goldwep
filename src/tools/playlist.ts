import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

export function registerPlaylistTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "playlist_track_count",
    {
      description:
        "Total number of playlist (arrangement) tracks in the project. NOT mixer tracks. Playlist tracks are 1-indexed when passed back to other playlist_* tools.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("playlist.trackCount")),
  );

  server.registerTool(
    "playlist_get_track_name",
    {
      description:
        'Get the display name of a playlist track. Default for an unrenamed track is "Track n".',
      inputSchema: {
        index: z.number().int().min(1).describe("Playlist track index (1-based per the research)"),
      },
    },
    async ({ index }) => jsonResult(await bridge.call("playlist.getTrackName", { index })),
  );

  server.registerTool(
    "playlist_get_track_color",
    {
      description:
        "Get the color of a playlist track as a 32-bit integer in 0x--BBGGRR layout (BGRA little-endian).",
      inputSchema: {
        index: z.number().int().min(1).describe("Playlist track index (1-based per the research)"),
      },
    },
    async ({ index }) => jsonResult(await bridge.call("playlist.getTrackColor", { index })),
  );

  server.registerTool(
    "playlist_is_track_muted",
    {
      description: "Returns true if the playlist track at `index` is muted.",
      inputSchema: {
        index: z.number().int().min(1).describe("Playlist track index (1-based per the research)"),
      },
    },
    async ({ index }) => jsonResult(await bridge.call("playlist.isTrackMuted", { index })),
  );

  server.registerTool(
    "playlist_get_display_zone",
    {
      description:
        "Get the active controller display zone for performance mode. Returns the raw bridge response (FL exposes this as an int — the active controller's zone id, where 0 means no controller currently owns a zone). Useful for telling FL which on-screen region of the live-clip grid is being focused by a hardware controller.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("playlist.getDisplayZone")),
  );
}
