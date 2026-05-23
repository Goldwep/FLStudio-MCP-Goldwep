import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Config } from "./config.js";
import { makeBridge } from "./bridge/index.js";
import { registerSystemTools } from "./tools/system.js";
import { registerTransportTools } from "./tools/transport.js";
import { registerGeneralTools } from "./tools/general.js";

// One bridge instance is shared across every tool module so that all FL
// Studio API calls flow through a single queue-and-drain chokepoint (per
// the runtime model in projects/flstudio_mcp_goldwep.md).
//
// Capability areas land here one module at a time. Provisional roadmap:
// composition (channels/patterns/notes), mixer, transport, playlist,
// arrangement, plugins, project, ui, general. L1 ships system + transport
// + general against the StubBridge so the graph wires up end-to-end.
export function registerTools(server: McpServer, config: Config): void {
  const bridge = makeBridge(config);
  registerSystemTools(server, bridge);
  registerTransportTools(server, bridge);
  registerGeneralTools(server, bridge);
}
