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
    docksmith_home,
    extract_tar_to,
    images_dir,
    is_linux,
    rm_tree,
    setup_cgroup,
    strip_digest_ref,
)
from docksmith.state import save_state, update_state_status, get_container_dir
import uuid
import subprocess


def ensure_layer_extracted(image_name: str, digest_hex: str) -> Path:
    """Extracts a layer lazily into ~/.docksmith/images/<image-name>/<layer-id>/"""
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in image_name.strip())
    ldir = images_dir() / safe_name / digest_hex
    if not ldir.exists():
        ldir.mkdir(parents=True)
        tar_path = layer_tar_path(digest_hex)
        extract_tar_to(tar_path, ldir)
    return ldir


def setup_overlayfs(manifest: dict, image_name: str, cid: str) -> tuple[Path, Path]:
    """
    Mounts an overlay filesystem for the container.
    Returns (merged_dir, container_dir)
    """
    lowerdirs = []
    # In overlayfs, lowerdir=dir1:dir2 where dir1 is the UPPERMOST read-only layer.
    for layer in reversed(manifest["layers"]):
        digest = strip_digest_ref(str(layer))
        ldir = ensure_layer_extracted(image_name, digest)
        lowerdirs.append(str(ldir))
        
    cont_dir = docksmith_home() / "containers" / cid
    upper = cont_dir / "upper"
    work = cont_dir / "work"
    merged = cont_dir / "merged"
    
    upper.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    merged.mkdir(parents=True, exist_ok=True)
    
    lowerdir_str = ":".join(lowerdirs)
    if not lowerdir_str:
        raise RuntimeError("No layers found in manifest to use as lowerdir")
        
    cmd = [
        "mount", "-t", "overlay", "overlay",
        "-o", f"lowerdir={lowerdir_str},upperdir={upper},workdir={work}",
        str(merged)
    ]
    subprocess.run(cmd, check=True)
    
    return merged, cont_dir


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
    cmd_override: list[str] | None = None,
    memory: str | None = None,
    cpus: str | None = None,
    pids_limit: int | None = None,
    cap_add: list[str] | None = None,
    hostname: str | None = None,
    port_mappings: list[str] | None = None,
    keep: bool = False,
    rootless: bool = False,
    seccomp_profile: str | None = "default",
) -> int:
    """
    Load manifest, assemble rootfs, and run the container.

    Requires Linux and usually sudo/root for chroot + unshare.
    """
    import signal
    import sys

    def _sig_handler(signum, frame):
        sys.exit(128 + signum)

    try:
        signal.signal(signal.SIGTERM, _sig_handler)
        signal.signal(signal.SIGINT, _sig_handler)
    except ValueError:
        pass

    if not is_linux():
        raise RuntimeError("docksmith run is only supported on Linux.")

    manifest = load_manifest(image_name)
    cid = uuid.uuid4().hex[:12]
    
    # Setup overlayfs rootfs
    rootfs, cont_dir = setup_overlayfs(manifest, image_name, cid)

    if cmd_override:
        cmd = cmd_override
    else:
        cmd = manifest.get("cmd")
        if not cmd:
            raise RuntimeError("No CMD found in image manifest.")

    if not isinstance(cmd, list):
        raise RuntimeError("CMD must be a list.")

    _validate_rootfs(rootfs, cmd)

    cg_path = None
    netns_name = None
    container_ip = None
    
    try:
        if rootless:
            if memory or cpus or pids_limit:
                raise RuntimeError("Resource limits (cgroups) are not supported in rootless mode.")
            if port_mappings:
                raise RuntimeError("Port mappings are not supported in rootless mode.")
            # We don't setup container network (bridge/veth) in rootless, just isolated loopback
        elif is_linux():
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

        def on_start(pid: int):
            save_state(cid, {
                "pid": pid,
                "cgroup_path": str(cg_path) if cg_path else None,
                "netns_name": netns_name,
                "rootless": rootless,
                "status": "running",
            })
            
        log_path = get_container_dir(cid) / "container.log"
        # Clear log file if it exists from a previous run
        log_path.write_bytes(b"")

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
            rootless=rootless,
            seccomp_profile=seccomp_profile,
            log_path=log_path,
            on_start=on_start,
        )
        return int(proc.returncode)
    except RuntimeError:
        raise
    finally:
        update_state_status(cid, "exited")
        # Cleanup OverlayFS
        umount_res = subprocess.run(["umount", str(rootfs)], check=False)
        if umount_res.returncode != 0:
            print(f"Warning: Failed to unmount {rootfs}. Skipping directory removal to prevent data loss.", file=sys.stderr)
        else:
            if not keep:
                rm_tree(cont_dir)
            else:
                print(f"Container state preserved at {cont_dir}")
        
        if netns_name and container_ip:
            teardown_container_network(cid, container_ip, port_mappings)
            
        if cg_path and cg_path.exists():
            import time
            procs_file = cg_path / "cgroup.procs"
            try:
                if procs_file.exists():
                    pids = procs_file.read_text().split()
                    for p in pids:
                        try:
                            os.kill(int(p), signal.SIGKILL)
                        except OSError:
                            pass
                    if pids:
                        time.sleep(0.1)
            except OSError:
                pass
            try:
                cg_path.rmdir()
            except OSError as e:
                print(f"Warning: Failed to remove cgroup {cg_path}: {e}", file=sys.stderr)


def run_container_exec(image_name: str) -> None:
    """
    Replace current process with the container.
    Delegates to run_container since os.execvp can't be used with the wrapper.
    """
    raise SystemExit(run_container(image_name))
