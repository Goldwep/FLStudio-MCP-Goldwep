"""PyFLP out-of-process helper for the FL Studio MCP server (L7).

Invoked as:  python pyflp_helper.py <action> <json-args>

Reads .flp project files from disk via the `pyflp` library and emits a
JSON envelope to stdout:

    success:  {"ok": true,  "result": <data>}
    failure:  {"ok": false, "error": "<type: msg>", "traceback": "..."}

This helper is intentionally READ-ONLY. PyFLP write is unsafe across FL
Studio 2025+ (open upstream issues #200, #203, #197) — we never call
`pyflp.save()`. The TS layer enforces a 30s timeout per invocation.

PyFLP attribute coverage varies between versions and project versions; we
use `getattr(...)` with safe defaults throughout so a slightly-off field
on one project never breaks the whole scan.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

# --- Hard-fail with a useful install hint if PyFLP is missing -------------
try:
    import pyflp  # type: ignore
except ImportError:  # pragma: no cover — runtime concern
    sys.stdout.write(
        json.dumps(
            {
                "ok": False,
                "error": "ImportError: pyflp not installed",
                "hint": (
                    "Run: pip install --user pyflp  "
                    "(use the same Python interpreter the MCP server spawns; "
                    "see docs/L7-PYFLP-SETUP.md)"
                ),
            }
        )
    )
    sys.exit(0)


# --- Safe attribute helpers ----------------------------------------------

def _safe(obj: Any, name: str, default: Any = None) -> Any:
    """Best-effort attribute read. PyFLP raises on undecoded events for some
    fields; treat any exception as 'missing' rather than blowing up the scan."""
    try:
        val = getattr(obj, name, default)
        return val if val is not None else default
    except Exception:
        return default


def _safe_str(obj: Any, name: str) -> str | None:
    val = _safe(obj, name)
    if val is None:
        return None
    try:
        return str(val)
    except Exception:
        return None


def _safe_int(obj: Any, name: str) -> int | None:
    val = _safe(obj, name)
    if val is None:
        return None
    try:
        return int(val)
    except Exception:
        return None


def _safe_len(it: Any) -> int:
    if it is None:
        return 0
    try:
        return len(it)
    except Exception:
        try:
            return sum(1 for _ in it)
        except Exception:
            return 0


def _time_signature(project: Any) -> dict[str, int | None]:
    # PyFLP exposes time_signature as a small object with .num / .beat.
    ts = _safe(project, "time_signature")
    if ts is None:
        return {"numerator": None, "denominator": None}
    num = _safe_int(ts, "num")
    beat = _safe_int(ts, "beat")
    return {"numerator": num, "denominator": beat}


# --- Core parsers ---------------------------------------------------------

def _parse_project(path: str) -> Any:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"FLP not found: {path}")
    if not p.is_file():
        raise IsADirectoryError(f"Not a file: {path}")
    return pyflp.parse(str(p))


def _project_summary(project: Any, path: str) -> dict[str, Any]:
    file_size = 0
    try:
        file_size = Path(path).stat().st_size
    except Exception:
        pass
    return {
        "path": path,
        "title": _safe_str(project, "title"),
        "tempo": _safe(project, "tempo"),
        "time_signature": _time_signature(project),
        "channel_count": _safe_len(_safe(project, "channels")),
        "mixer_track_count": _safe_len(_safe(project, "mixer")),
        "pattern_count": _safe_len(_safe(project, "patterns")),
        "file_size_bytes": file_size,
    }


def _project_metadata(project: Any) -> dict[str, Any]:
    samples = list(_iter_sample_paths(project))
    return {
        "title": _safe_str(project, "title"),
        "artist": _safe_str(project, "artist"),
        "genre": _safe_str(project, "genre"),
        "comments": _safe_str(project, "comments"),
        "version": _safe_str(project, "version"),
        "tempo": _safe(project, "tempo"),
        "time_signature": _time_signature(project),
        "channel_count": _safe_len(_safe(project, "channels")),
        "mixer_track_count": _safe_len(_safe(project, "mixer")),
        "pattern_count": _safe_len(_safe(project, "patterns")),
        "sample_paths_count": len(samples),
    }


def _iter_sample_paths(project: Any):
    channels = _safe(project, "channels")
    samplers = _safe(channels, "samplers") if channels is not None else None
    if samplers is None:
        return
    for sampler in samplers:
        sp = _safe(sampler, "sample_path")
        if sp:
            yield str(sp)


def _plugin_name(plugin: Any) -> str | None:
    # Native PyFLP plugins expose INTERNAL_NAME; VSTs expose .name or .vst.name.
    if plugin is None:
        return None
    for attr in ("name", "INTERNAL_NAME"):
        val = _safe_str(plugin, attr)
        if val:
            return val
    vst = _safe(plugin, "vst")
    if vst is not None:
        return _safe_str(vst, "name")
    # Last resort: class name.
    try:
        return type(plugin).__name__
    except Exception:
        return None


def _plugin_type(plugin: Any) -> str:
    if plugin is None:
        return "unknown"
    try:
        return type(plugin).__name__
    except Exception:
        return "unknown"


def _iter_plugins(project: Any):
    # Channel-rack instruments.
    channels = _safe(project, "channels")
    instruments = _safe(channels, "instruments") if channels is not None else None
    if instruments is not None:
        for idx, instrument in enumerate(instruments):
            plug = _safe(instrument, "plugin")
            if plug is not None:
                yield {
                    "name": _plugin_name(plug),
                    "type": _plugin_type(plug),
                    "channel_or_mixer": "channel",
                    "index": idx,
                    "slot_index": None,
                }
    # Mixer insert slot plugins.
    mixer = _safe(project, "mixer")
    if mixer is not None:
        for insert_idx, insert in enumerate(mixer):
            try:
                slots = list(insert)
            except Exception:
                slots = []
            for slot_idx, slot in enumerate(slots):
                plug = _safe(slot, "plugin")
                if plug is not None:
                    yield {
                        "name": _plugin_name(plug),
                        "type": _plugin_type(plug),
                        "channel_or_mixer": "mixer",
                        "index": insert_idx,
                        "slot_index": slot_idx,
                    }


def _iter_patterns(project: Any):
    patterns = _safe(project, "patterns")
    if patterns is None:
        return
    for pat in patterns:
        notes = _safe(pat, "notes")
        yield {
            "index": _safe_int(pat, "index"),
            "name": _safe_str(pat, "name"),
            "note_count": _safe_len(notes),
        }


# --- Action handlers ------------------------------------------------------

def action_scan_folder(args: dict[str, Any]) -> Any:
    folder = args["folder"]
    root = Path(folder)
    if not root.exists() or not root.is_dir():
        raise NotADirectoryError(f"Not a folder: {folder}")
    out: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for flp in root.rglob("*.flp"):
        try:
            project = pyflp.parse(str(flp))
            out.append(_project_summary(project, str(flp)))
        except Exception as e:
            errors.append({"path": str(flp), "error": f"{type(e).__name__}: {e}"})
    return {"projects": out, "errors": errors, "count": len(out)}


def action_inspect(args: dict[str, Any]) -> Any:
    project = _parse_project(args["path"])
    return _project_metadata(project)


def action_plugins(args: dict[str, Any]) -> Any:
    project = _parse_project(args["path"])
    return list(_iter_plugins(project))


def action_samples(args: dict[str, Any]) -> Any:
    project = _parse_project(args["path"])
    return list(_iter_sample_paths(project))


def action_check_missing_samples(args: dict[str, Any]) -> Any:
    project = _parse_project(args["path"])
    missing: list[str] = []
    present = 0
    for sp in _iter_sample_paths(project):
        if Path(sp).exists():
            present += 1
        else:
            missing.append(sp)
    return {"missing": missing, "present_count": present, "missing_count": len(missing)}


def action_tempo_distribution(args: dict[str, Any]) -> Any:
    folder = args["folder"]
    root = Path(folder)
    if not root.exists() or not root.is_dir():
        raise NotADirectoryError(f"Not a folder: {folder}")
    buckets: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    total = 0
    for flp in root.rglob("*.flp"):
        try:
            project = pyflp.parse(str(flp))
            tempo = _safe(project, "tempo")
            if tempo is None:
                continue
            try:
                bpm = float(tempo)
            except Exception:
                continue
            bucket_low = int(bpm // 5) * 5
            key = f"{bucket_low}-{bucket_low + 4}"
            buckets[key] = buckets.get(key, 0) + 1
            total += 1
        except Exception as e:
            errors.append({"path": str(flp), "error": f"{type(e).__name__}: {e}"})
    return {"buckets": buckets, "total": total, "errors": errors}


def action_plugin_inventory(args: dict[str, Any]) -> Any:
    folder = args["folder"]
    root = Path(folder)
    if not root.exists() or not root.is_dir():
        raise NotADirectoryError(f"Not a folder: {folder}")
    counts: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    files_scanned = 0
    for flp in root.rglob("*.flp"):
        try:
            project = pyflp.parse(str(flp))
            files_scanned += 1
            for plug in _iter_plugins(project):
                name = plug["name"] or "<unknown>"
                counts[name] = counts.get(name, 0) + 1
        except Exception as e:
            errors.append({"path": str(flp), "error": f"{type(e).__name__}: {e}"})
    return {"plugins": counts, "files_scanned": files_scanned, "errors": errors}


def action_pattern_summary(args: dict[str, Any]) -> Any:
    # YELLOW per DOMAIN-MAP: FL 2025 may break playlist/pattern data parsing
    # (PyFLP issue #200). We catch per-pattern errors and report best-effort.
    project = _parse_project(args["path"])
    return list(_iter_patterns(project))


ACTIONS = {
    "scan_folder": action_scan_folder,
    "inspect": action_inspect,
    "plugins": action_plugins,
    "samples": action_samples,
    "check_missing_samples": action_check_missing_samples,
    "tempo_distribution": action_tempo_distribution,
    "plugin_inventory": action_plugin_inventory,
    "pattern_summary": action_pattern_summary,
}


# --- Entry ---------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="PyFLP MCP helper")
    parser.add_argument("action", choices=sorted(ACTIONS.keys()))
    parser.add_argument("args_json", nargs="?", default="{}")
    ns = parser.parse_args()

    try:
        args = json.loads(ns.args_json) if ns.args_json else {}
        result = ACTIONS[ns.action](args)
        sys.stdout.write(json.dumps({"ok": True, "result": result}, default=str))
    except Exception as e:
        sys.stdout.write(
            json.dumps(
                {
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                    "traceback": traceback.format_exc(),
                }
            )
        )
    return 0  # always exit 0 — errors flow via stdout JSON envelope


if __name__ == "__main__":
    sys.exit(main())
