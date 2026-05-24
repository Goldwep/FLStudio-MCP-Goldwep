// One-command live-FL verification. Probes every entry in the FL-side
// DISPATCH table (88 methods) via the same SocketBridge the MCP server uses
// in production, classifies each result, and emits docs/LIVE-VERIFY-REPORT.md.
//
// Usage:
//   npx tsx scripts/verify-live.ts
//   npx tsx scripts/verify-live.ts --include-writes   // opt-in to mutating calls
//
// Behaviour summary:
//   1. Wait-for-bridge loop: poll 127.0.0.1:9876 every 1 sec for up to 60 sec.
//   2. Connect via SocketBridge (production transport, not a reimplementation).
//   3. Probe every method with safe default args, grouped by module.
//   4. Print a per-method line (✅ / ❌ / ⏭️) and a per-module summary table.
//   5. Write docs/LIVE-VERIFY-REPORT.md with the full result table and
//      suggested fixes for failures (looked up in the bridge-contract-audit).
//   6. Exit 0 if everything ran green, 1 on any ❌, 2 if bridge unreachable.

import { writeFileSync, mkdirSync } from "node:fs";
import { Socket } from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { loadConfig } from "../src/config.js";
import { SocketBridge } from "../src/bridge/socket.js";
import { BridgeError } from "../src/bridge/types.js";

// ---------------------------------------------------------------------------
// Wait-for-bridge loop
// ---------------------------------------------------------------------------

const WAIT_TIMEOUT_SECONDS = 60;
const WAIT_INTERVAL_MS = 1000;

async function probeBridge(host: string, port: number, timeoutMs: number): Promise<boolean> {
  return new Promise((res) => {
    const sock = new Socket();
    let settled = false;
    const t = setTimeout(() => {
      if (settled) return;
      settled = true;
      sock.destroy();
      res(false);
    }, timeoutMs);
    sock.once("connect", () => {
      if (settled) return;
      settled = true;
      clearTimeout(t);
      sock.destroy();
      res(true);
    });
    sock.once("error", () => {
      if (settled) return;
      settled = true;
      clearTimeout(t);
      sock.destroy();
      res(false);
    });
    sock.connect(port, host);
  });
}

async function waitForBridge(host: string, port: number): Promise<boolean> {
  process.stdout.write(
    `[verify] waiting for FL bridge on ${host}:${port} (timeout ${WAIT_TIMEOUT_SECONDS}s).\n`,
  );
  for (let attempt = 1; attempt <= WAIT_TIMEOUT_SECONDS; attempt++) {
    process.stdout.write(`[verify] connecting... attempt ${attempt}/${WAIT_TIMEOUT_SECONDS}\r`);
    const up = await probeBridge(host, port, 800);
    if (up) {
      process.stdout.write(`\n[verify] bridge live, starting verification...\n`);
      return true;
    }
    await new Promise((r) => setTimeout(r, WAIT_INTERVAL_MS));
  }
  process.stdout.write(`\n`);
  return false;
}

// ---------------------------------------------------------------------------
// Probe table
//
// Every entry of the FL-side DISPATCH table (88 methods, see
// bridge/device_FLStudioMCP.py). `args` is the request payload sent to the
// bridge. `kind`:
//   - "read"        : pure getter, safe to run by default
//   - "write"       : mutates project state, skipped unless --include-writes
//   - "audible"     : produces sound / transport motion, requires explicit
//                     --include-writes opt-in (write-shaped)
//   - "internal"    : MCP-bridge primitive, always safe to run
// ---------------------------------------------------------------------------

type ProbeKind = "read" | "write" | "audible" | "internal";

interface Probe {
  method: string;
  args: Record<string, unknown>;
  kind: ProbeKind;
  module: string;
}

