#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerTools } from "./server.js";
import { loadConfig } from "./config.js";
import { logger } from "./utils/logger.js";

const config = loadConfig();

const server = new McpServer({
  name: "flstudio-mcp",
  version: "1.0.1",
});

registerTools(server, config);

const transport = new StdioServerTransport();
await server.connect(transport);
logger.info("flstudio-mcp server started");
