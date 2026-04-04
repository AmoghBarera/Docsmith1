"""
Deterministic build cache: maps cache keys to layer digests.

Stored as ~/.docksmith/cache/<cache_key_hex> containing the layer digest (hex).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from docksmith.utils import cache_dir


def compute_cache_key(previous_digest: str | None, instruction_text: str, content_hash: str) -> str:
    """
    Deterministic cache key (hex digest, no sha256: prefix).

    previous_digest: hex digest of previous layer, or empty string for first layer after scratch.
    instruction_text: canonical instruction string (e.g. raw line).
    content_hash: hash of relevant context (COPY sources) or empty string.
    """
    prev = previous_digest or ""
    h = hashlib.sha256()
    h.update(prev.encode("utf-8"))
    h.update(b"\0")
    h.update(instruction_text.encode("utf-8"))
    h.update(b"\0")
    h.update(content_hash.encode("utf-8"))
    return h.hexdigest()


def cache_key_path(cache_key: str) -> Path:
    return cache_dir() / cache_key


def cache_get(cache_key: str) -> str | None:
    """Return layer digest hex if cached, else None."""
    p = cache_key_path(cache_key)
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8").strip()


def cache_put(cache_key: str, layer_digest: str) -> None:
    p = cache_key_path(cache_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(layer_digest.strip(), encoding="utf-8")


def cache_invalidate_prefix(prefix: str) -> int:
    """Remove cache entries whose key starts with prefix (debug/maintenance)."""
    n = 0
    for p in cache_dir().glob(f"{prefix}*"):
        if p.is_file():
            p.unlink()
            n += 1
    return n
