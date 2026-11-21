"""Blindness, code side (D10 layer 1): the guard refuses quarantined and out-of-scope reads."""

from __future__ import annotations

import pytest

from redistrict.ingest.guard import InputGuard, PathNotAllowedError, QuarantineAccessError


@pytest.fixture
def layout(tmp_path):
    raw = tmp_path / "data" / "raw"
    quarantine = tmp_path / "data" / "quarantine" / "electoral"
    raw.mkdir(parents=True)
    quarantine.mkdir(parents=True)
    (raw / "pop.csv").write_text("commune,pop\n01001,2000\n", encoding="utf-8")
    (quarantine / "results.csv").write_text("secret\n", encoding="utf-8")
    return tmp_path, raw, quarantine


def test_permitted_file_is_read_and_hashed(layout):
    _, raw, quarantine = layout
    guard = InputGuard(allowed_roots=[raw], quarantine_roots=[quarantine])
    data = guard.read_bytes(raw / "pop.csv")
    assert b"2000" in data
    manifest = guard.manifest()
    assert len(manifest) == 1
    assert len(next(iter(manifest.values()))) == 64  # sha256 hex


def test_quarantined_file_is_refused(layout):
    _, raw, quarantine = layout
    guard = InputGuard(allowed_roots=[raw, quarantine], quarantine_roots=[quarantine])
    with pytest.raises(QuarantineAccessError):
        guard.read_bytes(quarantine / "results.csv")
    assert guard.manifest() == {}  # nothing was recorded as read


def test_quarantine_is_refused_even_if_listed_as_allowed(layout):
    _, _, quarantine = layout
    guard = InputGuard(allowed_roots=[quarantine.parent], quarantine_roots=[quarantine])
    with pytest.raises(QuarantineAccessError):
        guard.check(quarantine / "results.csv")


def test_traversal_into_quarantine_is_refused(layout):
    tmp, raw, quarantine = layout
    guard = InputGuard(allowed_roots=[raw], quarantine_roots=[quarantine])
    # '..' resolves into quarantine: must be treated as quarantine, not as "allowed"
    with pytest.raises(QuarantineAccessError):
        guard.check(raw / ".." / "quarantine" / "electoral" / "results.csv")


def test_path_outside_all_roots_is_refused(layout):
    tmp, raw, quarantine = layout
    guard = InputGuard(allowed_roots=[raw], quarantine_roots=[quarantine])
    with pytest.raises(PathNotAllowedError):
        guard.check(tmp / "elsewhere.csv")
