"""Tests for the twilio_sms local artifact store."""

from __future__ import annotations

import pytest

from glc.channels.catalogue.twilio_sms import artifacts


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Point the store at a throwaway dir so tests never touch ~/.glc."""
    monkeypatch.setenv("GLC_ARTIFACTS_DIR", str(tmp_path))
    return tmp_path


def test_put_get_roundtrip():
    ref = artifacts.put(b"hello bytes", content_type="image/png", descriptor="d")
    assert ref.startswith("art:")
    assert artifacts.exists(ref)
    assert artifacts.get_bytes(ref) == b"hello bytes"

    meta = artifacts.get_meta(ref)
    assert meta is not None
    assert meta.id == ref
    assert meta.content_type == "image/png"
    assert meta.size_bytes == len(b"hello bytes")
    assert meta.source == "twilio_sms"
    assert meta.descriptor == "d"

    path = artifacts.get_path(ref)
    assert path is not None and path.read_bytes() == b"hello bytes"


def test_dedup_same_bytes_same_ref(isolated_store):
    ref1 = artifacts.put(b"dup", content_type="text/plain")
    ref2 = artifacts.put(b"dup", content_type="text/plain")
    assert ref1 == ref2
    # Written exactly once (one .bin + one .json).
    assert len(list(isolated_store.glob("*.bin"))) == 1
    assert len(list(isolated_store.glob("*.json"))) == 1


def test_remove():
    ref = artifacts.put(b"gone soon", content_type="application/octet-stream")
    assert artifacts.remove(ref) is True
    assert not artifacts.exists(ref)
    assert artifacts.get_bytes(ref) is None
    assert artifacts.remove(ref) is False  # already gone


@pytest.mark.parametrize(
    "bad_ref",
    [
        "art:../../etc/passwd",
        "art:not-hex-value!!",
        "art:ABCDEF0123456789",  # uppercase rejected
        "art:deadbeef",  # too short
        "notaref",
        "",
    ],
)
def test_validate_ref_rejects_bad_refs(bad_ref):
    assert artifacts._validate_ref(bad_ref) is None
    # ref-taking functions must refuse them, never touch the filesystem.
    assert artifacts.get_bytes(bad_ref) is None
    assert artifacts.get_path(bad_ref) is None
    assert artifacts.get_meta(bad_ref) is None
    assert artifacts.exists(bad_ref) is False
    assert artifacts.remove(bad_ref) is False


def test_cleanup_expired(monkeypatch):
    ref = artifacts.put(b"aging", content_type="text/plain")
    assert artifacts.exists(ref)
    # Force everything to look older than MAX_AGE.
    monkeypatch.setattr(artifacts, "MAX_AGE", -1)
    removed = artifacts.cleanup_expired()
    assert removed == 1
    assert not artifacts.exists(ref)


def test_cleanup_session():
    r1 = artifacts.put(b"one", content_type="text/plain")
    r2 = artifacts.put(b"two", content_type="text/plain")
    assert artifacts.cleanup_session([r1, r2, "art:deadbeefdeadbeef"]) == 2
    assert not artifacts.exists(r1)
    assert not artifacts.exists(r2)
