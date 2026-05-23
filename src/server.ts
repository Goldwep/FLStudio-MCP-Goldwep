import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Config } from "./config.js";
import { makeBridge } from "./bridge/index.js";

// L1 — bridge sanity + first transport/general entry points.
import { registerSystemTools } from "./tools/system.js";
import { registerTransportTools } from "./tools/transport.js";
import { registerGeneralTools } from "./tools/general.js";

// L2 — inspection breadth across the FL Studio MIDI scripting API.
import { registerChannelsTools } from "./tools/channels.js";
import { registerMixerTools } from "./tools/mixer.js";
import { registerPatternsTools } from "./tools/patterns.js";
import { registerPlaylistTools } from "./tools/playlist.js";
import { registerPluginsTools } from "./tools/plugins.js";
import { registerTransportExtraTools } from "./tools/transport_extra.js";
import { registerGeneralExtraTools } from "./tools/general_extra.js";
import { registerArrangementTools } from "./tools/arrangement.js";
import { registerUiTools } from "./tools/ui.js";

// L5 — composition v1: step grid.
import { registerChannelsStepsTools } from "./tools/channels_steps.js";

// L7 — PyFLP project intelligence (out-of-process).
import { registerFlpTools } from "./tools/flp.js";

// L8a — live composition (note dispatch, record arm, state polling).
import { registerLiveTools } from "./tools/live.js";

// L8b — state_sync. Bridge-side dirty-event accumulation + snapshot/diff.
// Tools wire into the bridge interface; they activate once the bridge-side
// flag + event queue land (probe + bridge transport pending).
import { registerStateSyncTools } from "./tools/state_sync.js";

// L6 — Piano Roll `.pyscript` dispatch (v1.0: deploy-only). File-I/O tools
// that generate `.pyscript` files into FL Studio's scripts directory; user
// manually invokes from Piano Roll via Ctrl+Alt+Y. Bridge is passed for
// signature symmetry but unused inside piano_roll.ts. Auto-trigger is
// deferred to v1.1 pending L0 probe data on REC-event note dispatch.
import { registerPianoRollTools } from "./tools/piano_roll.js";

// One bridge instance is shared across every tool module so that all FL
// Studio API calls flow through a single queue-and-drain chokepoint (per
// the runtime model in projects/flstudio_mcp_goldwep.md).
//
// Order: system first (so ping is always available even if downstream
// registrations fail), then L1 sanity tools, then L2 inspection modules
// grouped by FL module. Future milestones (L4 mutation, L5 step grid,
// L6 piano-roll dispatch, L7 PyFLP, L8 live composition) extend this list.
export function registerTools(server: McpServer, config: Config): void {
  const bridge = makeBridge(config);

  // L1
  registerSystemTools(server, bridge);
  registerTransportTools(server, bridge);
  registerGeneralTools(server, bridge);

  // L2
  registerTransportExtraTools(server, bridge);
  registerGeneralExtraTools(server, bridge);
  registerChannelsTools(server, bridge);
  registerMixerTools(server, bridge);
  registerPatternsTools(server, bridge);
  registerPlaylistTools(server, bridge);
  registerPluginsTools(server, bridge);
  registerArrangementTools(server, bridge);
  registerUiTools(server, bridge);

  // L5 — composition v1 (step grid). Sits after registerChannelsTools so
  // step-grid tools are a clear extension surface above L2/L4 channel ops.
  registerChannelsStepsTools(server, bridge);

  // L7 — PyFLP project intelligence (out-of-process).
  // Static .flp scanning via a Python subprocess; no FL Studio required.
  // Bridge is passed for signature symmetry but unused inside flp.ts.
  registerFlpTools(server, bridge);

  // L8a — live composition. Real-time note dispatch + record-arm guard.
  registerLiveTools(server, bridge);

  // L8b — state_sync. Subscribe/drain dirty events + light snapshot/diff.
  registerStateSyncTools(server, bridge);

  // L6 — Piano Roll `.pyscript` dispatch (v1.0: deploy-only). Registered
  // last because it's a side-channel surface (file I/O, no bridge calls)
  // and is gated on user manual invocation rather than the bridge runtime.
  registerPianoRollTools(server, bridge);
}
