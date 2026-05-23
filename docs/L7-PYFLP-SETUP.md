# L7 — PyFLP setup

L7 tools (`flp_scan_folder`, `flp_inspect`, `flp_get_plugins`, `flp_get_samples`, `flp_check_missing_samples`, `flp_tempo_distribution`, `flp_plugin_inventory`, `flp_get_pattern_summary`) read FL Studio `.flp` project files **off disk**, out-of-process from FL Studio itself. They spawn a Python subprocess that parses the file via [PyFLP](https://github.com/demberto/PyFLP).

This is a **one-time install**.

## Install

```powershell
# System Python 3.13 (recommended — what the MCP server defaults to):
"C:\Users\Nathan\AppData\Local\Programs\Python\Python313\python.exe" -m pip install --user pyflp
```

PyFLP 2.2.1 pulls in `construct`, `sortedcontainers`, and `typing-extensions` — all pure-Python, no compiler needed.

## Verify

```powershell
"C:\Users\Nathan\AppData\Local\Programs\Python\Python313\python.exe" -c "import pyflp; print(pyflp.__version__)"
```

Expected: `2.2.1`.

## Configure (optional)

The TS runner defaults to `C:\Users\Nathan\AppData\Local\Programs\Python\Python313\python.exe`. Override with environment variables:

- `FLSTUDIO_MCP_PYTHON` — full path to the Python interpreter that has PyFLP installed.
- `FLSTUDIO_MCP_PYFLP_HELPER` — full path to `bridge/pyflp_helper.py` (only needed if you've moved the helper).

## Behavior notes

- **Read-only.** L7 tools never call `pyflp.save()`. Writing `.flp` files via PyFLP is unsafe against FL Studio 2025+ (upstream issues #200, #203, #197).
- **Graceful degradation.** Folder-scanning tools (`flp_scan_folder`, `flp_tempo_distribution`, `flp_plugin_inventory`) collect per-file parse errors into an `errors` array and continue. Single-file tools (`flp_inspect`, `flp_get_plugins`, etc.) surface a `BridgeError` with `code: "PYFLP_ACTION_FAILED"`.
- **PyFLP missing.** If `pyflp` isn't importable, the helper returns a JSON error with a `hint` field instructing you to run the install command above. Surfaces as `BridgeError code "PYFLP_ACTION_FAILED"` on the TS side.
- **FL not running.** L7 doesn't talk to FL Studio at all — these tools work even if FL is closed.
- **`flp_get_pattern_summary` is YELLOW.** FL 2025 changed playlist/pattern serialization in ways PyFLP doesn't fully decode yet; `note_count` may be 0 or inaccurate on modern projects.
