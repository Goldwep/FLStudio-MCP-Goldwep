# Audit Cycle — 5 Reviewers, Escalating Antagonism

> **Date:** 2026-05-23, post-v1.0.0 tag.
> **Method:** 5 parallel delegate agents, each holding the v1.0.0 codebase to a different bar — friendly peer → skeptical senior → adversarial red-team → hostile PR-blocker → pathological adversary.
> **Verdict:** **v1.0 label is wrong.** Three independent reviewers (L3 CRITICAL, L4 hostile, L5 EXISTENTIAL) flagged the same thing: the primary tool surface is a stub. Either implement bridge transport, OR re-tag as `v0.9-pre-bridge` and reserve `v1.0` for "transport wired."

## Top-line verdicts

| Reviewer | Findings | Verdict |
|---|---|---|
| L1 friendly | 7 polish nits | Ship it, suggest these in v1.1 |
| L2 skeptical | 12 (3H/6M/3L) | Block v1.0; ship as v1.0-rc1 |
| L3 adversarial | 15 (3 CRITICAL / 6H / 4M / 2L) | Block — version label is fiction |
| L4 hostile | 18 substantiated | Block; conditional approve list of 6 fixes |
| L5 pathological | 25 (2 EXISTENTIAL / 4 FOUND / 17 SERIOUS / 2 NOISE) | Should not exist as labeled |

## Recurring themes (cited by 2+ reviewers)

These are the highest-confidence findings — independent reviewers landed on the same issue from different posture levels.

### T1 — "v1.0 label is fiction" (L3, L4, L5)
**Symptom:** `makeBridge()` always returns `StubBridge`. 109 tools register, but ~94 of them throw `BRIDGE_NOT_READY` on every call except `ping`. Only the file-deploy / out-of-process surfaces (L6 .pyscript + L7 PyFLP + ping) actually function.
**Resolution options:**
- **A. Re-tag as `v0.9-pre-bridge`** (1 min) — honest labelling; reserve `v1.0` for transport-wired.
- **B. Implement minimum bridge** (~1-2 weeks) — TCP socket loopback + minimal device script per L0 default-assumption report; ship v1.0.1.
- **C. Qualify README headline** ("15 tools functional today, 94 pending L0 probe + transport") and keep v1.0 tag — minimum honesty without rework.

**Recommendation:** A (re-tag) immediately + B (implement bridge) over 1-2 weeks. C alone is insufficient.

### T2 — Release hygiene broken (L2, L4)
**Symptom:**
- `npm test` exits 1 — empty `tests/`, vitest finds no files.
- `npm run lint` errors — `eslint.config.js` not present despite eslint being in package.json scripts.
- `npm run format:check` reports 21 dirty files.
**Resolution:** ~1 hour. Add minimal `eslint.config.js`, run `npm run format`, write a smoke-test wrapper at `tests/smoke.test.ts` that re-runs the existing `scripts/smoke.ts` so vitest at least exits 0.

