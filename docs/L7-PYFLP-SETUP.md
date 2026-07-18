# L7 — PyFLP setup

L7 tools (`flp_scan_folder`, `flp_inspect`, `flp_get_plugins`, `flp_get_samples`, `flp_check_missing_samples`, `flp_tempo_distribution`, `flp_plugin_inventory`, `flp_get_pattern_summary`) read FL Studio `.flp` project files **off disk**, out-of-process from FL Studio itself. They spawn a Python subprocess that parses the file via [PyFLP](https://github.com/demberto/PyFLP).

This is a **one-time install**.

## Python version constraint (IMPORTANT)

**PyFLP 2.2.x requires Python ≤ 3.10.** Its abstract `EventEnum(value)` lookup relies on `_missing_` dispatch against an empty enum, which Python 3.11+ rejects with:

```
TypeError: <enum 'EventEnum'> has no members defined
```

(Verified 2026-07-18 on 3.11 and 3.13 — every parse fails; on 3.10 everything works. PyFLP is unmaintained, so don't expect an upstream fix.)

## Install (recommended: repo-local uv venv)

```powershell
cd <repo root>
uv venv --python 3.10 .venv-pyflp
uv pip install --python .venv-pyflp pyflp
```

The TS runner **auto-detects `.venv-pyflp/`** at the repo root — no configuration needed. `.venv-pyflp` is gitignored.

## Verify

```powershell
.venv-pyflp\Scripts\python.exe -c "import pyflp; print('ok')"
# Full end-to-end check against a demo project:
.venv-pyflp\Scripts\python.exe bridge\pyflp_helper.py inspect "{\"path\": \"C:\\Program Files\\Image-Line\\FL Studio 2024\\Data\\Demo projects\\Demo songs\\Asher Postman - Future Bass.flp\"}"
```

Expected: a JSON envelope with `"ok": true` and the project title/tempo.

## Configure (optional)

Interpreter resolution order:

1. `FLSTUDIO_MCP_PYTHON` — full path to a Python (≤ 3.10) that has PyFLP installed.
2. Repo-local `.venv-pyflp` (see above) — auto-detected.
3. PATH-resolved `python` (Windows) / `python3` (elsewhere) — only works if your system Python is ≤ 3.10.

- `FLSTUDIO_MCP_PYFLP_HELPER` — full path to `bridge/pyflp_helper.py` (only needed if you've moved the helper).

## Behavior notes

- **Read-only.** L7 tools never call `pyflp.save()`. Writing `.flp` files via PyFLP is unsafe against FL Studio 2025+ (upstream issues #200, #203, #197).
- **Graceful degradation.** Folder-scanning tools (`flp_scan_folder`, `flp_tempo_distribution`, `flp_plugin_inventory`) collect per-file parse errors into an `errors` array and continue. Single-file tools (`flp_inspect`, `flp_get_plugins`, etc.) surface a `BridgeError` with `code: "PYFLP_ACTION_FAILED"`.
- **PyFLP missing.** If `pyflp` isn't importable, the helper returns a JSON error with a `hint` field instructing you to run the install command above. Surfaces as `BridgeError code "PYFLP_ACTION_FAILED"` on the TS side.
- **FL not running.** L7 doesn't talk to FL Studio at all — these tools work even if FL is closed.
- **`flp_get_pattern_summary` is YELLOW.** FL 2025 changed playlist/pattern serialization in ways PyFLP doesn't fully decode yet; `note_count` may be 0 or inaccurate on modern projects.
- **Plugin names may be generic.** On some projects PyFLP reports `_PluginBase` instead of the concrete plugin name (seen on FL 20.5-era projects); counts and slot positions are still correct.