const PROBES: Probe[] = [
  // -- bridge-internal ----------------------------------------------------
  { method: "ping", args: {}, kind: "internal", module: "ping" },
  { method: "state.setSubscribed", args: { enabled: false }, kind: "internal", module: "state" },
  { method: "state.drainChanges", args: {}, kind: "internal", module: "state" },

  // -- transport (read first, then writes/audible) ------------------------
  { method: "transport.isPlaying", args: {}, kind: "read", module: "transport" },
  { method: "transport.isRecording", args: {}, kind: "read", module: "transport" },
  { method: "transport.getSongPos", args: { unit: 2 }, kind: "read", module: "transport" },
  { method: "transport.getSongLength", args: { unit: 2 }, kind: "read", module: "transport" },
  { method: "transport.start", args: {}, kind: "audible", module: "transport" },
  { method: "transport.stop", args: {}, kind: "audible", module: "transport" },
  { method: "transport.record", args: {}, kind: "audible", module: "transport" },
  { method: "transport.setLoopMode", args: {}, kind: "write", module: "transport" },
  {
    method: "transport.setSongPos",
    args: { position: 0, mode: 2 },
    kind: "write",
    module: "transport",
  },
  { method: "transport.toggleMetronome", args: {}, kind: "write", module: "transport" },
  { method: "transport.tapTempo", args: {}, kind: "write", module: "transport" },

  // -- general -----------------------------------------------------------
  { method: "general.getProjectTitle", args: {}, kind: "read", module: "general" },
  { method: "general.getChangedFlag", args: {}, kind: "read", module: "general" },
  { method: "general.getRecPPB", args: {}, kind: "read", module: "general" },
  { method: "general.getUseMetronome", args: {}, kind: "read", module: "general" },
  { method: "general.undo", args: {}, kind: "write", module: "general" },
  { method: "general.saveProject", args: {}, kind: "write", module: "general" },

  // -- channels ----------------------------------------------------------
  { method: "channels.channelCount", args: {}, kind: "read", module: "channels" },
  { method: "channels.getChannelName", args: { index: 0 }, kind: "read", module: "channels" },
  { method: "channels.getChannelColor", args: { index: 0 }, kind: "read", module: "channels" },
  { method: "channels.getChannelVolume", args: { index: 0 }, kind: "read", module: "channels" },
  { method: "channels.getChannelPan", args: { index: 0 }, kind: "read", module: "channels" },
  { method: "channels.getTargetFxTrack", args: { index: 0 }, kind: "read", module: "channels" },
  { method: "channels.getChannelType", args: { index: 0 }, kind: "read", module: "channels" },
  {
    method: "channels.getGridBit",
    args: { index: 0, position: 0 },
    kind: "read",
    module: "channels",
  },
  {
    method: "channels.getCurrentStepParam",
    args: { index: 0, step: 0, param: 0 },
    kind: "read",
    module: "channels",
  },
  {
    method: "channels.setChannelName",
    args: { index: 0, name: "verify-probe" },
    kind: "write",
    module: "channels",
  },
  {
    method: "channels.setChannelVolume",
    args: { index: 0, value: 0.78 },
    kind: "write",
    module: "channels",
  },
  {
    method: "channels.setChannelPan",
    args: { index: 0, value: 0.0 },
    kind: "write",
    module: "channels",
  },
  {
    method: "channels.setChannelColor",
    args: { index: 0, color: 0x808080 },
    kind: "write",
    module: "channels",
  },
  {
    method: "channels.setTargetFxTrack",
    args: { index: 0, fxIndex: 0 },
    kind: "write",
    module: "channels",
  },
  {
    method: "channels.selectChannel",
    args: { index: 0, value: -1 },
    kind: "write",
    module: "channels",
  },
  {
    method: "channels.muteChannel",
    args: { index: 0, value: -1 },
    kind: "write",
    module: "channels",
  },
  { method: "channels.soloChannel", args: { index: 0 }, kind: "write", module: "channels" },
  {
    method: "channels.setGridBit",
    args: { index: 0, position: 0, value: 0 },
    kind: "write",
    module: "channels",
  },
  {
    method: "channels.setStepParameterByIndex",
    args: { index: 0, step: 0, param: 0, value: 0 },
    kind: "write",
    module: "channels",
  },
  {
    method: "channels.midiNoteOn",
    args: { channel_index: 0, note: 60, velocity: 0, midi_channel: 0 },
    kind: "audible",
    module: "channels",
  },

  // -- mixer -------------------------------------------------------------
  { method: "mixer.trackCount", args: {}, kind: "read", module: "mixer" },
  { method: "mixer.getTrackName", args: { index: 0 }, kind: "read", module: "mixer" },
  { method: "mixer.getTrackColor", args: { index: 0 }, kind: "read", module: "mixer" },
  { method: "mixer.getTrackVolume", args: { index: 0 }, kind: "read", module: "mixer" },
  { method: "mixer.getTrackPan", args: { index: 0 }, kind: "read", module: "mixer" },
  { method: "mixer.isTrackMuted", args: { index: 0 }, kind: "read", module: "mixer" },
  { method: "mixer.isTrackSoloed", args: { index: 0 }, kind: "read", module: "mixer" },
  { method: "mixer.getTrackPeaks", args: { index: 0, mode: 0 }, kind: "read", module: "mixer" },
  {
    method: "mixer.setTrackName",
    args: { index: 1, name: "verify-probe" },
    kind: "write",
    module: "mixer",
  },
  {
    method: "mixer.setTrackVolume",
    args: { index: 1, value: 0.8 },
    kind: "write",
    module: "mixer",
  },
  {
    method: "mixer.setTrackPan",
    args: { index: 1, value: 0.0 },
    kind: "write",
    module: "mixer",
  },
  {
    method: "mixer.setTrackColor",
    args: { index: 1, color: 0x808080 },
    kind: "write",
    module: "mixer",
  },
  { method: "mixer.muteTrack", args: { index: 1, value: -1 }, kind: "write", module: "mixer" },
  { method: "mixer.soloTrack", args: { index: 1, value: -1 }, kind: "write", module: "mixer" },
  { method: "mixer.armTrack", args: { index: 1 }, kind: "write", module: "mixer" },
  {
    method: "mixer.linkChannelToTrack",
    args: { channel: 0, track: 1, select: 0 },
    kind: "write",
    module: "mixer",
  },
  { method: "mixer.linkTrackToChannel", args: { mode: 0 }, kind: "write", module: "mixer" },
  {
    method: "mixer.setRouteTo",
    args: { source: 1, dest: 0, value: -1 },
    kind: "write",
    module: "mixer",
  },
  { method: "mixer.afterRoutingChanged", args: {}, kind: "write", module: "mixer" },
  {
    method: "mixer.setRouteToLevel",
    args: { source: 1, dest: 0, level: 1.0 },
    kind: "write",
    module: "mixer",
  },
  {
    method: "mixer.setEqGain",
    args: { index: 1, band: 0, value: 0.5 },
    kind: "write",
    module: "mixer",
  },
  {
    method: "mixer.setEqFrequency",
    args: { index: 1, band: 0, value: 0.5 },
    kind: "write",
    module: "mixer",
  },
  { method: "mixer.setCurrentTempo", args: { bpm: 120.0 }, kind: "write", module: "mixer" },

  // -- patterns ----------------------------------------------------------
  { method: "patterns.patternCount", args: {}, kind: "read", module: "patterns" },
  { method: "patterns.patternNumber", args: {}, kind: "read", module: "patterns" },
  { method: "patterns.getPatternName", args: { index: 1 }, kind: "read", module: "patterns" },
  { method: "patterns.getPatternColor", args: { index: 1 }, kind: "read", module: "patterns" },
  { method: "patterns.getPatternLength", args: { index: 1 }, kind: "read", module: "patterns" },
  {
    method: "patterns.selectPattern",
    args: { index: 1, value: -1, preview: 0 },
    kind: "write",
    module: "patterns",
  },
  { method: "patterns.jumpToPattern", args: { index: 1 }, kind: "write", module: "patterns" },
  {
    method: "patterns.setPatternName",
    args: { index: 1, name: "verify-probe" },
    kind: "write",
    module: "patterns",
  },
  {
    method: "patterns.setPatternColor",
    args: { index: 1, color: 0x808080 },
    kind: "write",
    module: "patterns",
  },
  {
    method: "patterns.setPatternLength",
    args: { index: 1, length: 16 },
    kind: "write",
    module: "patterns",
  },

  // -- playlist ----------------------------------------------------------
  { method: "playlist.trackCount", args: {}, kind: "read", module: "playlist" },
  { method: "playlist.getTrackName", args: { index: 1 }, kind: "read", module: "playlist" },
  { method: "playlist.getTrackColor", args: { index: 1 }, kind: "read", module: "playlist" },
  { method: "playlist.isTrackMuted", args: { index: 1 }, kind: "read", module: "playlist" },
  { method: "playlist.getDisplayZone", args: {}, kind: "read", module: "playlist" },

  // -- plugins -----------------------------------------------------------
  {
    method: "plugins.getPluginName",
    args: { index: 0, slotIndex: -1 },
    kind: "read",
    module: "plugins",
  },
  {
    method: "plugins.getParamCount",
    args: { index: 0, slotIndex: -1 },
    kind: "read",
    module: "plugins",
  },
  {
    method: "plugins.getParamName",
    args: { index: 0, paramIndex: 0, slotIndex: -1 },
    kind: "read",
    module: "plugins",
  },
  {
    method: "plugins.getParamValue",
    args: { index: 0, paramIndex: 0, slotIndex: -1 },
    kind: "read",
    module: "plugins",
  },
  {
    method: "plugins.setParamValue",
    args: { index: 0, paramIndex: 0, value: 0.5, slotIndex: -1 },
    kind: "write",
    module: "plugins",
  },
  { method: "plugins.nextPreset", args: { channel: 0 }, kind: "write", module: "plugins" },
  { method: "plugins.prevPreset", args: { channel: 0 }, kind: "write", module: "plugins" },

  // -- arrangement -------------------------------------------------------
  { method: "arrangement.currentTime", args: { snap: 0 }, kind: "read", module: "arrangement" },

  // -- ui ----------------------------------------------------------------
  { method: "ui.getVisible", args: { widget: 0 }, kind: "read", module: "ui" },
  { method: "ui.getFocusedFormID", args: {}, kind: "read", module: "ui" },
];

