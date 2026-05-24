// L6 piano-roll `.pyscript` deployer.
//
// Resolves the target FL Studio scripts directory, ensures it exists, and
// writes generated `.pyscript` source files into it. After deploy, the
// user manually invokes the script from the Piano Roll via Ctrl+Alt+Y or
// the Tools menu (v1.0 — auto-trigger is deferred to v1.1 pending L0
// probe data on whether REC events can substitute).
//
// Path resolution order:
//   1. process.env.FLSTUDIO_MCP_SCRIPTS_DIR (override for tests / non-default installs)
//   2. %USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Scripts (default)
//   3. fallback: os.homedir() + same suffix (covers exotic env where USERPROFILE is unset)
//
// All I/O lives here so generator.ts stays a pure string library.

import { mkdir, writeFile, readdir, stat } from "node:fs/promises";
import { join, resolve, isAbsolute } from "node:path";
import { homedir } from "node:os";

const DEFAULT_SCRIPTS_SUFFIX = join("Documents", "Image-Line", "FL Studio", "Settings", "Scripts");

export interface DeployResult {
  ok: true;
  path: string;
  source_lines: number;
}

export interface DeployedScriptInfo {
  name: string;
  size_bytes: number;
  modified_at: string;
}

export function resolveScriptsDir(): string {
  const override = process.env.FLSTUDIO_MCP_SCRIPTS_DIR;
  if (override && override.length > 0) {
    return isAbsolute(override) ? override : resolve(override);
  }
  const userProfile = process.env.USERPROFILE;
  if (userProfile && userProfile.length > 0) {
    return join(userProfile, DEFAULT_SCRIPTS_SUFFIX);
  }
  return join(homedir(), DEFAULT_SCRIPTS_SUFFIX);
}

function sanitizeScriptName(raw: string): string {
  // Strip directory separators and any extension the caller accidentally
  // tacked on. The deployer owns the `.pyscript` suffix.
  const base = raw.replace(/[\\/]/g, "_").replace(/\.pyscript$/i, "");
  // Keep alnum, dash, underscore, dot. Anything else → underscore. This
  // matches FL's scripts-folder file-naming tolerance without being
  // overly permissive.
  return base.replace(/[^A-Za-z0-9._-]/g, "_") || `mcp_${Date.now()}`;
}

function defaultScriptName(prefix: string): string {
  // Deterministic-ish but unique enough across rapid back-to-back deploys.
  return `${prefix}_${Date.now()}`;
}

export async function deployPyscript(
  source: string,
  scriptName: string | undefined,
  operationLabel: string,
): Promise<DeployResult> {
  const dir = resolveScriptsDir();
  await mkdir(dir, { recursive: true });

  const baseName = scriptName
    ? sanitizeScriptName(scriptName)
    : defaultScriptName(`mcp_${operationLabel}`);
  const filePath = join(dir, `${baseName}.pyscript`);

  // utf8, default LF line endings. FL's script editor handles both LF and
  // CRLF on Windows; LF keeps diffs clean if the user version-controls
  // their scripts folder.
  await writeFile(filePath, source, "utf8");

  const sourceLines = source.split("\n").length;
  return {
    ok: true,
    path: filePath,
    source_lines: sourceLines,
  };
}

export async function listDeployedScripts(): Promise<DeployedScriptInfo[]> {
  const dir = resolveScriptsDir();
  // If the dir doesn't exist yet, return [] rather than throw — listing
  // is a read tool; a missing dir means "no scripts deployed", not an error.
  try {
    await mkdir(dir, { recursive: true });
  } catch {
    return [];
  }

  let entries: string[];
  try {
    entries = await readdir(dir);
  } catch {
    return [];
  }

  const results: DeployedScriptInfo[] = [];
  for (const name of entries) {
    if (!name.toLowerCase().endsWith(".pyscript")) continue;
    try {
      const s = await stat(join(dir, name));
      if (!s.isFile()) continue;
      results.push({
        name,
        size_bytes: s.size,
        modified_at: s.mtime.toISOString(),
      });
    } catch {
      // Skip files we can't stat (permission errors etc).
      continue;
    }
  }
  // Newest first — matches the "what did I just deploy?" caller intent.
  results.sort((a, b) => (a.modified_at < b.modified_at ? 1 : -1));
  return results;
}
