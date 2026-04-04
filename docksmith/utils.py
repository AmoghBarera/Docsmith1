"""
Shared helpers: paths under ~/.docksmith, hashing, safe filenames, subprocess helpers.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


def docksmith_home() -> Path:
    """Root state directory (layers, cache, images, bases)."""
    base = os.environ.get("DOCKSMITH_HOME")
    if base:
        return Path(base).expanduser().resolve()
    return Path.home() / ".docksmith"


def layers_dir() -> Path:
    p = docksmith_home() / "layers"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    p = docksmith_home() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def images_dir() -> Path:
    p = docksmith_home() / "images"
    p.mkdir(parents=True, exist_ok=True)
    return p


def bases_dir() -> Path:
    """Optional base image tarballs: ~/.docksmith/bases/<n>.tar"""
    p = docksmith_home() / "bases"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_ref(hex_digest: str) -> str:
    """Normalize to sha256:... form for display."""
    if hex_digest.startswith("sha256:"):
        return hex_digest
    return f"sha256:{hex_digest}"


def strip_digest_ref(ref: str) -> str:
    if ref.startswith("sha256:"):
        return ref[7:]
    return ref


def sanitize_base_name(name: str) -> str:
    """Filesystem-safe key for ~/.docksmith/bases/<key>.tar"""
    safe = "".join(c if c.isalnum()
                   or c in "._-" else "_" for c in name.strip())
    return safe or "image"


def tar_directory(root: Path, dest_tar: Path) -> None:
    """
    Create a tar of `root` directory tree into dest_tar.

    On Linux: uses the system `tar` command which correctly handles:
      - symlinked directories (e.g. bin -> usr/bin in modern Ubuntu)
      - device nodes, special files, and all metadata
      - proper ordering so extracted layers are self-consistent

    On non-Linux (Windows, for unit tests): falls back to Python tarfile
    which is sufficient for the simple test fixtures used there.
    """
    root = root.resolve()
    dest_tar.parent.mkdir(parents=True, exist_ok=True)
    if not root.exists():
        root.mkdir(parents=True)

    if is_linux():
        # Use system tar: handles symlinked dirs, devices, and all special files
        # -C: change into root so paths inside tar are relative (no leading /)
        # .: archive everything under root
        result = subprocess.run(
            ["tar", "-cf", str(dest_tar.resolve()), "-C", str(root), "."],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"tar creation failed (exit {result.returncode}):\n{result.stderr.strip()}"
            )
    else:
        # Fallback for Windows (unit tests only — no real Ubuntu rootfs here)
        with tarfile.open(dest_tar, "w") as tf:
            walked = False
            for dirpath, dirnames, filenames in os.walk(root, topdown=True):
                walked = True
                dirnames.sort()
                filenames.sort()
                rel_dir = Path(dirpath).relative_to(root)
                if rel_dir.parts:
                    arc_dir = rel_dir.as_posix() + "/"
                    ti = tarfile.TarInfo(name=arc_dir)
                    ti.type = tarfile.DIRTYPE
                    ti.mode = 0o755
                    tf.addfile(ti)
                for name in filenames:
                    fp = Path(dirpath) / name
                    arc = (rel_dir / name).as_posix() if str(rel_dir) != "." else name
                    if fp.is_symlink():
                        ti = tarfile.TarInfo(name=arc)
                        ti.type = tarfile.SYMTYPE
                        ti.linkname = os.readlink(fp)
                        tf.addfile(ti)
                    elif fp.is_file():
                        tf.add(fp, arcname=arc, recursive=False)


def extract_tar_to(tar_path: Path, dest: Path) -> None:
    """Extract tarball into dest (creates dest). Trusted layers only (our own tars).

    Uses the system `tar` command on Linux so that symlinked directories
    (e.g. bin -> usr/bin in modern Ubuntu exports) are handled correctly.
    Falls back to Python tarfile on non-Linux (e.g. Windows, for tests).
    """
    dest.mkdir(parents=True, exist_ok=True)
    if is_linux():
        result = subprocess.run(
            ["tar", "-xf", str(tar_path.resolve()), "-C", str(dest.resolve())],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"tar extraction failed (exit {result.returncode}):\n{result.stderr.strip()}"
            )
    else:
        with tarfile.open(tar_path, "r:*") as tf:
            tf.extractall(dest)


def chroot_run(
    rootfs: Path,
    cmd: list[str],
    *,
    check: bool = True,
    inject_dns: bool = True,
) -> subprocess.CompletedProcess:
    """
    Run a command inside a chroot with a fully prepared namespace.

    Sets up:
      - unshare: mount, UTS, IPC, PID namespaces
      - bind-mounts /dev, /sys from the host (gives access to /dev/null, gpg, etc.)
      - /proc via --mount-proc
      - DNS: copies host /etc/resolv.conf into rootfs for the duration of the call,
        then restores the original (so it never leaks into a layer snapshot)

    This is the single authoritative place for all chroot execution in docksmith.
    Both builder (RUN steps) and runtime (container run) use this function so that
    any future fix or improvement applies everywhere automatically.
    """
    if not is_linux():
        raise RuntimeError("chroot_run is only supported on Linux.")

    rootfs_abs = str(rootfs.resolve())

    # --- DNS injection ---
    guest_resolv = rootfs / "etc" / "resolv.conf"
    host_resolv = Path("/etc/resolv.conf")
    resolv_backup: bytes | None = None
    if inject_dns and host_resolv.is_file():
        guest_resolv.parent.mkdir(parents=True, exist_ok=True)
        if guest_resolv.is_file():
            resolv_backup = guest_resolv.read_bytes()
        shutil.copy2(host_resolv, guest_resolv)

    # --- Wrapper: bind-mount /dev and /sys then chroot ---
    # All mounts are confined to the private mount namespace and cleaned up on exit.
    cmd_str = " ".join(shlex.quote(str(c)) for c in cmd)
    wrapper = (
        f"mount --bind /dev {rootfs_abs}/dev && "
        f"mount --bind /sys {rootfs_abs}/sys && "
        f"chroot {rootfs_abs} {cmd_str}"
    )
    argv = [
        "unshare",
        "--mount",
        "--uts",
        "--ipc",
        "--pid",
        "--fork",
        "--mount-proc",
        "/bin/sh", "-c",
        wrapper,
    ]

    try:
        proc = subprocess.run(argv)
    except FileNotFoundError as e:
        raise RuntimeError(
            "unshare or chroot not found. Install util-linux and run as root."
        ) from e
    finally:
        # --- DNS restore ---
        if inject_dns and host_resolv.is_file():
            if resolv_backup is not None:
                guest_resolv.write_bytes(resolv_backup)
            elif guest_resolv.is_file():
                guest_resolv.unlink()

    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command {cmd} failed inside chroot with exit code {proc.returncode}"
        )

    return proc


def copy_tree(src: Path, dst: Path) -> None:
    """Copy file or directory tree from src to dst."""
    if src.is_file() or src.is_symlink():
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            dst.symlink_to(os.readlink(src))
        else:
            shutil.copy2(src, dst)
        return
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for child in sorted(src.iterdir()):
            copy_tree(child, dst / child.name)


def rm_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def hash_paths_for_copy(context: Path, src_pattern: str) -> str:
    """
    Deterministic hash of files that COPY would include.
    """
    src = (context / src_pattern).resolve()
    if not str(src).startswith(str(context.resolve())):
        raise ValueError("COPY source must stay inside build context")
    if not src.exists():
        raise FileNotFoundError(f"COPY source not found: {src_pattern}")

    h = hashlib.sha256()
    if src.is_file():
        h.update(src_pattern.encode())
        h.update(b"\0")
        h.update(sha256_file(src).encode())
        return h.hexdigest()

    paths = sorted(src.rglob("*"), key=lambda p: str(p.relative_to(src)))
    h.update(src_pattern.encode())
    for p in paths:
        rel = p.relative_to(src).as_posix()
        h.update(rel.encode())
        h.update(b"\0")
        if p.is_file():
            h.update(sha256_file(p).encode())
        elif p.is_dir():
            h.update(b"dir\0")
        elif p.is_symlink():
            h.update(b"link\0")
            h.update(os.readlink(p).encode())
        h.update(b"|")
    return h.hexdigest()


def ensure_dir(path: Path, mode: int = 0o755) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def is_linux() -> bool:
    return os.name == "posix" and hasattr(os, "uname") and os.uname().sysname == "Linux"