// ---------------------------------------------------------------------------
// Audit lookup — failure suggestions sourced from bridge-contract-audit.md
// ---------------------------------------------------------------------------

const AUDIT_HINTS: Record<string, string> = {
  "mixer.setCurrentTempo":
    "manual-only API; vendor pattern is REC-event tempo (general.processRECEvent with REC_Tempo)",
  "mixer.setRouteToLevel":
    "manual-only API; vendor-confirmed alternative is mixer.setRouteTo(src, dest, -1) for toggle",
  "mixer.setEqGain":
    "vendor arg order is ambiguous — try (selected_track, fader_index, value) vs (fader_index, value, selected_track)",
  "mixer.setEqFrequency": "manual-only API; no vendor precedent — probe both arg orderings",
  "mixer.linkChannelToTrack":
    "manual-only API; vendor-confirmed alternative is mixer.linkTrackToChannel(mode)",
  "general.getRecPPB": "manual-only API; vendor uses general.getRecPPQ instead",
  "arrangement.currentTime":
    "manual-only API; vendor uses arrangement.currentTimeHint(mode) instead",
  "transport.getSongLength": "manual-only API; no vendor caller — confirm or drop",
  "ui.getFocusedFormID": "manual-only API; no vendor caller — confirm or drop",
};

// ---------------------------------------------------------------------------
// Result classification + per-probe runner
// ---------------------------------------------------------------------------

