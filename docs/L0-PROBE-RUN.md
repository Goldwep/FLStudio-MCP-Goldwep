# L0 — Probe Run Instructions

**Already installed for you** at:
`%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP-Probe\device_FLStudioMCP_Probe.py`

## What the probe does

Answers 7 architectural questions empirically by running inside FL Studio's MIDI scripting environment for ~20 seconds. Outputs `probe_results.json` next to the script. Read-only on your project (Q2 may crash FL — see Risks below).

| Q   | What it tests                                   | Why it matters                                      |
| --- | ----------------------------------------------- | --------------------------------------------------- |
| Q1  | `threading.Thread` survives FL embedding        | Decides socket bridge vs virtual MIDI               |
| Q2  | Cross-thread FL API call                        | Decides queue-and-drain vs direct-call              |
| Q3  | `processRECEvent(REC_Chan_NoteOn,...)` accepted | **HIGHEST LEVERAGE** — if yes, L6 collapses into L5 |
| Q4  | `OnDeInit` fires on Reload Script               | Affects socket cleanup design                       |
| Q5  | `OnIdle` cadence p50/p99                        | Sets per-request timeout                            |
| Q6  | Worker-thread `print()` reaches Script Output   | Decides logging architecture                        |
| Q7  | `OnUpdateLiveDisplay` vs `OnUpdateLiveMode`     | Callback count for plan-doc accuracy                |

## How to run (manual, ~2 minutes)

1. **Save and close any FL Studio project** you care about. Q2 deliberately attempts a cross-thread API call that could crash FL.
2. Open FL Studio. Create a new blank project (or open one you don't care about).
3. Open **Options → MIDI Settings**.
4. In the **Input** list, pick any input device (or click a placeholder). Click the **Controller type** dropdown.
5. Select **"FLStudio MCP Probe"** from the list (it appears because the script's `# name=` header registers it).
6. Click **Refresh device list** if it doesn't show up.
7. Click **OK**.
8. Open **View → Script output**. You should see messages from `[probe]`.
9. **Wait ~15 seconds.** The probe collects 200 `OnIdle` samples in this window.
10. Click **Reload script** in the Script Output window.
11. **Wait ~5 more seconds.**
12. Quit FL Studio (clean exit so `OnDeInit` fires one more time).

## Where the results land

```
%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP-Probe\
├── device_FLStudioMCP_Probe.py
├── probe_results.json     <-- main output, JSON
└── probe_log.txt          <-- auxiliary log (worker-thread writes here)
```

## When you're done

Either:

- **Tell Claude "probe done"** — Claude reads the JSON, synthesizes `docs/PROBE-REPORT.md`, locks architecture, continues to L1.
- **Or just let it run** — Claude continues against best-evidence defaults; reconciles when probe data lands.

## Risks

- **Q2 may crash FL.** The probe calls `channels.channelCount()` from a worker thread. il-group docs warn one `device` function "crashes FL when called from wrong interpreter context". If FL crashes, that itself answers Q2 (don't call FL API from worker threads — use queue-and-drain) and you proceed without restarting the probe.
- **Q3 attempts a REC event** with a best-guess pitch+velocity encoding. On a blank project there's no channel for it to land on, so worst case is an exception. Use a blank project.
- **Reload Script may leak the worker thread.** If FL stays sluggish after the probe, restart FL.

## Uninstall

Delete the folder:
`%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\FLStudio-MCP-Probe\`

That's it.
