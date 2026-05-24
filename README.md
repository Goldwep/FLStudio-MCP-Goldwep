# FL Studio MCP — Goldwep

MCP server for FL Studio (Image-Line). Full-spectrum control surface — composition _and_ project inspection — for LLM workflows. Built on a localhost bridge into FL Studio's bundled Python 3.12 MIDI scripting environment, with `.pyscript` deploy + PyFLP project intelligence as auxiliary surfaces.

**110 tools registered across 9 milestones.**

> **Status (2026-05-23): v0.9.1-pre-bridge.** Tool surface complete (110 tools registered), but the bridge transport is not yet wired — most FL-API tools throw `BRIDGE_NOT_READY` against `StubBridge` until the L0 probe completes and a real transport (TCP socket or virtual MIDI) lands. Honest functional status: **~14 tools work today** (the L6 `.pyscript` deploys + L7 PyFLP scans + L8b's pure-TS snapshot/diff + `ping`). The other ~96 register correctly and pass schema validation but will reject at the bridge layer until v1.0.
>
> A 5-reviewer audit cycle (L1 friendly → L5 pathological, 77 raw findings, ~30 unique after dedup) plus a vendor-script audit of every `bridge.call` (62 vendor-confirmed, 10 docs-only flagged `[unverified]`, 8 invented/rescued) is documented in [docs/AUDIT-CYCLE.md](./docs/AUDIT-CYCLE.md) and `_scratch/flstudio-mcp-research/bridge-contract-audit.md`. The original `v1.0.0` tag is retained for history; `v1.0` proper waits for transport. Run the probe ([docs/L0-PROBE-RUN.md](./docs/L0-PROBE-RUN.md)) to unblock.

## Architecture

```
┌──────────────┐  stdio   ┌──────────────────┐   socket / MIDI   ┌─────────────────────────┐
│ Claude /     │ ───────▶ │ flstudio-mcp     │ ──────────────▶   │ device_FLStudioMCP.py   │
│ MCP client   │ ◀─────── │ (Node, this repo)│ ◀──────────────   │ (runs inside FL Studio) │
└──────────────┘          └──────┬───────────┘                   └────────────┬────────────┘
                                 │                                            │
                                 │ subprocess                  channels / mixer / patterns /
                                 ▼                            transport / playlist / plugins /
                          ┌──────────────┐                    arrangement / ui / general
                          │ pyflp_helper │ ──▶ reads .flp files (offline analysis)
                          │ (Python 3.13)│
                          └──────────────┘
                                 │
                                 ▼
                          ┌──────────────┐
                          │ .pyscript    │ ──▶ deployed to FL's Settings\Scripts\ for
                          │ generator    │     piano-roll-scope note CRUD (user-triggered)
                          └──────────────┘
```

**Three surfaces:**

| Surface                                  | Tools | Connectivity                                                                                                            | Notes                                                                                        |
| ---------------------------------------- | ----- | ----------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| **Live bridge** (L1/L2/L4/L5/L8)         | ~85   | TCP socket or virtual MIDI into the in-FL device script. Real-time read/mutate over FL's MIDI Controller Scripting API. | Gated on L0 probe selecting transport. Architecture is transport-agnostic at the tool layer. |
| **PyFLP project intel** (L7)             | 8     | Out-of-process Python subprocess. No FL needed.                                                                         | Reads `.flp` files on disk. PyFLP `pip install --user pyflp` required.                       |
| **Piano Roll `.pyscript` dispatch** (L6) | 6     | File deploy to FL scripts dir. User invokes via Ctrl+Alt+Y.                                                             | v1.0 ships deploy-only; auto-trigger in v1.1.                                                |

FL Studio 2024 ships Python 3.12.1 (verified) at `Shared\Python\` with the full CPython stdlib in `python312.zip` — `socket`, `threading`, `queue`, `ssl`, `asyncio` all import cleanly inside the embedded interpreter. The widely-cited "3.9 sandbox with threading stripped" community claim is **outdated** for FL 2024.

## Install

### Dev install (Windows)

```powershell
git clone https://github.com/Goldwep/FLStudio-MCP-Goldwep.git
cd FLStudio-MCP-Goldwep
npm install
npm run build
```

### Run the L0 probe (one-time, ~2 minutes)

Required to lock bridge transport before live FL calls work. See [docs/L0-PROBE-RUN.md](./docs/L0-PROBE-RUN.md). The probe script is already installed at:

```
%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP-Probe\
```

Open FL Studio, set "Controller type" to "FLStudio MCP Probe", wait ~15 seconds, reload the script once, then read `probe_results.json` from the same folder.

### Optional: L7 PyFLP project intelligence

The `flp_*` tools (project scanning, plugin inventory, tempo distribution, missing-samples check) parse `.flp` files off disk via a Python subprocess — they don't need FL Studio running. One-time setup:

```powershell
"C:\Users\<you>\AppData\Local\Programs\Python\Python313\python.exe" -m pip install --user pyflp
```

See [docs/L7-PYFLP-SETUP.md](./docs/L7-PYFLP-SETUP.md) for verification, env-var overrides (`FLSTUDIO_MCP_PYTHON`, `FLSTUDIO_MCP_PYFLP_HELPER`), and behavior notes. Tools fail gracefully if PyFLP isn't installed.

### Optional: L6 piano-roll `.pyscript` dispatch

Deploy target defaults to `%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Scripts\` (auto-created). Override with `FLSTUDIO_MCP_SCRIPTS_DIR` env var. No external setup needed.

### Claude Code (Windows)

```powershell
claude mcp add --scope user flstudio-mcp -- cmd /c node "C:\Users\<you>\Documents\GitHub\FLStudio-MCP-Goldwep\dist\index.js"
```

### Claude Desktop

Add to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "flstudio-mcp": {
      "command": "node",
      "args": ["C:\\Users\\<you>\\Documents\\GitHub\\FLStudio-MCP-Goldwep\\dist\\index.js"]
    }
  }
}
```

Restart Claude. Verify with `/mcp`.

## Usage

After the L0 probe locks the bridge transport, ask Claude things like:

- _"What channels are in my project?"_
- _"Set mixer track 3 volume to 0.7 and arm it for recording."_
- _"Build a 4-on-the-floor kick pattern on channel 0."_
- _"Set the tempo to 128 BPM and toggle the metronome on."_
- _"Stream this melody into channel 1: C4, E4, G4, C5 with quarter-note durations."_
- _"Save the project — but first check if it has unsaved changes."_

L7 PyFLP tools work without FL running:

- _"Scan my Projects folder and tell me which projects use Serum."_
- _"What's the tempo distribution across my last 50 projects?"_
- _"Check this project for missing sample paths."_

L6 piano-roll tools generate `.pyscript` files for the user to invoke:

- _"Generate a piano-roll script that transposes all notes up an octave."_ → script deployed to FL's scripts dir → user opens piano roll → Ctrl+Alt+Y → effect applied.

## Tool surface

109 tools across 13 modules. Full per-tool scoring with green/yellow caveats in [docs/DOMAIN-MAP.md](./docs/DOMAIN-MAP.md).

| Module                          | Tools                                                                                                                                                                                                                                                                  | Notes                                                                                               |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| **system**                      | `ping`                                                                                                                                                                                                                                                                 | Sanity / health                                                                                     |
| **transport** (live)            | `transport_play`, `transport_stop`, `transport_is_playing`, `transport_set_tempo`, `transport_set_loop_mode`, `transport_set_song_pos`, `transport_toggle_metronome`, `transport_tap_tempo`, `transport_record`, `transport_get_song_pos`, `transport_get_song_length` | Play/stop, tempo (direct setter, no REC plumbing), loop, position, metronome, tap-tempo, record arm |
| **channels** (live)             | 15 incl. `channels_count`, `channel_get_*` (name/color/volume/pan/target*fx/type), `channel_set*\*`(name/volume/pan/color/target_fx),`channel_select/mute/solo`                                                                                                        | 0-indexed channel rack                                                                              |
| **channels (step grid)** (live) | 9 incl. `channel_get_step_bit`, `channel_set_step_bit`, `channel_toggle_step`, `channel_get_step_param`, `channel_set_step_param`, `channel_set_step_row`, `channel_clear_pattern_steps`, `channel_step_pattern_build`, `pattern_set_length`                           | The cleanest composition surface; works fully within FL's hard limits                               |
| **mixer** (live)                | 18 incl. `mixer_track_count`, `mixer_get_*` (name/color/vol/pan/mute/solo/peaks), `mixer_set_*` (name/vol/pan/color/route/send/eq_gain/eq_freq), `mixer_mute_track`, `mixer_solo_track`, `mixer_arm_track`, `mixer_link_channel_to_track`                              | 0-indexed (0=Master). Direct setters for send/EQ (not REC plumbing).                                |
| **patterns** (live)             | 9 incl. `patterns_count`, `patterns_current_number`, `patterns_get_*` (name/color/length), `patterns_select`, `patterns_jump_to`, `patterns_set_*` (name/color)                                                                                                        | 1-indexed. Picker selection ≠ playback marker.                                                      |
| **playlist** (live, read-only)  | 5 incl. `playlist_track_count`, `playlist_get_track_*` (name/color), `playlist_is_track_muted`, `playlist_get_display_zone`                                                                                                                                            | 1-indexed. No clip CRUD (hard limit — trigger only).                                                |
| **plugins** (live)              | 6 incl. `plugins_get_*` (name/param count/param name/param value), `plugins_set_param` (with `pickupMode` + `useGlobalIndex`), `plugins_change_preset`                                                                                                                 | Dual addressing: `slotIndex=-1` = channel-rack instrument; ≥0 = mixer effect slot                   |
| **general** (live)              | 5 incl. `general_get_project_title`, `general_undo`, `general_save_project`, `general_get_changed_flag`, `general_get_rec_ppb`, `general_get_use_metronome`                                                                                                            | Save, undo, metadata                                                                                |
| **arrangement / ui** (live)     | 3: `arrangement_current_time`, `ui_get_visible`, `ui_get_focused_form_id`                                                                                                                                                                                              | Window focus, snap-based time                                                                       |
| **live composition** (L8a)      | 6 incl. `live_arm_record`, `live_play_note_now`, `live_release_note`, `live_play_chord_now`, `live_stream_notes`, `live_get_record_state`                                                                                                                              | Real-time note streaming; if FL armed+playing → records; else previews                              |
| **state sync** (L8b)            | 4: `state_subscribe`, `state_get_changes`, `state_snapshot`, `state_diff_snapshots`                                                                                                                                                                                    | Subscribe via bridge-side flag (not a callback registration). Drain accumulated dirty events.       |
| **piano roll deploy** (L6)      | 6: `piano_roll_deploy_add_notes/clear_pattern/transpose/quantize/velocity_set`, `piano_roll_list_deployed`                                                                                                                                                             | Generates `.pyscript` files. User invokes via Ctrl+Alt+Y in FL's Piano Roll.                        |
| **PyFLP project intel** (L7)    | 8: `flp_scan_folder`, `flp_inspect`, `flp_get_plugins`, `flp_get_samples`, `flp_check_missing_samples`, `flp_tempo_distribution`, `flp_plugin_inventory`, `flp_get_pattern_summary`                                                                                    | Out-of-process. PyFLP via subprocess. Independent of FL.                                            |

## Hard limits (architectural walls, not bugs)

These are pinned by FL's API surface and don't move with effort:

- **No real-time piano-roll note CRUD** from the MIDI Controller scope. Workarounds: live `channels.midiNoteOn` during record (L8a), step-grid composition (L5), Piano Roll `.pyscript` dispatch (L6), or PyFLP read-only (L7).
- **No playlist clip insert/move/resize** at runtime. Trigger-only.
- **No programmatic plugin loading.** User adds VST/native plugins manually; scripts can then address them via `(index, slotIndex)`.
- **No programmatic pattern creation.** Patterns must exist before scripts populate them.
- **Piano Roll `.pyscript` is scope-locked** — cannot reach mixer, playlist, channels from that surface.

See [docs/DOMAIN-MAP.md](./docs/DOMAIN-MAP.md) and [the brain doc](https://github.com/Goldwep/Claude-Brain/blob/main/projects/flstudio_mcp_goldwep.md) for the full picture.

## Project layout

```
src/
  index.ts            MCP server entrypoint (stdio transport)
  server.ts           tool registration graph (all 109 tools wired here)
  config.ts           bridge config (mode: stub | socket | midi)
  bridge/             transport-agnostic Bridge interface + StubBridge
  pyflp/runner.ts     subprocess wrapper for the PyFLP helper
  pyscript/           .pyscript generator + deployer
  tools/              one TS module per FL module concern (channels, mixer, ...)
  utils/              logger
bridge/
  probes/             L0 probe script (FLStudio-MCP-Probe device script)
  pyflp_helper.py     out-of-process PyFLP scanner (Python 3.13)
docs/
  DOMAIN-MAP.md       priced tool roadmap (L3 audit deliverable)
  L0-PROBE-RUN.md     probe install + run instructions
  L7-PYFLP-SETUP.md   PyFLP install + override notes
  PROBE-REPORT.md     architecture lock decisions (template until probe lands)
scripts/
  smoke.ts            in-process tool registration smoke test
```

## Development workflow

```powershell
npm run build           # tsc -p tsconfig.build.json
npm run dev             # tsx src/index.ts (stdio server)
npx tsx scripts/smoke.ts  # verify tool count + ping round-trip
npm run lint
npm run format
```

## Roadmap

| Milestone                            | Status        | New tools | Cumulative |
| ------------------------------------ | ------------- | --------- | ---------- |
| L0 — Foundation probe                | ✅ shipped    | 0         | 0          |
| L1 — Bridge foundation               | ✅ shipped    | 5         | 5          |
| L2 — Inspection breadth              | ✅ shipped    | 36        | 41         |
| L3 — Domain feasibility audit        | ✅ shipped    | 0         | 41         |
| L4 — Mutation breadth + critic adds  | ✅ shipped    | 35        | 76         |
| L5 — Composition v1 (step grid)      | ✅ shipped    | 9         | 85         |
| L8a — Live composition               | ✅ shipped    | 6         | 91         |
| L8b — State sync                     | ✅ shipped    | 4         | 95         |
| L7 — PyFLP project intel             | ✅ shipped    | 8         | 103        |
| L6 — Piano Roll `.pyscript` dispatch | ✅ shipped    | 6         | 109        |
| L9 — Polish + v1.0 release           | _in progress_ | 0         | 109        |
| **v1.1+**                            | _planned_     | —         | —          |

### v1.1+ targets

- **Bridge transport implementation** (TCP socket or virtual MIDI, gated on L0 probe results)
- **State-sync deep snapshot** (loop through every channel/track for full state object)
- **Piano-roll auto-trigger** (FL Studio Remote API or keystroke automation; user no longer needs Ctrl+Alt+Y)
- **L4 EQ extras** (Q, band type, dock-side, more send routing)
- **`OnDirty*` event payload coalescing** (dedupe repeats within a single drain window)
- **FL Studio Remote API spike** (third Python scripting surface, currently unexplored by any community MCP)

## Credits

- Designed and built by [Goldwep](https://github.com/Goldwep). Built with [Claude Code](https://claude.com/claude-code) — heavy parallel delegation across L milestones (one delegate fleet per L2/L4 module, plus targeted critic + scaffolding agents).
- Heavy debt to [MaddyGuthridge/FL-Studio-API-Stubs](https://github.com/MaddyGuthridge/FL-Studio-API-Stubs) — de facto canonical API reference for FL's Python scripting modules, better than Image-Line's own docs in places.
- PyFLP by [demberto](https://github.com/demberto/PyFLP) — the canonical reverse-engineered `.flp` parser. Used read-only for L7.
- Architectural sibling: [Enfusion-Workbench-MCP-Goldwep](https://github.com/Goldwep/Enfusion-Workbench-MCP-Goldwep) — same Node/TS + in-DAW Python bridge pattern, ported from Arma Reforger modding to music production.
- FL Studio is a trademark of [Image-Line NV](https://www.image-line.com/). This is an independent community tool and is not affiliated with or endorsed by Image-Line NV.

## License

[MIT](./LICENSE).