type Status = "ok" | "fail" | "timeout" | "skip";

interface Result {
  method: string;
  module: string;
  kind: ProbeKind;
  status: Status;
  value?: unknown;
  error?: string;
  hint?: string;
}

function shouldSkip(probe: Probe, includeWrites: boolean): boolean {
  if (probe.kind === "internal" || probe.kind === "read") return false;
  return !includeWrites;
}

function classifyError(message: string): { status: Status; hint?: string } {
  if (/timed out/i.test(message)) return { status: "timeout" };
  // AttributeError surfaces from the FL side as "AttributeError: module 'X' has no attribute 'Y'"
  return { status: "fail" };
}

function fmtValue(v: unknown): string {
  if (v === undefined) return "undefined";
  if (typeof v === "string") return JSON.stringify(v);
  if (typeof v === "object") {
    try {
      const s = JSON.stringify(v);
      return s.length > 80 ? s.slice(0, 77) + "..." : s;
    } catch {
      return String(v);
    }
  }
  return String(v);
}

async function runProbe(bridge: SocketBridge, probe: Probe, skipped: boolean): Promise<Result> {
  if (skipped) {
    return {
      method: probe.method,
      module: probe.module,
      kind: probe.kind,
      status: "skip",
    };
  }
  try {
    const result = await bridge.call(probe.method, probe.args);
    return {
      method: probe.method,
      module: probe.module,
      kind: probe.kind,
      status: "ok",
      value: result,
    };
  } catch (err) {
    const message =
      err instanceof BridgeError ? err.message : err instanceof Error ? err.message : String(err);
    const cls = classifyError(message);
    const hint = AUDIT_HINTS[probe.method];
    return {
      method: probe.method,
      module: probe.module,
      kind: probe.kind,
      status: cls.status,
      error: message,
      hint,
    };
  }
}

