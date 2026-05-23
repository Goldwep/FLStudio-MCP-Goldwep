import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Bridge } from "../bridge/index.js";

// L8b — state_sync. Bridge-side accumulation of FL Studio's OnDirty* / OnRefresh
// callbacks so the LLM can poll for "what changed since last drain" without
// re-walking the entire project on every turn.
//
// Architecture note (per L3 critic): OnDirtyMixerTrack / OnDirtyChannel /
// OnRefresh are MODULE-LEVEL functions in the FL device script that FL invokes
// by name. They cannot be registered/unregistered at runtime. Instead the
// bridge keeps a persistent `BridgeState.dirty_subscribed: bool` flag plus an
// in-memory event queue. Each OnDirty* checks the flag — if True, push event;
// if False, no-op. The MCP tools below toggle the flag and drain the queue.
//
// These tools wrap bridge.call into the eventual bridge interface — they'll
// work once the bridge-side flag + queue land (probe + bridge transport are
// still pending as of L8b spec).

function jsonResult(value: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
  };
}

export function registerStateSyncTools(server: McpServer, bridge: Bridge): void {
  server.registerTool(
    "state_subscribe",
    {
      description:
        "Toggle the bridge-side dirty-event subscription flag. When enabled=true, the bridge's OnDirtyChannel / OnDirtyMixerTrack / OnRefresh / OnUpdateBeatIndicator callbacks accumulate events into an in-memory queue; when enabled=false, they no-op. NOTE: this is a BRIDGE-SIDE TOGGLE, not a callback registration — FL's OnDirty* hooks are module-level and cannot be registered at runtime. The bridge always exposes the callbacks; this flag just gates whether they record. Unified subscribe/unsubscribe via one tool: pass enabled=false to stop accumulating. Drain the queue with state_get_changes.",
      inputSchema: {
        enabled: z
          .boolean()
          .default(true)
          .describe("true = start accumulating dirty events; false = stop and discard further events (queue is preserved until drained)."),
      },
    },
    async ({ enabled }) =>
      jsonResult(await bridge.call("state.setSubscribed", { enabled })),
  );

  server.registerTool(
    "state_get_changes",
    {
      description:
        "Drain and return all accumulated dirty events since the last drain (or since state_subscribe was first enabled). Returns an empty list if nothing changed. Event schema:\n" +
        "  { kind: \"channel\", index: number, flag: 0|1|2|3|4, flag_name: \"CE_New\"|\"CE_Delete\"|\"CE_Replace\"|\"CE_Rename\"|\"CE_Select\" }\n" +
        "    — CE_* flag from OnDirtyChannel. CE_New=0, CE_Delete=1, CE_Replace=2, CE_Rename=3, CE_Select=4.\n" +
        "  { kind: \"mixer_track\", index: number }\n" +
        "    — from OnDirtyMixerTrack. index = -1 means ALL tracks dirty (FL convention).\n" +
        "  { kind: \"refresh\", flags: number }\n" +
        "    — HW_Dirty_* bitmask from OnRefresh (broad state-change signal).\n" +
        "  { kind: \"song_pos\", position: number }\n" +
        "    — current song position (from OnUpdateBeatIndicator-style callbacks).\n" +
        "Events are returned in arrival order. Drain is destructive: a second consecutive call returns []. Returns [] also if state_subscribe was never enabled.",
      inputSchema: {},
    },
    async () => jsonResult(await bridge.call("state.drainChanges")),
  );

  server.registerTool(
    "state_snapshot",
    {
      description:
        "Capture a LIGHT snapshot of FL Studio's current state for LLM context loading. Returns { timestamp, transport: { isPlaying, projectTitle }, channels: { count }, mixer: { count }, patterns: { count } }. Server-side composite — issues parallel L1/L2 read calls (transport.isPlaying, general.getCurrentProjectTitle, channels.channelCount, mixer.trackCount, patterns.patternCount) and aggregates. No new bridge.call required beyond existing L2 surface. NOTE: this is the v1 LIGHT snapshot — it returns COUNTS only, not per-channel/per-track detail (a deep snapshot would loop every channel and track which is expensive). Deep snapshot is a v1.1 enhancement. Pair with state_diff_snapshots to compute deltas between two points in time.",
      inputSchema: {},
    },
    async () => {
      const [
        isPlaying,
        projectTitle,
        channelCount,
        mixerTrackCount,
        patternCount,
      ] = await Promise.all([
        bridge.call("transport.isPlaying"),
        bridge.call("general.getCurrentProjectTitle"),
        bridge.call("channels.channelCount"),
        bridge.call("mixer.trackCount"),
        bridge.call("patterns.patternCount"),
      ]);
      return jsonResult({
        timestamp: Date.now(),
        transport: { isPlaying, projectTitle },
        channels: { count: channelCount },
        mixer: { count: mixerTrackCount },
        patterns: { count: patternCount },
      });
    },
  );

  server.registerTool(
    "state_diff_snapshots",
    {
      description:
        "Compare two snapshots from state_snapshot and return the delta. Pure TypeScript — no bridge.call. Returns { ok: true, changed: { <key>: { before, after } } } for top-level keys whose JSON serialization differs. Use to detect what changed between two arbitrary points in time (e.g. before/after a long-running tool call). Returns { ok: false, error: ... } if either argument is not an object.",
      inputSchema: {
        before: z
          .unknown()
          .describe("Earlier snapshot object (from state_snapshot)."),
        after: z
          .unknown()
          .describe("Later snapshot object (from state_snapshot)."),
      },
    },
    async ({ before, after }) => {
      if (
        typeof before !== "object" ||
        typeof after !== "object" ||
        before === null ||
        after === null
      ) {
        return jsonResult({
          ok: false,
          error: "Both before and after must be snapshot objects",
        });
      }
      const b = before as Record<string, unknown>;
      const a = after as Record<string, unknown>;
      const changed: Record<string, { before: unknown; after: unknown }> = {};
      for (const key of new Set([...Object.keys(b), ...Object.keys(a)])) {
        if (JSON.stringify(b[key]) !== JSON.stringify(a[key])) {
          changed[key] = { before: b[key], after: a[key] };
        }
      }
      return jsonResult({ ok: true, changed });
    },
  );
}
