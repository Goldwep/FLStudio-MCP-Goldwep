# Domain Feasibility Map — L3 Audit Gate

> **Purpose:** Convert the hand-waved L4-L8 plan into a priced roadmap. Every proposed tool is scored against verified API surface from the 9-agent research sweep + the 6-agent L2 implementation pass + `midi.py` constants + bundled vendor scripts.
>
> **Tool count projection:** L1+L2 shipped 41 tools. L4-L8 proposes 68. Final v1.0 surface: **~109 tools** (above the ~100 target — trim list is below).

## Color legend

| Tag | Meaning | Action |
|---|---|---|
| 🟢 **green** | API verified, signature confirmed, vendor-script precedent OR il-group stub | Ship as planned |
| 🟡 **yellow** | API exists but semantics ambiguous OR no vendor precedent OR needs L0 probe data | Ship with `[unverified]` flag in description; verify in implementation; one runtime probe |
| 🔴 **red** | API absent OR known unsupported OR architectural wall | Drop OR defer to post-v1.0 OR find workaround surface |

---

## L4 — Mutation breadth (~25 target, 29 proposed)

Write-side tools. Each toggle/setter is a single REC-event or named-mutator call. Group by FL module.

### channels module (8 tools)
| Tool | FL call | Color | Notes |
|---|---|---|---|
| `channel_set_name` | `channels.setChannelName(idx, name)` | 🟢 | Standard setter; vendor scripts use it (MackieCU naming probe). |
| `channel_set_volume` | `channels.setChannelVolume(idx, v)` or via `processRECEvent(REC_Chan_Vol + idx*REC_ItemRange)` | 🟢 | Both paths work; setChannelVolume direct is simpler. |
| `channel_set_pan` | `channels.setChannelPan(idx, p)` | 🟢 | Direct setter. |
| `channel_set_color` | `channels.setChannelColor(idx, bgra)` | 🟢 | BGRA int — match read-side decode in `channel_get_color`. |
| `channel_set_target_fx_track` | `channels.setTargetFxTrack(idx, fxIdx)` | 🟢 | Documented, vendor precedent. |
| `channel_select` | `channels.selectChannel(idx, value=-1)` | 🟢 | value=-1 toggles, 0/1 explicit. |
| `channel_mute` | `channels.muteChannel(idx, value=-1)` | 🟢 | Same toggle pattern. |
| `channel_solo` | `channels.soloChannel(idx)` | 🟢 | One-arg solo. |

### mixer module (10 tools)
| Tool | FL call | Color | Notes |
|---|---|---|---|
| `mixer_set_track_name` | `mixer.setTrackName(idx, name)` | 🟢 | Direct setter. |
| `mixer_set_track_volume` | `mixer.setTrackVolume(idx, v)` | 🟢 | Float 0..1 (NOT MIDI 0..127). |
| `mixer_set_track_pan` | `mixer.setTrackPan(idx, p)` | 🟢 | Float -1..+1. |
| `mixer_set_track_color` | `mixer.setTrackColor(idx, bgra)` | 🟢 | Match read-side. |
| `mixer_mute_track` | `mixer.muteTrack(idx, value=-1)` | 🟢 | Toggle / explicit. |
| `mixer_solo_track` | `mixer.soloTrack(idx, value=-1)` | 🟢 | Same. |
| `mixer_set_route` | `mixer.setRouteTo(src, dest, val)` + `mixer.afterRoutingChanged()` | 🟡 | **Both calls required** — missing `afterRoutingChanged` silently fails to propagate. Bridge must enforce the pair atomically. |
| `mixer_set_send_level` | `processRECEvent(getTrackPluginId(track,0) + REC_Mixer_Send_First + dest, val, REC_Controller)` | 🟡 | REC plumbing; verify path with empirical test. |
| `mixer_set_eq_gain` | `processRECEvent(getTrackPluginId(track,0) + REC_Mixer_EQ_Gain + band, val, ...)` | 🟡 | EQ has 8 bands per `midi.py` but visible strip EQ has 3 — clarify in description. |
| `mixer_set_eq_freq` | `processRECEvent(getTrackPluginId(track,0) + REC_Mixer_EQ_Freq + band, val, ...)` | 🟡 | Same. |

(EQ Q + EQ band type deferred to post-L4 — diminishing returns vs adding more breadth elsewhere.)

