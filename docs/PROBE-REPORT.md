# L0 Probe Report — Architecture Lock

> **Status:** TEMPLATE. Auto-fills when `probe_results.json` lands. Until then this file documents the **best-evidence default assumptions** L1+ is built against — see Section 0.

## 0. Default assumptions (in force until probe runs)

We proceed against the most-conservative interpretation that's still consistent with the il-group warnings and the 9-agent research sweep. If the probe contradicts any of these, L1+ code adapts in the next sync.

| Q   | Default assumption                                                          | Source of confidence                                                                                                             |
| --- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Q1  | `threading.Thread` works inside FL's embedded Python 3.12.1                 | Module imports cleanly; bundled `_thread.pyd` + `threading.pyc` present (verified)                                               |
| Q2  | **Cross-thread FL API calls UNSAFE** — assume crash mode is real            | il-group docs explicitly cite one crash for `device.isMidiOutAssigned` from "wrong interpreter". Queue-and-drain is the default. |
| Q3  | `processRECEvent(REC_Chan_NoteOn,...)` **assumed REJECTED**                 | Zero bundled vendor scripts wire `REC_Chan_Note_*` through processRECEvent (`grep` = 0 hits). Plan L6 separately.                |
| Q4  | `OnDeInit` **assumed unreliable on Reload Script**                          | Use `SO_REUSEADDR` + force-close pattern in `OnInit` defensively                                                                 |
| Q5  | `OnIdle` p50 ≈ 20 ms, p99 ≈ 100 ms under load                               | il-group docs say "roughly every 20 ms"                                                                                          |
| Q6  | Worker-thread `print()` **assumed lost**                                    | Bridge logs to `logging.FileHandler` next to device script                                                                       |
| Q7  | `OnUpdateLiveDisplay` **assumed merged into `OnUpdateLiveMode`** in FL 2024 | No vendor script wires `OnUpdateLiveDisplay`; image-line manual lists both but no observed differentiation                       |

These defaults are conservative. The architecture is built so each can be relaxed independently when probe data lands.

## 1. Environment

- Python version: _TBD_
- FL Studio version: _TBD_
- Probe run started: _TBD_
- Probe report finalized: _TBD_

## 2. Empirical results

### Q1 — Thread survival

- Spawned: _TBD_
- Worker counter after ~10s of OnIdle: _TBD_
- Worker thread ID: _TBD_
- **Verdict:** _TBD_

### Q2 — Cross-thread API call

- `channels.channelCount()` from worker returned: _TBD_
- Exception: _TBD_
- FL alive after call: _TBD_
- **Verdict:** _TBD_

### Q3 — `processRECEvent` accepts REC_Chan_NoteOn

- REC ID used: _TBD_
- Value used: _TBD_
- Flags: _TBD_
- Outcome: _TBD_
- **Verdict:** _TBD_ — if accepted, L6 collapses into L5; if rejected, ship L6 as multi-surface dispatch path.

### Q4 — OnDeInit on reload

- OnInit count: _TBD_
- OnDeInit count: _TBD_
- **Verdict:** _TBD_

### Q5 — OnIdle cadence

- Samples: _TBD_
- p50: _TBD_ ms
- p90: _TBD_ ms
- p99: _TBD_ ms
- **Verdict:** _TBD_ — sets per-request timeout to roughly 10× p99.

### Q6 — Worker print

- Main marker emitted: _TBD_
- Worker marker emitted: _TBD_
- (Manual: did both markers appear in Script Output window?) _TBD_
- **Verdict:** _TBD_

### Q7 — OnUpdateLiveDisplay vs OnUpdateLiveMode

- OnUpdateLiveMode calls: _TBD_
- OnUpdateLiveDisplay calls: _TBD_
- **Verdict:** _TBD_

## 3. Architecture decisions locked

| Decision                                             | Locked              | Rationale                                                                                            |
| ---------------------------------------------------- | ------------------- | ---------------------------------------------------------------------------------------------------- |
| Transport: TCP socket primary                        | _conditional on Q1_ | If Q1=alive: socket. If Q1=dead: pivot to virtual MIDI (Flapi pattern, +2 wks).                      |
| Dispatch: queue-and-drain via OnIdle                 | _conditional on Q2_ | Default safe pattern. Direct-call from socket thread possible if Q2=safe.                            |
| Note CRUD path: dual-mode                            | _conditional on Q3_ | If Q3=accepted: REC-based via MIDI Controller. If Q3=rejected: Piano Roll `.pyscript` dispatch (L6). |
| Socket cleanup: SO_REUSEADDR + force-close in OnInit | _yes_               | Defensive regardless of Q4 outcome.                                                                  |
| Request timeout: 10× p99 from Q5                     | _conditional on Q5_ | Default 1000ms; tighten/loosen after Q5.                                                             |
| Logging: file handler next to device script          | _yes_               | Defensive regardless of Q6 outcome.                                                                  |

## 4. Plan adjustments (auto-filled when probe runs)

_TBD_