// ---------------------------------------------------------------------------
// Reporting
// ---------------------------------------------------------------------------

function statusEmoji(s: Status): string {
  switch (s) {
    case "ok":
      return "✅";
    case "fail":
      return "❌";
    case "timeout":
      return "🟡";
    case "skip":
      return "⏭️";
  }
}

function summarize(results: Result[]): {
  byModule: Map<string, { ok: number; fail: number; timeout: number; skip: number }>;
  totals: { ok: number; fail: number; timeout: number; skip: number };
} {
  const byModule = new Map<string, { ok: number; fail: number; timeout: number; skip: number }>();
  const totals = { ok: 0, fail: 0, timeout: 0, skip: 0 };
  for (const r of results) {
    const mod = r.module;
    let bucket = byModule.get(mod);
    if (!bucket) {
      bucket = { ok: 0, fail: 0, timeout: 0, skip: 0 };
      byModule.set(mod, bucket);
    }
    bucket[r.status]++;
    totals[r.status]++;
  }
  return { byModule, totals };
}

const MODULE_ORDER = [
  "ping",
  "state",
  "transport",
  "general",
  "channels",
  "mixer",
  "patterns",
  "playlist",
  "plugins",
  "arrangement",
  "ui",
];

function printSummary(results: Result[]): void {
  const { byModule, totals } = summarize(results);
  process.stdout.write(`[verify] ============ SUMMARY ============\n`);
  for (const mod of MODULE_ORDER) {
    const b = byModule.get(mod);
    if (!b) continue;
    process.stdout.write(
      `[verify]   ${mod.padEnd(11)} : ${b.ok} ✅ / ${b.fail} ❌ / ${b.timeout} 🟡 / ${b.skip} ⏭️\n`,
    );
    for (const r of results) {
      if (r.module !== mod || r.status !== "fail") continue;
      process.stdout.write(`[verify]     ❌ ${r.method} — ${r.error}\n`);
    }
  }
  process.stdout.write(
    `[verify] OVERALL: ${totals.ok} ✅ / ${totals.fail} ❌ / ${totals.timeout} 🟡 / ${totals.skip} ⏭️\n`,
  );
}