### patterns module (4 tools)
| Tool | FL call | Color | Notes |
|---|---|---|---|
| `patterns_select` | `patterns.selectPattern(idx, value=-1, preview=0)` | 🟢 | Picker selection (distinct from playback marker). |
| `patterns_jump_to` | `patterns.jumpToPattern(idx)` | 🟢 | Sets playback marker. |
| `patterns_set_name` | `patterns.setPatternName(idx, name)` | 🟢 | Direct setter. |
| `patterns_set_color` | `patterns.setPatternColor(idx, bgra)` | 🟢 | Match read-side. |

### transport / general (4 tools)
| Tool | FL call | Color | Notes |
|---|---|---|---|
| `transport_set_tempo` | `processRECEvent(REC_Tempo, val, REC_Controller)` | 🟢 | Canonical pattern from MackieCU line 227. Value encoding: tempo*1000 (e.g. 120 BPM = 120000). |
| `transport_set_loop_mode` | `transport.setLoopMode()` | 🟡 | **TOGGLE, no arg** — can't force specific mode without read-then-toggle. Tool exposes "toggle" semantics. |
| `transport_set_song_pos` | `transport.setSongPos(pos, mode=2)` | 🟢 | `mode` selects unit (SONGLENGTH_*); mode=2 = AbsTicks. |
| `general_undo` | `general.saveUndo(text, flags)` + `general.undo()` | 🟡 | Two calls; bridge composes. Undo grouping non-trivial. |

### plugins (2 tools)
| Tool | FL call | Color | Notes |
|---|---|---|---|
| `plugins_set_param` | `plugins.setParamValue(val, paramIdx, idx, slotIdx)` | 🟢 | Float 0..1. paramIdx is FIRST positional arg. |
| `plugins_next_preset` | `plugins.nextPreset(idx, slotIdx)` + `prevPreset` | 🟢 | Two tools rolled into one with `direction` arg. |

**L4 total:** 28 tools. Greens: 22 (79%). Yellows: 6 (21%). Reds: 0. **Ship as planned, with yellow descriptions flagging caveats.**

---

## L5 — Composition v1: step grid (~10 target, 9 proposed)

Step-sequencer composition. Works fully within hard limits (no piano-roll CRUD needed).

| Tool | FL call | Color | Notes |
|---|---|---|---|
| `channel_get_step_bit` | `channels.getGridBit(idx, pos)` | 🟢 | Documented + Akai Fire vendor heavy usage. |
| `channel_set_step_bit` | `channels.setGridBit(idx, pos, value)` | 🟢 | Mirror of get. |
| `channel_toggle_step` | get → set (compose) | 🟢 | Convenience; bridge implements server-side. |
| `channel_get_step_param` | `channels.getCurrentStepParam(idx, step, param)` | 🟢 | Returns step param (pitch/vel/pan/modX/modY/release/fine/shift) — see `midi.py` step param indices. |
| `channel_set_step_param` | `channels.setStepParameterByIndex(idx, pattern, step, param, value)` | 🟡 | **Silently no-ops if step bit = 0.** Bridge force-sets bit first, then sets param. |
| `channel_set_step_pattern` | composite: get all 16/32 bits, diff, setGridBit per step | 🟢 | Server-side composite tool for bulk pattern editing. |
| `channel_clear_pattern` | loop: setGridBit(idx, p, 0) for all p | 🟢 | Composite. |
| `pattern_set_length` | `patterns.setPatternLength(idx, length)` | 🟡 | Units uncertain (beats vs steps) — flag in description. |
| `channel_step_pattern_build` | composite from JSON spec: `{ pattern: [[1,0,1,0,1,0,1,0], ...] }` | 🟢 | High-leverage MCP tool — LLM-generates drum patterns from spec. |

**L5 total:** 9 tools. Greens: 7 (78%). Yellows: 2 (22%). Reds: 0. **Ship as planned. Step grid is the cleanest composition surface.**

---

## L6 — Piano Roll dispatch (~10 target, 10 proposed)

**Conditional on L0 probe Q3 outcome.** If `processRECEvent(REC_Chan_NoteOn,...)` is accepted → L6 collapses INTO L5 as REC-event-driven note tools. If rejected → L6 ships as Piano Roll `.pyscript` dispatch.

### Path A: REC-based (collapse into L5) — IF Q3 = accepted
| Tool | FL call | Color | Notes |
|---|---|---|---|
| `piano_roll_add_note` | `processRECEvent(REC_Chan_NoteOn + ch*REC_ItemRange, val, REC_Controller)` | 🟡 | Untested encoding; needs probe data. |
| `piano_roll_remove_note` | `REC_Chan_NoteOff` | 🟡 | Same caveat. |
| `piano_roll_clear_pattern` | composite loops | 🟡 | Same. |

