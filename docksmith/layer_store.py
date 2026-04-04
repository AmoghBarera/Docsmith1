"""
Content-addressed layer storage: ~/.docksmith/layers/<sha256>.tar
"""

from __future__ import annotations

import shutil
from pathlib import Path

from docksmith.utils import digest_ref, layers_dir, sha256_bytes, strip_digest_ref


def layer_tar_path(digest_hex: str) -> Path:
    d = strip_digest_ref(digest_hex)
    return layers_dir() / f"{d}.tar"


def has_layer(digest_hex: str) -> bool:
    return layer_tar_path(digest_hex).is_file()


def store_layer_bytes(tar_bytes: bytes) -> str:
    """Store layer bytes; return hex digest (no prefix)."""
    digest = sha256_bytes(tar_bytes)
    path = layer_tar_path(digest)
    if not path.exists():
        path.write_bytes(tar_bytes)
    return digest


def store_layer_file(tar_path: Path) -> str:
    data = tar_path.read_bytes()
    return store_layer_bytes(data)


def read_layer_bytes(digest_hex: str) -> bytes:
    p = layer_tar_path(digest_hex)
    if not p.is_file():
        raise FileNotFoundError(f"Layer not found: {digest_ref(digest_hex)}")
    return p.read_bytes()


def copy_layer_to(digest_hex: str, dest_path: Path) -> None:
    """Copy layer tarball to dest_path."""
    shutil.copy2(layer_tar_path(digest_hex), dest_path)


def delete_layer(digest_hex: str) -> bool:
    p = layer_tar_path(digest_hex)
    if p.is_file():
        p.unlink()
        return True
    return False
