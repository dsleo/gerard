"""Runtime guard and provenance manifest for generation-side commands.

This is defense in depth: Python's audit hook rejects every attempted access to
the electoral quarantine and unexpected raw-data paths. `run_blind.py` adds an
OS-level quarantine deny rule; only that wrapper may issue a blindness PASS.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import multiprocessing.util
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

_ROOT: Path | None = None
_SCRIPT = "unknown"
_RUN_ID = ""
_OPENED: dict[str, str] = {}
_BLOCKED: list[str] = []
_INSTALLED = False
_FINALIZED = False
_HASHING = False

_ALLOWED_RAW = {
    "population",
    "admin_express",
    "insee_cog2024",
    "insee_iris_pop",
    "iris",
    "constituencies",
}
_ALLOWED_PROCESSED_DIRS = {
    "admin_express",
    "admin_express_fra",
    "gate1",
    "gate2",
    "iris",
    "iris_reu",
    "optimized",
    "acceptance",
    "optimizer_monitor",
    "plans",
    "official_seed_audit",
    "pipeline_runs",
}
_ALLOWED_PROCESSED_FILES = {
    "cog2024_mapping.csv",
    "cog2024_population.csv",
    "iris_population_2022.csv",
}
_ALLOWED_CONFIG_FILES = {"approved_contiguity_links.csv"}


class GenerationInputDenied(PermissionError):
    """A generation process attempted to access a disallowed input."""


def _as_path(value: Any) -> Path | None:
    if isinstance(value, int):
        return None
    if isinstance(value, bytes):
        try:
            value = os.fsdecode(value)
        except Exception:
            return None
    if not isinstance(value, (str, os.PathLike)):
        return None
    raw = os.fspath(value)
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    # GDAL's virtual zip prefix is not a filesystem path component.
    if raw.startswith("zip://"):
        raw = raw[6:]
    if raw.startswith("file://"):
        raw = raw[7:]
    path = Path(raw)
    if not path.is_absolute() and _ROOT is not None:
        path = Path.cwd() / path
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _record(path: Path) -> None:
    if str(path) in _OPENED or not path.is_file():
        return
    global _HASHING
    try:
        _HASHING = True
        digest = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        _OPENED[str(path)] = digest.hexdigest()
    except OSError:
        _OPENED[str(path)] = "UNAVAILABLE"
    finally:
        _HASHING = False


def _check_and_track(raw_path: Any, *, read: bool = True) -> None:
    if _ROOT is None or _HASHING:
        return
    path = _as_path(raw_path)
    if path is None:
        return
    quarantine = (_ROOT / "data/quarantine").resolve()
    raw_root = (_ROOT / "data/raw").resolve()
    processed_root = (_ROOT / "data/processed").resolve()
    config_root = (_ROOT / "config").resolve()

    if _inside(path, quarantine):
        _BLOCKED.append(str(path))
        raise GenerationInputDenied(f"generation access to quarantined data blocked: {path}")

    if _inside(path, raw_root):
        rel = path.relative_to(raw_root)
        if not rel.parts or rel.parts[0] not in _ALLOWED_RAW:
            _BLOCKED.append(str(path))
            raise GenerationInputDenied(f"raw input is not on the generation allowlist: {path}")
        if read:
            _record(path)
    elif _inside(path, processed_root):
        if read:
            rel = path.relative_to(processed_root)
            if not rel.parts or (rel.parts[0] not in _ALLOWED_PROCESSED_DIRS and rel.parts[0] not in _ALLOWED_PROCESSED_FILES):
                _BLOCKED.append(str(path))
                raise GenerationInputDenied(f"processed input is not on the generation allowlist: {path}")
            _record(path)
    elif _inside(path, config_root) and read:
        rel = path.relative_to(config_root)
        if len(rel.parts) != 1 or rel.name not in _ALLOWED_CONFIG_FILES:
            _BLOCKED.append(str(path))
            raise GenerationInputDenied(f"config input is not on the generation allowlist: {path}")
        _record(path)


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if event != "open" or not args:
        return
    raw_path = args[0]
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
    if isinstance(mode, str):
        read = mode.startswith("r") or "+" in mode
    elif flags:
        read = not bool(flags & getattr(os, "O_WRONLY", 1))
    else:
        read = True
    _check_and_track(raw_path, read=read)


def _patch_reader(module: Any, name: str) -> None:
    original = getattr(module, name, None)
    if original is None or getattr(original, "_generation_guard_wrapped", False):
        return

    def guarded(path_or_buffer: Any, *args: Any, **kwargs: Any) -> Any:
        _check_and_track(path_or_buffer, read=True)
        # ESRI Shapefile is a multi-file dataset. Include the companion files
        # used by GDAL, which may open them below Python's audit layer.
        if name == "read_file":
            path = _as_path(path_or_buffer)
            if path is not None and path.suffix.lower() == ".shp":
                for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix"):
                    _check_and_track(path.with_suffix(suffix), read=True)
        return original(path_or_buffer, *args, **kwargs)

    guarded._generation_guard_wrapped = True  # type: ignore[attr-defined]
    setattr(module, name, guarded)


def install_generation_guard(project_root: Path, script: str) -> str:
    """Install quarantine denial and return a run id shared by subprocesses."""
    global _ROOT, _SCRIPT, _RUN_ID, _INSTALLED
    if _INSTALLED:
        return _RUN_ID
    _ROOT = project_root.resolve()
    _SCRIPT = script
    if os.environ.get("REDISTRICTING_BLINDNESS_VERIFIED") != "seatbelt":
        raise RuntimeError(
            "Generation is disabled outside scripts/run_blind.py: the electoral quarantine must be OS-inaccessible."
        )
    _RUN_ID = os.environ.get("REDISTRICTING_BLIND_RUN_ID") or f"direct-{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"

    # Install before generation entry points read any project data. Python's
    # audit event also covers Path.open, zipfile, and ordinary library opens.
    sys.addaudithook(_audit)

    # GDAL-backed readers can open source files below Python's audit layer, so
    # guard their explicit input paths before handing them to native code.
    pd = sys.modules.get("pandas")
    if pd is not None:
        for name in ("read_csv", "read_excel", "read_json", "read_parquet", "read_pickle"):
            _patch_reader(pd, name)
    gpd = sys.modules.get("geopandas")
    if gpd is not None:
        _patch_reader(gpd, "read_file")

    _INSTALLED = True
    atexit.register(finalize_process_manifest)
    # multiprocessing workers terminate with os._exit(), so ordinary atexit
    # hooks are not reliable there. Register the same writer with its finalizer.
    multiprocessing.util.Finalize(None, finalize_process_manifest, exitpriority=20)
    return _RUN_ID


def finalize_process_manifest() -> None:
    """Write a per-process manifest; direct invocations are never certified."""
    global _FINALIZED, _HASHING
    if _FINALIZED or _ROOT is None:
        return
    _FINALIZED = True
    hashes = dict(sorted(_OPENED.items()))
    run_dir = _ROOT / "data/processed/blindness/runs" / _RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": _RUN_ID,
        "script": _SCRIPT,
        "pid": os.getpid(),
        "python_guard_installed": True,
        "os_quarantine_deny_claim": os.environ.get("REDISTRICTING_BLINDNESS_VERIFIED") == "seatbelt",
        "opened_project_inputs_sha256": hashes,
        "blocked_attempts": list(_BLOCKED),
    }
    (run_dir / f"process-{os.getpid()}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