### Path B: `.pyscript` dispatch — IF Q3 = rejected (default plan)
| Tool | FL call | Color | Notes |
|---|---|---|---|
| `piano_roll_add_notes` | generate `.pyscript` text using `flpianoroll` API → write to `Documents\Image-Line\FL Studio\Settings\Scripts\` → trigger via FL Studio Remote API OR keystroke automation | 🟡 | Trigger mechanism needs probe — keystroke automation is brittle. |
| `piano_roll_remove_notes` | same dispatch | 🟡 | |
| `piano_roll_set_note_pitch` | same | 🟡 | |
| `piano_roll_set_note_velocity` | same | 🟡 | |
| `piano_roll_set_note_duration` | same | 🟡 | |
| `piano_roll_set_note_position` | same | 🟡 | |
| `piano_roll_get_notes` | **NOT FEASIBLE via .pyscript scope-lock** — read piano-roll from a Controller script: 🔴 | 🔴 | Workaround: PyFLP read-only on saved project (L7 path), or no read. |
| `piano_roll_quantize` | dispatch | 🟡 | Standard `.pyscript` operation. |
| `piano_roll_transpose` | dispatch | 🟡 | Same. |

**L6 total:** 9 tools proposed for Path B + 3 collapsed into Path A. Greens: 0. Yellows: 8. Reds: 1 (`piano_roll_get_notes` via .pyscript scope-lock — workaround via PyFLP). **Highest-risk milestone — gated entirely on probe data.** If Q3=yes, L6 effective scope drops to 3-4 tools and the 2-week slot becomes 1 week (collapse into L5). **Recommendation: defer L6 implementation start until probe results land.**

---

## L7 — PyFLP project intelligence (~8 target, 8 proposed)

Out-of-process. Spawns Python subprocess; no FL needed. Independent code path.

| Tool | Implementation | Color | Notes |
|---|---|---|---|
| `flp_scan_folder` | glob `**/*.flp`, parse each via PyFLP, return summary | 🟢 | Tier-0 PyFLP capability. |
| `flp_get_metadata` | parse one file, return `{artist, title, tempo, time_signature, fl_version, channels_count, mixer_track_count}` | 🟢 | Standard PyFLP read. |
| `flp_get_plugins` | extract VST/native plugin list from file | 🟢 | PyFLP supports this. |
| `flp_get_samples` | extract sample path references | 🟢 | PyFLP supports. |
| `flp_check_missing_samples` | resolve each sample path, return missing list | 🟢 | Composite. |
| `flp_tempo_distribution` | scan folder, build tempo histogram | 🟢 | Composite. |
| `flp_plugin_inventory` | scan folder, count occurrences per plugin | 🟢 | Composite. |
| `flp_get_pattern_summary` | high-level pattern overview (note count per pattern) | 🟡 | PyFLP issue #200: FL 2025 playlist data breaks parsing. Best-effort + graceful degradation. |

**L7 total:** 8 tools. Greens: 7 (88%). Yellows: 1 (12%). Reds: 0. **Ship as planned. Low risk, high differentiation value.**

**Key dependency:** PyFLP must be installable via pip on a Python the MCP can spawn. User's system has Anaconda + Python 3.13 visible — `python -m pip install pyflp` from MCP-spawned subprocess should work. Verify in L7 implementation start.

---

## L8 — Live composition + state sync (~12 target, 12 proposed)

| Tool | Implementation | Color | Notes |
|---|---|---|---|
| `live_arm_record` | `transport.record()` toggle | 🟢 | Documented. |
| `live_play_note_now` | `channels.midiNoteOn(idx, note, velocity, channel=-1)` | 🟢 | Documented; works as preview OR record-input depending on FL state. |
| `live_play_chord_now` | composite: multiple `midiNoteOn` calls | 🟢 | Server-side. |
| `live_stream_notes` | sequence with timing; bridge handles spacing | 🟡 | Timing precision depends on OnIdle cadence — L0 probe Q5 informs. |
| `live_release_note` | `channels.midiNoteOn(idx, note, 0, ch=-1)` (velocity=0 = note-off) | 🟢 | Standard MIDI convention. |
| `live_stop_record` | `transport.record()` toggle | 🟢 | Same as arm. |
| `state_subscribe` | bridge registers callback handler for `OnDirty*`; accumulates dirty events | 🟡 | **Hard to verify pre-bridge.** Depends on bridge architecture finalizing in L1.5 post-probe. |
| `state_unsubscribe` | bridge releases callback handler | 🟡 | Same dep. |
| `state_get_changes` | drain accumulated dirty events queue | 🟡 | Same. |
| `state_snapshot` | composite: walks all L2 read tools, returns one giant object | 🟢 | Pure composition over existing read surface. |
| `state_diff_snapshots` | compare two snapshots, return delta | 🟢 | Pure logic. |
| `live_get_record_state` | derive from `transport.isRecording()` | 🟢 | Simple read. |

**L8 total:** 12 tools. Greens: 8 (67%). Yellows: 4 (33%). Reds: 0. **Ship as planned, with state_* tools gated on bridge architecture finalization.**

---

## Cross-cutting concerns (must surface in EVERY mutating tool's description)

These are gotchas the 9-agent sweep + L2 delegates surfaced that apply across modules. Bake them into tool descriptions and bridge-side handlers.

1. **PME re-entry guard.** Mutating helpers should only run when `event.pmeFlags & PME_System_Safe`. Bridge-side responsibility, not MCP tool surface.
2. **Color channels are BGRA little-endian int32.** Same for `channels`, `mixer`, `patterns`, `playlist`. All `*_set_color` tools document this.
3. **Volume normalization differs by module.** `channels.*` and `mixer.*` use 0..1 floats. Master vol via `REC_MainVol` uses different range. Document per-tool.
4. **Pan is -1..+1, stereo separation is -1..+1, peaks return ~1.1 cap.**
5. **PROCESS-rec value encoding varies by REC ID.** REC_Tempo expects BPM*1000. REC_Mixer_Vol expects float-as-int (the agent who implements L4 mutation must verify per-REC encoding via vendor scripts).
6. **`useGlobalIndex` flag inconsistency** on channels module — `False` default on most functions, `True` on `showGraphEditor`. Surface explicitly in any L4 channel tool that exposes it.
7. **Plugin addressing dual mode** — `slotIndex=-1` = channel-rack; `slotIndex>=0` = mixer effect slot. Already surfaced in L2 plugin tools; carry through to L4 `plugins_set_param`.
8. **`afterRoutingChanged()` MUST follow `setRouteTo()`.** Bridge enforces atomic pair.
9. **NKS metadata at param indices 0, 2048, 4096.** Bridge filters or exposes them with a flag — L4 `plugins_set_param` decision.
10. **Indexing convention split:** `channels` and `mixer` are 0-indexed; `playlist` and `patterns` are 1-indexed. Zod schemas enforce.

---

## Final v1.0 tool count

| Milestone | Tools | Status |
|---|---|---|
| L1 | 5 | shipped |
| L2 | 36 | shipped |
| L4 | 28 (22 green + 6 yellow) | planned |
| L5 | 9 (7 green + 2 yellow) | planned |
| L6 | 9 (if Q3=no) OR 3 (if Q3=yes — collapses into L5) | gated on probe |
| L7 | 8 (7 green + 1 yellow) | planned |
| L8 | 12 (8 green + 4 yellow) | planned |
| **v1.0 total** | **107** (if Q3=no) or **~101** (if Q3=yes) | |

Above the ~100 target either way. If we want to land exactly at ~100, trim candidates:
- Drop `mixer_set_eq_q` and `mixer_set_eq_band_type` (already deferred above)
- Drop `state_diff_snapshots` (pure logic — can do client-side)
- Drop `flp_get_pattern_summary` (yellow, error-prone)

**Locked target: ~100 tools at v1.0.** Trim list activates only if L6 ships full (Q3=no).

## Verification checklist before L4 starts

| Action | Owner | Status |
|---|---|---|
| L0 probe runs in FL → architecture lock | User OR computer-use spike | **pending** |
| If Q3=accepted: collapse L6 into L5; revise tool count | Main thread | gated |
| If Q1=dead: pivot transport to virtual MIDI (+2 weeks) | Main thread | gated |
| Bridge transport implementation lands (L1.5) | Either main thread or delegate | gated on probe |
| Bundled vendor script grep for L4-yellow tool encoding (`REC_Tempo`, `REC_Mixer_*`) | Delegate | scheduled |

---

**Lock decision:** L4 + L5 + L7 + L8 are GO. L6 is **deferred until probe lands**. If probe shows Q3=accepted, L6 collapses and we save 1-2 weeks. If Q3=rejected, ship L6 as `.pyscript` dispatch path (Path B) with `piano_roll_get_notes` as the one red dropped from scope.

**Next gate:** L4 mutation breadth. Estimate 2.5 weeks. Parallelizable via delegate fleet (~7 module agents, same pattern as L2).
