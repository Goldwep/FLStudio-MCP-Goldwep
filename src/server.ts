import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Config } from "./config.js";

export function registerTools(_server: McpServer, _config: Config): void {
  // Tool surface is defined in the first planning phase.
  // Each capability area gets its own module under src/tools/ and registers
  // here. Provisional areas: composition (channels/patterns/notes),
  // mixer, transport, playlist, arrangement, plugins, project (inspection),
  // ui, general.
}
