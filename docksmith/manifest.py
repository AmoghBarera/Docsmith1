"""
Image manifests stored as JSON under ~/.docksmith/images/<name>.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docksmith.utils import digest_ref, images_dir


def manifest_path(name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name.strip())
    return images_dir() / f"{safe}.json"


def save_manifest(
    name: str,
    base: str,
    layers: list[str],
    env: dict[str, str],
    cmd: list[str],
    workdir: str,
) -> Path:
    """layers: ordered list of sha256 hex digests (stored with sha256: prefix)."""
    path = manifest_path(name)
    data: dict[str, Any] = {
        "name": name,
        "base": base,
        "layers": [digest_ref(l) for l in layers],
        "env": env,
        "cmd": cmd,
        "workdir": workdir,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_manifest(name: str) -> dict[str, Any]:
    path = manifest_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_images() -> list[str]:
    out: list[str] = []
    for p in sorted(images_dir().glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(data.get("name", p.stem))
        except (json.JSONDecodeError, OSError):
            out.append(p.stem)
    return out


def delete_manifest(name: str) -> bool:
    p = manifest_path(name)
    if p.is_file():
        p.unlink()
        return True
    return False
