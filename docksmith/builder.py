"""
Build images from a Docksmithfile: layers, cache, manifests.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from docksmith.cache import compute_cache_key, cache_get, cache_put
from docksmith.layer_store import has_layer, store_layer_bytes
from docksmith.manifest import save_manifest
from docksmith.parser import Instruction, load_docksmithfile
from docksmith.utils import (
    bases_dir,
    chroot_run,
    copy_tree,
    extract_tar_to,
    hash_paths_for_copy,
    is_linux,
    rm_tree,
    sanitize_base_name,
    sha256_file,
    tar_directory,
)

LogFn = Callable[[str], None]


def _log(log: LogFn, msg: str) -> None:
    log(msg)


def _base_tarball_path(from_value: str) -> Path | None:
    """Resolve ~/.docksmith/bases/<sanitized>.tar if present."""
    if from_value.lower() == "scratch":
        return None
    key = sanitize_base_name(from_value)
    p = bases_dir() / f"{key}.tar"
    if p.is_file():
        return p
    # alternate: literal filename
    p2 = bases_dir() / from_value.replace("/", "_")
    if p2.suffix != ".tar":
        p2 = Path(str(p2) + ".tar")
    if p2.is_file():
        return p2
    return None


def _snapshot_layer(rootfs: Path) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as f:
        tmp = Path(f.name)
    try:
        tar_directory(rootfs, tmp)
        return tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)


def _apply_layer_tar_to_rootfs(rootfs: Path, tar_bytes: bytes) -> None:
    rm_tree(rootfs)
    rootfs.mkdir(parents=True)
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as f:
        tmp = Path(f.name)
    try:
        tmp.write_bytes(tar_bytes)
        extract_tar_to(tmp, rootfs)
    finally:
        tmp.unlink(missing_ok=True)


def _apply_layer_digest(rootfs: Path, digest: str) -> None:
    from docksmith.layer_store import read_layer_bytes

    data = read_layer_bytes(digest)
    _apply_layer_tar_to_rootfs(rootfs, data)


def _mkdir_p(rootfs: Path, path: str) -> None:
    if not path or path == "/":
        return
    p = rootfs / path.lstrip("/")
    p.mkdir(parents=True, exist_ok=True)


def _run_in_chroot(
    rootfs: Path,
    shell_cmd: str,
    workdir: str,
    extra_env: dict[str, str],
    log: LogFn,
) -> None:
    """
    Execute a RUN instruction inside the chroot using chroot_run().
    Environment variables and WORKDIR are applied as a shell preamble.
    """
    if not is_linux():
        raise RuntimeError("RUN is only supported on Linux hosts.")

    wd = workdir if workdir.startswith("/") else "/" + workdir
    run_env: dict[str, str] = dict(extra_env)
    if "PATH" not in run_env:
        run_env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    if "HOME" not in run_env:
        run_env["HOME"] = "/root"

    exports = " && ".join(f"export {k}={shlex.quote(v)}" for k, v in sorted(run_env.items()))
    inner = f"{exports} && cd {shlex.quote(wd)} && {shell_cmd}"

    _log(log, f"Executing RUN: {shell_cmd}")
    try:
        chroot_run(rootfs, ["/bin/sh", "-c", inner], check=True, inject_dns=True)
    except RuntimeError as e:
        # Re-raise with a cleaner RUN-specific message
        raise RuntimeError(str(e).replace(
            "Command ['/bin/sh', '-c'", f"RUN command"
        )) from e


def _copy_instruction(
    context: Path,
    rootfs: Path,
    ins: Instruction,
) -> None:
    assert ins.copy_src is not None and ins.copy_dest is not None
    src = (context / ins.copy_src).resolve()
    if not str(src).startswith(str(context.resolve())):
        raise ValueError("COPY source must be inside build context")
    dest = rootfs / ins.copy_dest.lstrip("/")
    if src.is_dir():
        if dest.exists():
            rm_tree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        copy_tree(src, dest)


def build_image(
    context: Path,
    dockerfile: Path,
    tag: str,
    log: LogFn | None = None,
) -> Path:
    """
    Build a tagged image. Returns path to manifest JSON.

    Requires Linux + root for RUN steps. COPY-only images may work without root.
    """
    log = log or print
    instructions = load_docksmithfile(dockerfile)
    if not instructions or instructions[0].name != "FROM":
        raise ValueError("Docksmithfile must start with FROM")

    env: dict[str, str] = {}
    workdir = "/"
    cmd: list[str] = []
    base_name = ""

    layers: list[str] = []
    prev_digest: str | None = None

    with tempfile.TemporaryDirectory() as td:
        rootfs = Path(td) / "rootfs"
        rootfs.mkdir()

        idx = 0
        while idx < len(instructions):
            ins = instructions[idx]

            if ins.name == "FROM":
                if idx != 0:
                    raise ValueError("Only one FROM is supported; it must be the first line of the Docksmithfile.")
                base_name = str(ins.value or "").strip()
                if not base_name:
                    raise ValueError("FROM requires a base image name or scratch")

                base_tar = _base_tarball_path(base_name)
                if base_name.lower() == "scratch":
                    content_hash = ""
                elif base_tar is not None:
                    content_hash = sha256_file(base_tar)
                else:
                    raise FileNotFoundError(
                        f"Base image '{base_name}' not found. Place a rootfs tarball at "
                        f"{bases_dir() / (sanitize_base_name(base_name) + '.tar')} "
                        "or use `FROM scratch` for an empty rootfs."
                    )

                instr_text = ins.raw.strip()
                ck = compute_cache_key(prev_digest, instr_text, content_hash)
                hit = cache_get(ck)
                if hit and has_layer(hit):
                    _log(log, "CACHE HIT")
                    prev_digest = hit
                    layers.append(hit)
                    _apply_layer_digest(rootfs, hit)
                else:
                    _log(log, "CACHE MISS")
                    if base_name.lower() == "scratch":
                        rm_tree(rootfs)
                        rootfs.mkdir()
                        tar_bytes = _snapshot_layer(rootfs)
                    else:
                        assert base_tar is not None
                        rm_tree(rootfs)
                        rootfs.mkdir()
                        extract_tar_to(base_tar, rootfs)
                        tar_bytes = _snapshot_layer(rootfs)
                    digest = store_layer_bytes(tar_bytes)
                    cache_put(ck, digest)
                    prev_digest = digest
                    layers.append(digest)
                idx += 1
                continue

            if ins.name == "WORKDIR":
                workdir = str(ins.value or "/")
                _mkdir_p(rootfs, workdir)
                idx += 1
                continue

            if ins.name == "ENV":
                if ins.env:
                    env.update(ins.env)
                idx += 1
                continue

            if ins.name == "CMD":
                cmd = list(ins.value) if isinstance(ins.value, list) else []
                idx += 1
                continue

            if ins.name == "COPY":
                assert ins.copy_src is not None and ins.copy_dest is not None
                ch = hash_paths_for_copy(context, ins.copy_src)
                instr_text = ins.raw.strip()
                ck = compute_cache_key(prev_digest, instr_text, ch)
                hit = cache_get(ck)
                if hit and has_layer(hit):
                    _log(log, "CACHE HIT")
                    prev_digest = hit
                    layers.append(hit)
                    _apply_layer_digest(rootfs, hit)
                else:
                    _log(log, "CACHE MISS")
                    _copy_instruction(context, rootfs, ins)
                    tar_bytes = _snapshot_layer(rootfs)
                    digest = store_layer_bytes(tar_bytes)
                    cache_put(ck, digest)
                    prev_digest = digest
                    layers.append(digest)
                idx += 1
                continue

            if ins.name == "RUN":
                if not isinstance(ins.value, str) or not ins.value.strip():
                    raise ValueError("RUN requires a non-empty command string")
                instr_text = ins.raw.strip()
                ck = compute_cache_key(prev_digest, instr_text, "")
                hit = cache_get(ck)
                if hit and has_layer(hit):
                    _log(log, "CACHE HIT")
                    prev_digest = hit
                    layers.append(hit)
                    _apply_layer_digest(rootfs, hit)
                else:
                    _log(log, "CACHE MISS")
                    _run_in_chroot(rootfs, ins.value.strip(), workdir, env, log)
                    tar_bytes = _snapshot_layer(rootfs)
                    digest = store_layer_bytes(tar_bytes)
                    cache_put(ck, digest)
                    prev_digest = digest
                    layers.append(digest)
                idx += 1
                continue

            raise ValueError(f"Unexpected instruction: {ins.name}")

    path = save_manifest(
        name=tag,
        base=base_name,
        layers=layers,
        env=env,
        cmd=cmd,
        workdir=workdir,
    )
    _log(log, f"Tagged image '{tag}' at {path}")
    return path


def build_from_path(
    path: Path,
    tag: str,
    log: LogFn | None = None,
) -> Path:
    """Convenience: path is build context; Docksmithfile must be path/Docksmithfile."""
    df = path / "Docksmithfile"
    if not df.is_file():
        df = path / "Dockerfile"
    if not df.is_file():
        raise FileNotFoundError(f"No Docksmithfile or Dockerfile in {path}")
    return build_image(path.resolve(), df.resolve(), tag, log=log)
