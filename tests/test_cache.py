"""Tests for deterministic cache keys."""

from __future__ import annotations

from docksmith.cache import compute_cache_key, cache_get, cache_put


def test_cache_key_deterministic() -> None:
    a = compute_cache_key("abc123", "COPY . /app", "filehash")
    b = compute_cache_key("abc123", "COPY . /app", "filehash")
    assert a == b
    assert len(a) == 64


def test_cache_key_changes_with_prev_digest() -> None:
    a = compute_cache_key("a", "RUN x", "")
    b = compute_cache_key("b", "RUN x", "")
    assert a != b


def test_cache_get_put_roundtrip(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCKSMITH_HOME", str(tmp_path))
    k = compute_cache_key(None, "FROM scratch", "")
    assert cache_get(k) is None
    cache_put(k, "deadbeef")
    assert cache_get(k) == "deadbeef"
