"""The Pages release must work under a repository prefix and match its source."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pages_bundle_uses_only_saved_snapshots_and_project_relative_urls(tmp_path, monkeypatch):
    builder = script("build_pages")
    monkeypatch.setattr(builder, "OUTPUT", tmp_path / "site")
    output = builder.build()
    snapshots = {path.name for path in (output / "export/browser").iterdir()}
    assert snapshots == set(builder.SNAPSHOTS)
    assert "const DATA='export/';" in (output / "atlas.js").read_text()
    assert 'src="export/browser/projection-2026.js"' in (output / "method.html").read_text()
    assert not (output / "data").exists()
    assert not (output / "experiments").exists()
    assert not (output / ".git").exists()
    manifest = json.loads((output / "build-manifest.json").read_text())["sha256"]
    for name, digest in manifest.items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest


def test_pages_builder_preserves_unrecognized_output_directory(tmp_path, monkeypatch):
    builder = script("build_pages")
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("existing work")
    monkeypatch.setattr(builder, "OUTPUT", output)
    with pytest.raises(RuntimeError, match="unrecognized"):
        builder.build()
    assert (output / "keep.txt").read_text() == "existing work"


def test_published_file_check_uses_repository_prefix(tmp_path, monkeypatch):
    verifier = script("verify_pages")
    contents = b"<!doctype html><title>Deployed release</title>"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sha256": {"index.html": hashlib.sha256(contents).hexdigest()}}))
    requested = []

    def download(request, timeout):
        requested.append(request.full_url)
        return io.BytesIO(contents)

    monkeypatch.setattr(verifier, "urlopen", download)
    assert verifier.verify("https://example.github.io/gerard/", manifest) == 1
    assert requested == ["https://example.github.io/gerard/index.html"]


def test_published_file_check_detects_stale_or_missing_release(tmp_path, monkeypatch):
    verifier = script("verify_pages")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sha256": {"index.html": hashlib.sha256(b"new release").hexdigest()}}))
    monkeypatch.setattr(verifier, "urlopen", lambda *args, **kwargs: io.BytesIO(b"old release"))
    with pytest.raises(ValueError, match="differs from this release"):
        verifier.verify("https://example.github.io/gerard/", manifest)
