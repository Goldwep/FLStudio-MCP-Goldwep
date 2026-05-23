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
}