### T3 — Invented FL API names (L4)
**Symptom:** Several bridge.call method names have zero hits in the bundled vendor controller scripts (`Settings\Hardware\`):
- `mixer.setCurrentTempo` (introduced by L3 critic patch)
- `mixer.setRouteToLevel`
- `general.getCurrentProjectTitle` (the documented form is `general.getProjectTitle` — no "Current")
- Probably more — full audit needed.
**This directly violates Nathan's CLAUDE.md hard rule "Never invent APIs."** The L3 critic asserted these existed; nobody re-verified against vendor scripts before patching.
**Resolution:** ~2 hours. Spike-grep every bridge.call across `src/tools/*.ts` against `Settings\Hardware\**\*.py`. Any with zero vendor hits get either (a) renamed to a vendor-confirmed name, (b) demoted to YELLOW with description caveat, or (c) dropped.

### T4 — `state_snapshot` Promise.all (L2-H, L3 CRITICAL)
**Symptom:** `state_snapshot` issues 5 parallel `bridge.call`s. Any single rejection nukes the entire snapshot — fail-fast, no partial recovery. Against `StubBridge`, this means the first call throws `BRIDGE_NOT_READY` and the LLM gets a cryptic error instead of a useful partial picture.
**Resolution:** ~15 min. Replace `Promise.all` with `Promise.allSettled` and return per-call `{ ok, value | error }` shape. Caller can decide whether partial-data is acceptable.

### T5 — `.pyscript` user-input interpolation (L2-H)
**Symptom:** `src/pyscript/generator.ts` interpolates LLM-provided arguments (note pitches, velocities, names) directly into Python source via template literals. Zod schemas are the only gate before that source executes inside FL Studio. While zod constrains the types, a `script_name` with backticks or a `note.pitch` that's NaN could produce malformed Python that the user invokes.
**Resolution:** ~30 min. Sanitize all user-input substitutions before template insertion (numeric coercion, name regex `/^[A-Za-z0-9._-]+$/`, no escape sequences in numeric paths).

### T6 — `state_diff_snapshots` accepts non-snapshot inputs (L3 CRITICAL)
**Symptom:** Type guard is `typeof === "object"` only. Arrays, Date, RegExp, Buffer, etc. all pass. JSON.stringify comparison on these returns confident garbage.
**Resolution:** ~10 min. Use `Object.getPrototypeOf(x) === Object.prototype` or a stricter guard. Surface a "snapshot must come from state_snapshot" hint in the error.

### T7 — `channel_index` global-vs-group silent misrouting (L3-H)
**Symptom:** `live_play_note_now` and several other channels tools document `channel_index` as "0-based" without mentioning that `channels.midiNoteOn` ignores group membership and addresses the project-global channel space. When the user has channel groups, the LLM's mental "channel 5" silently targets a different channel than expected.
**Resolution:** ~20 min. Surface the global addressing in every relevant tool description. Long-term: add an optional `useGlobalIndex` arg with sane default (matches plugins module pattern).

### T8 — `mixer_set_route` claims atomic but isn't (L3-H)
**Symptom:** Description says "atomic" but the handler does two sequential `bridge.call`s with no rollback. Also ignores `setRouteTo`'s negative-return on rejected routing cycles.
**Resolution:** ~30 min. Wrap in try/catch, on second-call failure attempt rollback (set route back to original), surface routing-cycle errors as MCP tool errors.

### T9 — `DEFAULT_PYTHON` hardcoded to Nathan's profile (L2, L4)
**Symptom:** `src/pyflp/runner.ts` hardcodes `C:\Users\Nathan\AppData\Local\Programs\Python\Python313\python.exe` as fallback. Anyone else cloning the repo hits an ENOENT immediately if they don't set `FLSTUDIO_MCP_PYTHON`.
**Resolution:** ~10 min. Probe `PATH` for `python` / `python3` / `py -3` first. Document the env var override. Or: ship a config file pattern.

### T10 — `live_stream_notes` timing + stuck note (L2, L5)
**Symptom:** Uses `setTimeout` for per-note hold; if the MCP server is killed mid-stream, the note-off never fires, leaving a stuck note. Also susceptible to JS event-loop jitter for tight rhythms.
**Resolution:** ~30 min. Add `try/finally` that flushes all started notes' note-off on stream-end OR error. Document timing as "best-effort, not sample-accurate."

## Other notable findings

### L1 polish (ship as v1.1)
- F1.1 `jsonResult` helper duplicated across 17 tool files; hoist to `src/tools/_helpers.ts`.
- F1.2 snake_case vs camelCase arg-name split in `live.ts` / `piano_roll.ts` vs everything else.
- F1.3 4 different BGRA-color phrasings; pick one canonical sentence.
- F1.6 `live_arm_record` "idempotent" claim is wrong — it's a toggle, not idempotent.
- F1.7 Unused-`bridge`-param handling inconsistent across `flp.ts` and `piano_roll.ts`.

### L2 additions
- Silent config-load failure: `loadConfig` swallows JSON errors → falls back to defaults silently.
- `runner.ts` `setTimeout` for subprocess timeout — verified kill happens, but no test.
- Missing `tests/` directory entirely; ~12 modules are pure-TS and testable today.

### L3 additions (HIGH-severity not in themes above)
- `runner.ts` race between `setTimeout` and `child.exit` (timeout may fire after process already exited cleanly).
- `playlist_get_display_zone` returns int but description was originally "object/array" (corrected post-L2).
- Off-by-one risk in `channel_set_step_row` when `bits.length` exceeds pattern length.

### L4 conditional approvals (the things L4 demands before approval)
1. Headline qualified to "15 functional, 94 pending"
2. eslint.config.js added; format applied
3. Per-tool YELLOW caveats from DOMAIN-MAP surfaced in tool descriptions
4. `runner.ts` `DEFAULT_PYTHON` de-hardcoded
5. Drop `live_arm_record` or `transport_record` alias (functional duplicate)
6. Either `bridge-contract.md` enumerating method names with FL-API mapping, OR demote tag to `v0.9-pre-bridge`

### L5 architectural objections (worth considering, not necessarily acting on)
- **"Multi-surface dispatch" is naming, not implementation.** Three modules (Controller / Piano Roll / PyFLP) are registered side-by-side; there's no router. F5.2 FOUNDATIONAL.
- **TS adds no type safety over the bridge.** String-keyed RPC means a typo in `bridge.call("mixerr.setVolume")` only fails at runtime against a real bridge. Generated TS bindings from `fl-studio-api-stubs` would catch it at compile. F5.3 FOUNDATIONAL.
- **The README's lead usage example ("stream a melody") cannot be served reliably** — `live_stream_notes` has unbounded OnIdle jitter, no precision scheduler. F5.25.

### L5 acknowledgments (intellectually honest)
- L0 probe (`bridge/probes/device_FLStudioMCP_Probe.py`) is well-instrumented (7 questions, JSON envelope, atomic write).
- L7 PyFLP subprocess design (`src/pyflp/runner.ts`) is the best code in the repo — 30s timeout, kill-on-timeout, exit-code-agnostic JSON envelope, named error codes.
- L3 critique was real adversarial work; its patches all landed in shipped code.

## Action priority

### CRITICAL (do before any public push beyond current state)
1. **Re-tag the release.** Delete `v1.0.0` tag (or supersede); cut `v0.9-pre-bridge` at same commit. Reserve `v1.0` for transport-wired.
2. **Audit bridge.call method names against vendor scripts.** Spike-grep every `bridge.call("X.y")` against `Settings\Hardware\**\*.py`. Drop or rename anything with zero vendor hits (T3 — Nathan's hard rule).
3. **Fix `state_snapshot`** to use `Promise.allSettled` (T4).
4. **Fix `state_diff_snapshots`** type guard (T6).

### HIGH (before re-tagging v1.0)
5. **Release hygiene:** `eslint.config.js`, format-pass, vitest smoke-test wrapper so `npm test` passes (T2).
6. **`.pyscript` sanitize:** name regex + numeric coercion (T5).
7. **`channel_index` global-vs-group warning** in every relevant tool description (T7).
8. **`mixer_set_route` rollback** + error surface (T8).
9. **De-hardcode `DEFAULT_PYTHON`** (T9).
10. **`live_stream_notes` stuck-note guard** (T10).
11. **Drop `live_arm_record` OR `transport_record`** to remove duplicate (F1.6 / F4.13).

### MEDIUM (v1.0.1)
12. Hoist `jsonResult` to shared module (F1.1).
13. Standardize BGRA description sentence (F1.3).
14. Snake_case vs camelCase arg-name pass (F1.2).
15. Per-tool YELLOW caveats from DOMAIN-MAP in tool descriptions (F4.5 / F4.6).
16. `runner.ts` subprocess race fix (L3).
17. `loadConfig` JSON-error surface instead of silent fallback (L2).
18. Stricter zod schemas (channel_index bound checks, step_row length bound, etc.).

### LOW / DEFERRED (v1.1+)
19. Generated TS bindings from `fl-studio-api-stubs` (architectural, addresses L5 F5.3).
20. Real multi-surface router (architectural, addresses L5 F5.2).
21. Deep `state_snapshot` (already planned for v1.1).
22. Tests/ build-out — characterization tests for pure-TS modules first, integration tests against a real bridge once it exists.

## Recommended next move

**One-day fix pass:**
1. Re-tag → `v0.9-pre-bridge` (1 min).
2. Vendor-grep all bridge.call method names; produce `docs/BRIDGE-CONTRACT.md` mapping each MCP tool → FL API call → vendor-script citation. Anything without citation gets demoted or renamed (4-6 hr).
3. Apply CRITICAL + HIGH fixes (3-5 hr).
4. Add minimal `eslint.config.js`, run format, write a `tests/smoke.test.ts` that re-runs `scripts/smoke.ts` under vitest (1 hr).
5. Cut `v0.9.1-pre-bridge` with fixes.

**Then plan v1.0 properly:** L0 probe → transport implementation → integration test → real v1.0 tag, ~2 weeks of focused work.

## Audit artifacts

Full scratch reports (per reviewer):
- `_scratch/flstudio-mcp-research/audit-L1-friendly.md` (7 findings)
- `_scratch/flstudio-mcp-research/audit-L2-skeptical.md` (12 findings)
- `_scratch/flstudio-mcp-research/audit-L3-adversarial.md` (15 findings)
- `_scratch/flstudio-mcp-research/audit-L4-hostile.md` (18 findings)
- `_scratch/flstudio-mcp-research/audit-L5-pathological.md` (25 findings)

77 findings total across 5 reviewers. ~30 unique after dedup. ~10 in the CRITICAL/HIGH band.

The audits caught what the build did not: a v1.0 release that ships against a stub bridge.
