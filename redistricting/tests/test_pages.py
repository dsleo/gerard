"""The Pages release must work under a repository prefix and match its source."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

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
    assert "const DATA='export/';" in (output / 'scenarios.js').read_text()
    assert (output / 'scenarios.html').is_file()
    assert 'partisan-scenarios.js' in snapshots
    assert not (output / "data").exists()
    assert not (output / "experiments").exists()
    assert not (output / ".git").exists()
    manifest = json.loads((output / "build-manifest.json").read_text())["sha256"]
    assert (output / ".nojekyll").is_file()
    assert ".nojekyll" not in manifest
    assert ".gerard-pages-build" not in manifest
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


def test_legacy_manifest_does_not_request_configuration_markers(tmp_path, monkeypatch):
    verifier = script("verify_pages")
    contents = b"published app"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sha256": {
        ".nojekyll": hashlib.sha256(b"").hexdigest(),
        ".gerard-pages-build": hashlib.sha256(b"build marker").hexdigest(),
        "index.html": hashlib.sha256(contents).hexdigest(),
    }}))
    requested = []

    def download(request, timeout):
        requested.append(request.full_url)
        if request.full_url.endswith((".nojekyll", ".gerard-pages-build")):
            raise HTTPError(request.full_url, 404, "Not Found", {}, None)
        return io.BytesIO(contents)

    monkeypatch.setattr(verifier, "urlopen", download)
    assert verifier.verify("https://example.github.io/gerard/", manifest) == 1
    assert requested == ["https://example.github.io/gerard/index.html"]


def test_missing_public_file_still_fails_with_its_url(tmp_path, monkeypatch):
    verifier = script("verify_pages")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sha256": {"atlas.js": "unused digest"}}))

    def download(request, timeout):
        raise HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(verifier, "urlopen", download)
    with pytest.raises(ValueError, match=r"HTTP 404.*atlas\.js.*https://example\.github\.io/gerard/atlas\.js"):
        verifier.verify("https://example.github.io/gerard/", manifest)


def test_manifest_with_only_control_files_cannot_pass(tmp_path):
    verifier = script("verify_pages")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sha256": {".nojekyll": "unused digest"}}))
    with pytest.raises(ValueError, match="no public files"):
        verifier.verify("https://example.github.io/gerard/", manifest)


def test_cli_reports_failed_url_and_retries_without_a_traceback(tmp_path, monkeypatch, capsys):
    verifier = script("verify_pages")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sha256": {"index.html": "unused digest"}}))
    requests = []

    def download(request, timeout):
        requests.append(request.full_url)
        raise HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(verifier, "urlopen", download)
    monkeypatch.setattr(verifier.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(verifier.sys, "argv", [
        "verify_pages.py", "https://example.github.io/gerard/", "--manifest", str(manifest), "--attempts", "2",
    ])
    with pytest.raises(SystemExit) as failure:
        verifier.main()
    assert failure.value.code == 1
    assert len(requests) == 2
    errors = capsys.readouterr().err
    assert "Verification attempt 2/2" in errors
    assert "https://example.github.io/gerard/index.html" in errors
    assert "Traceback" not in errors