async function writeReport(
  results: Result[],
  reportPath: string,
  flVersion: string | null,
  includeWrites: boolean,
): Promise<void> {
  const { byModule, totals } = summarize(results);
  const lines: string[] = [];
  lines.push(`# Live Verification Report`);
  lines.push(``);
  lines.push(`- **Timestamp:** ${new Date().toISOString()}`);
  lines.push(`- **FL version:** ${flVersion ?? "unknown (ui.getVersion not available)"}`);
  lines.push(`- **Include writes:** ${includeWrites ? "yes" : "no"}`);
  lines.push(``);
  lines.push(`## Totals`);
  lines.push(``);
  lines.push(
    `${totals.ok} ✅ ok / ${totals.fail} ❌ fail / ${totals.timeout} 🟡 timeout / ${totals.skip} ⏭️ skipped (total ${results.length})`,
  );
  lines.push(``);
  lines.push(`## Per-module summary`);
  lines.push(``);
  lines.push(`| Module | ✅ | ❌ | 🟡 | ⏭️ |`);
  lines.push(`| --- | --- | --- | --- | --- |`);
  for (const mod of MODULE_ORDER) {
    const b = byModule.get(mod);
    if (!b) continue;
    lines.push(`| ${mod} | ${b.ok} | ${b.fail} | ${b.timeout} | ${b.skip} |`);
  }
  lines.push(``);
  lines.push(`## Per-method results`);
  lines.push(``);
  lines.push(`| Status | Method | Detail |`);
  lines.push(`| --- | --- | --- |`);
  for (const r of results) {
    const detail =
      r.status === "ok"
        ? fmtValue(r.value)
        : r.status === "skip"
          ? r.kind === "audible"
            ? "skipped (audible; --include-writes to test)"
            : "skipped (write-side; --include-writes to test)"
          : (r.error ?? "");
    const escaped = detail.replace(/\|/g, "\\|").replace(/\n/g, " ");
    lines.push(`| ${statusEmoji(r.status)} | \`${r.method}\` | ${escaped} |`);
  }
  lines.push(``);
  const failures = results.filter((r) => r.status === "fail");
  if (failures.length > 0) {
    lines.push(`## Suggested actions for failures`);
    lines.push(``);
    for (const r of failures) {
      lines.push(`### \`${r.method}\``);
      lines.push(``);
      lines.push(`- **Error:** ${r.error}`);
      if (r.hint) {
        lines.push(`- **Audit hint:** ${r.hint}`);
      } else if (/AttributeError/.test(r.error ?? "")) {
        lines.push(
          `- **Audit hint:** AttributeError — the FL module does not expose this name on this build. Check the bridge-contract-audit for a vendor-confirmed alternative.`,
        );
      }
      lines.push(``);
    }
  }
  mkdirSync(dirname(reportPath), { recursive: true });
  writeFileSync(reportPath, lines.join("\n"), "utf8");
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

function parseArgs(argv: string[]): { includeWrites: boolean } {
  return { includeWrites: argv.includes("--include-writes") };
}

async function main(): Promise<number> {
  const { includeWrites } = parseArgs(process.argv.slice(2));
  const config = loadConfig();
  const host = config.bridge.host;
  const port = config.bridge.port;

  const up = await waitForBridge(host, port);
  if (!up) {
    process.stdout.write(
      `[verify] FAILED: bridge not reachable on ${host}:${port} after ${WAIT_TIMEOUT_SECONDS}s.\n` +
        `[verify] See docs/INSTALL.md for FL Studio device-script setup.\n`,
    );
    return 2;
  }

  const bridge = new SocketBridge({
    host,
    port,
    connectTimeoutMs: config.bridge.connectTimeoutMs,
    // verify-live needs a generous per-call budget because some probes
    // (e.g. peaks, plugin params) can stall on idle ticks at the upper
    // end of the Q5 OnIdle cadence.
    requestTimeoutMs: Math.max(config.bridge.requestTimeoutMs, 2000),
  });

  // Best-effort FL version. Not in the DISPATCH table, so it might be
  // absent on the bridge side — silently fall through.
  let flVersion: string | null = null;
  try {
    const v = await bridge.call("ui.getVersion", {});
    if (typeof v === "string") flVersion = v;
  } catch {
    // Not in DISPATCH on the current build — fine, leave null.
  }

  process.stdout.write(
    `[verify] bridge live, starting verification (${PROBES.length} methods to probe)\n`,
  );

  const results: Result[] = [];
  for (const probe of PROBES) {
    const skipped = shouldSkip(probe, includeWrites);
    const argStr = Object.keys(probe.args).length === 0 ? "" : `(${JSON.stringify(probe.args)})`;
    process.stdout.write(`[verify] ${probe.method}${argStr}... `);
    const r = await runProbe(bridge, probe, skipped);
    results.push(r);
    if (r.status === "ok") {
      process.stdout.write(`✅ ${fmtValue(r.value)}\n`);
    } else if (r.status === "skip") {
      const reason =
        probe.kind === "audible"
          ? "audible; --include-writes to test"
          : "write; --include-writes to test";
      process.stdout.write(`⏭️ skipped (${reason})\n`);
    } else if (r.status === "timeout") {
      process.stdout.write(`🟡 timeout — ${r.error}\n`);
    } else {
      process.stdout.write(`❌ ${r.error}\n`);
    }
  }

  printSummary(results);

  const __filename = fileURLToPath(import.meta.url);
  const repoRoot = resolve(dirname(__filename), "..");
  const reportPath = resolve(repoRoot, "docs", "LIVE-VERIFY-REPORT.md");
  await writeReport(results, reportPath, flVersion, includeWrites);
  process.stdout.write(`[verify] report written to ${reportPath}\n`);

  const failures = results.filter((r) => r.status === "fail");
  if (failures.length > 0) {
    process.stdout.write(
      `[verify] suggested next action: ${failures.length} failures — see ${reportPath} for vendor-confirmed alternatives.\n`,
    );
    return 1;
  }
  process.stdout.write(`[verify] all green.\n`);
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    process.stderr.write(
      `[verify] CRASHED: ${err instanceof Error ? (err.stack ?? err.message) : String(err)}\n`,
    );
    process.exit(2);
  });
