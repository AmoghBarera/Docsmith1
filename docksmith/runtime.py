"""
Assemble layer tarballs into a rootfs and run the container CMD under Linux namespaces.

Uses unshare(1) for mount, UTS, IPC, and PID namespaces,
and chroot(1) for filesystem isolation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from docksmith.layer_store import layer_tar_path
from docksmith.manifest import load_manifest
from docksmith.network import setup_container_network, teardown_container_network
from docksmith.utils import (
    chroot_run,
    extract_tar_to,
    is_linux,
    rm_tree,
    setup_cgroup,
    strip_digest_ref,
)
import uuid


def assemble_rootfs(manifest: dict) -> Path:
    """
    Merge all layers in order into a new temporary directory.
    Later layers overwrite earlier layers.
    """
    root = Path(tempfile.mkdtemp(prefix="docksmith-rootfs-"))

    for layer in manifest["layers"]:
        digest = strip_digest_ref(str(layer))
        tar_path = layer_tar_path(digest)

        if not tar_path.is_file():
            raise FileNotFoundError(f"Missing layer tarball for {layer}")

        extract_tar_to(tar_path, root)

    return root


def _validate_rootfs(rootfs: Path, cmd: list) -> None:
    """
    Check that the assembled rootfs is non-empty and that the CMD
    executable actually exists inside it before we hand it to chroot.
    Raises a clear RuntimeError if something is wrong.
    """
    # Check rootfs is not completely empty
    contents = list(rootfs.iterdir())
    if not contents:
        raise RuntimeError(
            "Rootfs is empty — the assembled layers produced no filesystem.\n"
            "If you used 'FROM scratch', you must COPY in a full rootfs or at least "
            "the binary that CMD will run (e.g. a statically compiled executable).\n"
            "For a real base image, place a rootfs tarball at "
            "~/.docksmith/bases/<n>.tar and reference it with FROM <n>."
        )

    # Check that the CMD binary exists inside the rootfs
    exe = cmd[0]
    if exe.startswith("/"):
        exe_in_rootfs = rootfs / exe.lstrip("/")
        if not exe_in_rootfs.exists():
            raise RuntimeError(
                f"CMD executable '{exe}' not found inside the rootfs at {exe_in_rootfs}.\n"
                f"Make sure your Docksmithfile COPYs or installs '{exe}' before CMD."
            )


def run_container(
    image_name: str,
    *,
    use_exec: bool = False,
    memory: str | None = None,
    cpus: str | None = None,
    pids_limit: int | None = None,
    cap_add: list[str] | None = None,
    hostname: str | None = None,
    port_mappings: list[str] | None = None,
) -> int:
    """
    Load manifest, assemble rootfs, and run the container.

    Requires Linux and usually sudo/root for chroot + unshare.
    """
    if not is_linux():
        raise RuntimeError("docksmith run is only supported on Linux.")

    manifest = load_manifest(image_name)
    rootfs = assemble_rootfs(manifest)

    cmd = manifest.get("cmd")
    if not cmd:
        raise RuntimeError("No CMD found in image manifest.")

    if not isinstance(cmd, list):
        raise RuntimeError("CMD must be a list.")

    _validate_rootfs(rootfs, cmd)

    cid = uuid.uuid4().hex[:12]
    cg_path = None
    netns_name = None
    container_ip = None
    
    try:
        if is_linux():
            if memory or cpus or pids_limit:
                cg_path = setup_cgroup(cid, memory, cpus, pids_limit)
                print(f"Container limits: Memory={memory or 'unlimited'}, CPUs={cpus or 'unlimited'}, PIDs={pids_limit or 'unlimited'}")
            
            # Setup network if we're not just executing interactively/testing on host
            try:
                netns_name, container_ip = setup_container_network(cid, port_mappings)
                print(f"Network setup: IP={container_ip}, netns={netns_name}")
            except RuntimeError as e:
                # If network setup fails because bridge doesn't exist etc, we print and fail
                raise RuntimeError(f"Failed to setup container network: {e}")

        # use_exec mode: replace current process (os.execvp can't use the wrapper,
        # so we fall back to a direct subprocess with check=False and return its code)
        proc = chroot_run(
            rootfs, 
            cmd, 
            check=False, 
            inject_dns=False, 
            cgroup_path=cg_path,
            cid=cid,
            hostname=hostname,
            cap_add=cap_add,
            netns_name=netns_name,
        )
        return int(proc.returncode)
    except RuntimeError:
        raise
    finally:
        rm_tree(rootfs)
        
        if netns_name and container_ip:
            teardown_container_network(cid, container_ip, port_mappings)
            
        if cg_path and cg_path.exists():
            try:
                cg_path.rmdir()
            except OSError:
                pass


def run_container_exec(image_name: str) -> None:
    """
    Replace current process with the container.
    Delegates to run_container since os.execvp can't be used with the wrapper.
    """
    raise SystemExit(run_container(image_name))
