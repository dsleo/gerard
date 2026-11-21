"""Small atomic progress snapshots for the local optimizer dashboard."""

from __future__ import annotations

import json
import os
from pathlib import Path


def monitor_directory() -> Path | None:
    value = os.environ.get("REDISTRICT_MONITOR_DIR")
    return Path(value) if value else None


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    temp.replace(path)


def write_department_progress(record: dict) -> None:
    root = monitor_directory()
    if root is None:
        return
    dept = str(record.get("dept", "unknown"))
    atomic_json(root / "departments" / f"{dept}.json", record)
