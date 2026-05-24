# v1.0.0 Release Checklist — Single-Command Path

> **Status:** Currently at **v1.0.0-rc2**. All code work is done. Single user action gates v1.0.0 final.

## The one-command path

After you have:

- FL Studio open
- Bridge device script deployed (already at `Settings\Hardware\FLStudio-MCP\device_FLStudioMCP.py`)

Do this:

1. **In FL Studio:** `F10` → MIDI Settings → pick an input port → Controller type = `"FLStudio MCP Bridge"` → click Enable.
2. **Confirm:** Script Output window (Ctrl+F12) shows a new tab `"FLStudio MCP Bridge"` with `[mcp-bridge] listening on 127.0.0.1:9876`.
3. **From repo root:**

   ```powershell
   npm run verify:live
   ```

That's it. The script:

- Polls port 9876 every 1s for up to 60s.
- Probes all 88 dispatch entries via the production SocketBridge.
- Categorizes results per method: ✅ working / ❌ broken / 🟡 timeout / ⏭️ skipped.
- Writes a full report to `docs/LIVE-VERIFY-REPORT.md`.
- For each ❌ AttributeError, suggests the vendor-script-confirmed alternative from `bridge-contract-audit.md`.

**Exit codes:**

- `0` — all green, ready for v1.0.0
- `1` — one or more ❌ failures (almost certainly the `[UNVERIFIED]` tools; apply the suggested renames)
- `2` — bridge unreachable (FL controller not assigned; see step 1)

## After verify-live exits 0

You're at v1.0.0. Final tag:

```powershell
# Update version in package.json + src/index.ts: "1.0.0-rc2" -> "1.0.0"
# Build + test + lint + format-check should all be clean
npm run build && npm test && npm run lint && npm run format:check

git add -A
git commit -m "v1.0.0 — live-verified against FL Studio"
git tag -a v1.0.0 -m "v1.0.0 final — bridge live, 88 dispatch entries verified"
git push origin main
git push origin v1.0.0

gh release create v1.0.0 --repo Goldwep/FLStudio-MCP-Goldwep \
  --title "v1.0.0 — FL Studio MCP" \
  --notes-file docs/LIVE-VERIFY-REPORT.md \
  --latest
```

## After verify-live exits 1 (failures)

Read `docs/LIVE-VERIFY-REPORT.md`. For each ❌, the suggested action will be one of:

- **Rename** — change `bridge.call("X.Y", ...)` in `src/tools/<module>.ts` to the vendor-confirmed name (the report suggests which).
- **Drop** — remove the tool from `src/tools/<module>.ts` and the registration call from `src/server.ts`.
- **Demote further** — leave the tool but ensure the `[UNVERIFIED]` flag is loud in the description.

After applying fixes, re-run `npm run verify:live`. Iterate until exit 0.

## Also worth running (one-off)

**Probe-2** — does `processRECEvent(REC_Chan_NoteOn,...)` actually add a note?

1. In FL: switch the input row's Controller type to **"FLStudio MCP Probe 2"** (script is already deployed at `Settings\Hardware\FLStudio-MCP-Probe-2\`).
2. Wait ~2 seconds.
3. Read `%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP-Probe-2\probe2_results.json`.

The `verdict` field tells you:

- `"MODIFIED"` — REC noteOn did add state. **L6 piano-roll dispatch can collapse** into REC-based live composition tools. Worth a v1.1 follow-up.
- `"NO-OP"` — REC noteOn was silently dropped. Keep L6 as-is (`.pyscript` deploy path).
- `"ALREADY-DIRTY"` — project was already modified before the call; rerun on a clean blank project.
- `"no-channel"` — need at least one channel in the rack; add one and rerun.

This is informational — doesn't block v1.0.0. The `live_play_note_now` / `live_play_chord_now` / `live_stream_notes` tools already use `channels.midiNoteOn` (vendor-confirmed) which works regardless.

## What's already verified (no action needed)

- Bridge code paths (88/88 entries) — exercised via `tests/bridge_device_smoke.py` against mocked FL modules.
- SocketBridge — 5 unit tests (connect/ok/error/timeout/out-of-order).
- Smoke test — `npm test` (4/9 smoke + 5/9 socket-bridge = 9/9 pass).
- Build, lint, format — all clean.

The mock smoke exercises the same dispatch + framing + error code paths as live FL — what `verify:live` adds is verification that **the FL modules actually expose the methods we expect** for the `[UNVERIFIED]` 10.
