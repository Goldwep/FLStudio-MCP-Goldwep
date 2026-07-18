// L7 out-of-process PyFLP helper runner.
//
// Spawns the bundled `bridge/pyflp_helper.py` as a Python subprocess and
// proxies an action + JSON args payload to it. The helper writes a single
// JSON envelope to stdout — { ok: true, result } or { ok: false, error,
// traceback } — and exits 0 either way; we never key on the process exit
// code for success/failure.
//
// PyFLP is read-only-safe but unmaintained against FL 2025 (upstream
// issues #200/#203/#197); this runner deliberately stays out of the
// bridge code path so PyFLP failures can never corrupt live FL state.

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { BridgeError } from "../bridge/index.js";
import { logger } from "../utils/logger.js";

// Python interpreter resolution, in priority order:
//   1. FLSTUDIO_MCP_PYTHON env var (explicit user override)
//   2. A repo-local `.venv-pyflp` virtualenv, if present. PyFLP 2.2.x
//      requires Python <= 3.10: its abstract EventEnum(value) lookup
//      relies on `_missing_` dispatch that Python 3.11+ rejects with
//      "TypeError: <enum 'EventEnum'> has no members defined". The
//      documented setup (docs/L7-PYFLP-SETUP.md) provisions this venv
//      via `uv venv --python 3.10 .venv-pyflp`.
//   3. PATH-resolved "python" (or "python3" off-Windows) — works only
//      if the system Python is <= 3.10.
const DEFAULT_PYTHON = process.platform === "win32" ? "python" : "python3";

function venvPython(): string | null {
  const here = dirname(fileURLToPath(import.meta.url));
  // src/pyflp → ../../.venv-pyflp ; dist/pyflp → same relative hop.
  const venvDir = resolve(here, "..", "..", ".venv-pyflp");
  const candidate =
    process.platform === "win32"
      ? resolve(venvDir, "Scripts", "python.exe")
      : resolve(venvDir, "bin", "python");
  return existsSync(candidate) ? candidate : null;
}

const DEFAULT_TIMEOUT_MS = 30_000;

// Resolve `bridge/pyflp_helper.py` relative to this file's location.
// At dev time this file is src/pyflp/runner.ts → ../../bridge/pyflp_helper.py.
// After `tsc` it lives at dist/pyflp/runner.js → same relative hop.
function defaultHelperPath(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  // src/pyflp → ../../bridge ; dist/pyflp → ../../bridge
  return resolve(here, "..", "..", "bridge", "pyflp_helper.py");
}

function pythonExecutable(): string {
  const envPath = process.env.FLSTUDIO_MCP_PYTHON;
  if (envPath && envPath.trim().length > 0) return envPath;
  const venv = venvPython();
  if (venv) return venv;
  return DEFAULT_PYTHON;
}

function helperPath(): string {
  const envPath = process.env.FLSTUDIO_MCP_PYFLP_HELPER;
  if (envPath && envPath.trim().length > 0) return envPath;
  return defaultHelperPath();
}

interface HelperEnvelope {
  ok: boolean;
  result?: unknown;
  error?: string;
  traceback?: string;
  hint?: string;
}

/**
 * Invoke the PyFLP helper script with the given action and args.
 *
 * @param action  one of the registered helper actions (scan_folder,
 *                inspect, plugins, samples, check_missing_samples,
 *                tempo_distribution, plugin_inventory, pattern_summary).
 * @param args    arbitrary JSON-serializable args object passed through
 *                to the helper's action_<name> handler.
 * @param timeoutMs override the default 30s timeout.
 */
export function runPyflp(
  action: string,
  args: Record<string, unknown> = {},
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<unknown> {
  const py = pythonExecutable();
  const helper = helperPath();

  if (!existsSync(helper)) {
    return Promise.reject(
      new BridgeError(`PyFLP helper script not found at: ${helper}`, {
        code: "PYFLP_HELPER_MISSING",
      }),
    );
  }

  return new Promise((resolveP, rejectP) => {
    let settled = false;
    const finish = (cb: () => void) => {
      if (settled) return;
      settled = true;
      cb();
    };

    const argsJson = JSON.stringify(args);
    logger.debug(`pyflp helper: ${action} ${argsJson}`);

    const child = spawn(py, [helper, action, argsJson], {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });

    const timer = setTimeout(() => {
      finish(() => {
        try {
          child.kill("SIGKILL");
        } catch {
          // ignore
        }
        rejectP(
          new BridgeError(`PyFLP helper timed out after ${timeoutMs}ms`, {
            code: "PYFLP_TIMEOUT",
          }),
        );
      });
    }, timeoutMs);

    child.on("error", (err) => {
      finish(() => {
        clearTimeout(timer);
        rejectP(
          new BridgeError(
            `PyFLP helper spawn failed: ${err.message} (python="${py}"). ` +
              `Set FLSTUDIO_MCP_PYTHON to the desired interpreter.`,
            { code: "PYFLP_SPAWN_FAILED", cause: err },
          ),
        );
      });
    });

    child.on("close", (code) => {
      finish(() => {
        clearTimeout(timer);
        if (stderr.trim().length > 0) {
          logger.debug(`pyflp helper stderr: ${stderr.trim()}`);
        }
        if (stdout.trim().length === 0) {
          rejectP(
            new BridgeError(
              `PyFLP helper produced no output (exit=${code}). stderr: ${stderr.trim()}`,
              { code: "PYFLP_EMPTY_OUTPUT" },
            ),
          );
          return;
        }
        let envelope: HelperEnvelope;
        try {
          envelope = JSON.parse(stdout) as HelperEnvelope;
        } catch (e) {
          rejectP(
            new BridgeError(
              `PyFLP helper stdout was not valid JSON (exit=${code}): ${stdout.slice(0, 400)}`,
              { code: "PYFLP_BAD_JSON", cause: e },
            ),
          );
          return;
        }
        if (!envelope.ok) {
          const hint = envelope.hint ? ` Hint: ${envelope.hint}` : "";
          rejectP(
            new BridgeError(`PyFLP helper error: ${envelope.error ?? "<unknown>"}.${hint}`, {
              code: "PYFLP_ACTION_FAILED",
            }),
          );
          return;
        }
        resolveP(envelope.result);
      });
    });
  });
}
