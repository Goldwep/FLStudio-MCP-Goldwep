# FL Studio MCP — Goldwep

MCP server for FL Studio (Image-Line). Full-spectrum control surface — composition *and* project inspection — over a localhost socket bridge into FL Studio's bundled Python scripting environment.

> **Status: pre-planning scaffold.** This repo is the bones — the tool surface, bridge protocol, and feature matrix are about to be designed in the first planning phase. Nothing functional yet.

## Architecture (provisional)

```
┌──────────────┐  stdio   ┌──────────────────┐  TCP   ┌─────────────────────────┐
│ Claude /     │ ───────▶ │ flstudio-mcp     │ ─────▶ │ device_FLStudioMCP.py   │
│ MCP client   │ ◀─────── │ (Node, this repo)│ ◀───── │ (runs inside FL Studio) │
└──────────────┘          └──────────────────┘        └────────────┬────────────┘
                                                                   │
                                                  channels / mixer / patterns /
                                                  transport / playlist / plugins /
                                                  arrangement / ui / general
```

- **Node MCP server** — exposes tools to the LLM, owns the protocol surface.
- **Localhost TCP bridge** — JSON-RPC over a single socket. Persistent, low-latency.
- **In-FL device script** — a MIDI device script Python file living in FL Studio's `Settings\Hardware\` folder. Calls FL's scripting API (`channels`, `mixer`, `patterns`, `transport`, `plugins`, `playlist`, `arrangement`, `ui`, `general`, `device`) on behalf of the MCP server.

FL Studio 2024 ships Python 3.12 in `Shared\Python\` with `_socket.pyd` and `_ssl.pyd` available — the socket bridge runs entirely inside FL Studio's own interpreter, no external Python install required.

## Project layout

```
src/        TypeScript MCP server (tools, server bootstrap, config, logger)
bridge/     in-FL Python device script (to be installed in FL Studio)
docs/       design notes, API surface reference
tests/      vitest suites
scripts/    build / dev / packaging helpers
data/       static reference data
```

## Install (once shipped)

Not published yet. Local-dev install instructions will land at v0.1+.

### Optional: L7 PyFLP project intelligence

The `flp_*` tools (project scanning, plugin inventory, tempo distribution, etc.) parse `.flp` files off disk via a Python subprocess — they don't need FL Studio running. One-time setup:

```powershell
"C:\Users\Nathan\AppData\Local\Programs\Python\Python313\python.exe" -m pip install --user pyflp
```

See [`docs/L7-PYFLP-SETUP.md`](./docs/L7-PYFLP-SETUP.md) for verification, environment overrides, and behavior notes.

## Credits

- Designed and built by [Goldwep](https://github.com/Goldwep).
- FL Studio is a trademark of [Image-Line NV](https://www.image-line.com/). This is an independent community tool.

## License

[MIT](./LICENSE).
