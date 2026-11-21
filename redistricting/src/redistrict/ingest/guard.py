"""Explicit guarded byte reads, retained for callers that need a narrow allowlist.

Generation entry points use `generation.py` for runtime path enforcement and
per-process manifests; `InputGuard` remains useful for isolated, explicit reads.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


class QuarantineAccessError(PermissionError):
    """A generation-side component tried to read electoral data."""


class PathNotAllowedError(PermissionError):
    """A path is outside the allowed input roots."""


@dataclass
class InputGuard:
    allowed_roots: list[Path]
    quarantine_roots: list[Path]
    _opened: dict[str, str] = field(default_factory=dict)  # path -> sha256

    def _resolve(self, path: str | Path) -> Path:
        return Path(path).resolve()

    def check(self, path: str | Path) -> Path:
        """Raise unless `path` may be read. Returns the resolved path."""
        p = self._resolve(path)
        for q in self.quarantine_roots:
            if p == q.resolve() or q.resolve() in p.parents:
                raise QuarantineAccessError(f"blocked read of quarantined file: {p}")
        for root in self.allowed_roots:
            r = root.resolve()
            if p == r or r in p.parents:
                return p
        raise PathNotAllowedError(f"path outside allowed roots: {p}")

    def read_bytes(self, path: str | Path) -> bytes:
        """Read a permitted file and record its hash in the manifest."""
        p = self.check(path)
        data = p.read_bytes()
        self._opened[str(p)] = hashlib.sha256(data).hexdigest()
        return data

    def manifest(self) -> dict[str, str]:
        """Files opened so far, with SHA-256. Written into runs/<id>/manifest.json."""
        return dict(sorted(self._opened.items()))

    def write_manifest(self, out: Path) -> None:
        out.write_text(json.dumps(self.manifest(), indent=2), encoding="utf-8")
