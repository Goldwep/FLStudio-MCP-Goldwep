# Write operations — FL's mutation gate, root-caused

> Empirical findings 2026-07-18 → 2026-07-21 against FL Studio 2024 v24.2.2 build 4597.

## The symptom

Mutating calls (`channels.setChannelName`, `mixer.setTrackVolume`, `patterns.setPatternName`, `general.processRECEvent`, …) dispatched by the bridge raise:

```
RuntimeError: Operation unsafe at current time
```

while read-side calls keep working normally.

## The root cause (three sessions to isolate)

**A modal dialog (or equivalent blocking UI state) is open in FL Studio.** While a modal is up, FL rejects every project mutation from scripting with "unsafe at current time" — reads are unaffected, which is what made this so confusing.

The killer detail: **`transport.record` on a never-saved project pops FL's "Save as" modal** (autosave-before-risky-operations). Our own verify harness triggered the modal with its `transport.record` probe, then every subsequent write in the same run failed. Three separate verification runs were poisoned this way before the modal was spotted on screen. `transport.start` on a never-saved project can do the same.

With no modal open, writes succeed **inline from the OnIdle dispatch** — no special context needed:

```
setChannelName -> ok in ~50ms, readback confirms
```

### Full live verification (2026-07-21, saved project, no modal)

```
$ npm run verify:live -- --include-writes
OVERALL: 75 ok / 0 fail / 0 timeout / 13 skip   —   all green
  channels : 20 ok / 0 fail   (every getter AND setter, incl. midiNoteOn, setGridBit, setStepParameterByIndex)
  mixer    : 20 ok / 0 fail   (setTrackVolume/Pan/Color/Name, mute/solo/arm, linkChannelToTrack, ...)
  patterns :  9 ok / 0 fail   (selectPattern, setPatternName/Color/Length, jumpToPattern)
  transport: 10 ok / 0 fail   (start/stop, setLoopMode, setSongPos, toggleMetronome, tapTempo)
```

The 13 skips are: 7 plugins probes (empty test project has no plugins loaded), 3 mixer routing-level ops, `transport.record` + `mixer.linkTrackToChannel` (kind `manual`, modal-poppers), and 1 general write.

## Rules for reliable writes

1. **Work against a saved project.** A never-saved ("Untitled") project pops the Save-as modal on the first risky operation (record, sometimes start). One manual save removes the whole failure class.
2. **Don't drive record/start probes unattended on unsaved projects.** `verify-live.ts` marks `transport.record` as kind `"manual"` — it never auto-runs, even with `--include-writes`.
3. **If writes suddenly all fail with "unsafe at current time": look for a modal.** Dismiss it (Escape / Cancel / WM_CLOSE to the dialog window) and writes resume immediately.
4. **Some setters pop their own modal on an invalid target.** `mixer.linkTrackToChannel` with no valid channel/track selection raises FL's "No channels" message box, which then stalls the gate. `verify-live.ts` marks it `manual`; in normal use only call it when a real link target exists.

## Defense in depth: the deferred-flush queue

The bridge additionally parks any request that trips the unsafe gate instead of failing it immediately (`_deferred` in `device_FLStudioMCP.py`):

- Parked requests are retried from `OnMidiMsg` and `OnRefresh` — FL's event-driven safe contexts (every bundled vendor script, e.g. Akai Fire, mutates exclusively from `OnMidiMsg`).
- If a safe context arrives (user plays a key, UI refreshes, the modal closes and generates a refresh), the queued writes land and their responses are written normally. Observed live: writes parked behind a modal all flushed the moment the dialog was closed.
- Requests older than `DEFER_TTL_SEC` (30s) are answered with the unsafe error so the Node caller never hangs past its own timeout.

Node-side callers see either a normal (delayed) success or a clean `FL_DISPATCH_ERROR` — never a mystery timeout caused by the gate itself.

## Related environmental gotchas (same investigation)

- **FL only executes controller scripts when the assigned MIDI input port opens.** `midiInGetNumDevs() == 0` → no bridge at all.
- **A zombie MIDI driver blocks OnIdle silently.** After a power interruption, the MPKmini2 driver enumerated but returned `MMSYSERR_NOTENABLED (7)` on open — FL loaded the script (OnInit on reload) but never pumped OnIdle. Reads AND writes both time out; the heartbeat goes stale (which the Node side now detects and reports as `BRIDGE_NOT_READY`). Fix: replug the USB device (or `pnputil /restart-device` as admin), then restart FL or re-select the controller.

## Verify runs leave toggle residue

`verify-live --include-writes` exercises toggle-style probes (`mixer.muteTrack`/`soloTrack` with `value: -1`, `channels.muteChannel`/`selectChannel`, metronome toggle, …) that **mutate the project they run against and don't restore state**. The sneakiest: the `soloTrack` probe on insert 1 solos it, which FL implements by muting every other insert — inaudible while nothing routes there, but the moment channels get routed to inserts 2+, only insert 1 plays. Diagnose with `mixer.isTrackMuted` across inserts; fix with explicit `muteTrack(index, value=0)`. Run verify against a scratch project, or expect to sweep mute/solo state afterward.
