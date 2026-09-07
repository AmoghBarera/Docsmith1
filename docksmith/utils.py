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
import typing
from pathlib import Path


def docksmith_home() -> Path:
    """Root state directory (layers, cache, images, bases)."""
    base = os.environ.get("DOCKSMITH_HOME")
    if base:
        return Path(base).expanduser().resolve()
    return Path.home() / ".docksmith"

CAPS = {
    "CAP_CHOWN": 0,
    "CAP_DAC_OVERRIDE": 1,
    "CAP_DAC_READ_SEARCH": 2,
    "CAP_FOWNER": 3,
    "CAP_FSETID": 4,
    "CAP_KILL": 5,
    "CAP_SETGID": 6,
    "CAP_SETUID": 7,
    "CAP_SETPCAP": 8,
    "CAP_LINUX_IMMUTABLE": 9,
    "CAP_NET_BIND_SERVICE": 10,
    "CAP_NET_BROADCAST": 11,
    "CAP_NET_ADMIN": 12,
    "CAP_NET_RAW": 13,
    "CAP_IPC_LOCK": 14,
    "CAP_IPC_OWNER": 15,
    "CAP_SYS_MODULE": 16,
    "CAP_SYS_RAWIO": 17,
    "CAP_SYS_CHROOT": 18,
    "CAP_SYS_PTRACE": 19,
    "CAP_SYS_PACCT": 20,
    "CAP_SYS_ADMIN": 21,
    "CAP_SYS_BOOT": 22,
    "CAP_SYS_NICE": 23,
    "CAP_SYS_RESOURCE": 24,
    "CAP_SYS_TIME": 25,
    "CAP_SYS_TTY_CONFIG": 26,
    "CAP_MKNOD": 27,
    "CAP_LEASE": 28,
    "CAP_AUDIT_WRITE": 29,
    "CAP_AUDIT_CONTROL": 30,
    "CAP_SETFCAP": 31,
    "CAP_MAC_OVERRIDE": 32,
    "CAP_MAC_ADMIN": 33,
    "CAP_SYSLOG": 34,
    "CAP_WAKE_ALARM": 35,
    "CAP_BLOCK_SUSPEND": 36,
    "CAP_AUDIT_READ": 37,
    "CAP_PERFMON": 38,
    "CAP_BPF": 39,
    "CAP_CHECKPOINT_RESTORE": 40,
}


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
        files = os.listdir(root)
        if not files:
            # Empty directory, create empty tar
            with tarfile.open(dest_tar, "w") as tf:
                pass
        else:
            result = subprocess.run(
                ["tar", "-cf", str(dest_tar.resolve()), "-C", str(root)] + files,
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
            for dirpath, dirnames, filenames in os.walk(root, topdown=True):
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


def parse_memory_string(mem: str) -> int:
    """Parse memory strings like '512m', '1g' to bytes."""
    mem = mem.lower().strip()
    if mem.endswith("k"):
        return int(mem[:-1]) * 1024
    if mem.endswith("m"):
        return int(mem[:-1]) * 1024 * 1024
    if mem.endswith("g"):
        return int(mem[:-1]) * 1024 * 1024 * 1024
    return int(mem)


def setup_cgroup(cid: str, memory: str | None, cpus: str | None, pids: int | None) -> Path:
    """
    Sets up a cgroup v2 directory for the container and writes limits.
    Returns the path to the container's cgroup directory.
    """
    cg_base = Path("/sys/fs/cgroup")
    if not (cg_base / "cgroup.controllers").exists():
        raise RuntimeError("cgroup v2 unified hierarchy is not mounted at /sys/fs/cgroup. Please enable cgroup v2.")

    ds_cg = cg_base / "docksmith"
    ds_cg.mkdir(exist_ok=True)

    # Attempt to enable controllers in docksmith subtree
    try:
        (cg_base / "cgroup.subtree_control").write_text("+cpu +memory +pids\n")
    except OSError:
        pass

    try:
        (ds_cg / "cgroup.subtree_control").write_text("+cpu +memory +pids\n")
    except OSError:
        pass

    cg_path = ds_cg / cid
    cg_path.mkdir(exist_ok=True)

    if memory:
        bytes_val = parse_memory_string(memory)
        (cg_path / "memory.max").write_text(str(bytes_val))
    
    if cpus:
        val = float(cpus)
        quota = int(val * 100000)
        (cg_path / "cpu.max").write_text(f"{quota} 100000")
        
    if pids:
        (cg_path / "pids.max").write_text(str(pids))

    return cg_path


def chroot_run(
    rootfs: Path,
    cmd: list[str],
    *,
    check: bool = True,
    inject_dns: bool = True,
    cgroup_path: Path | None = None,
    cid: str | None = None,
    hostname: str | None = None,
    cap_add: list[str] | None = None,
    netns_name: str | None = None,
    rootless: bool = False,
    seccomp_profile: str | None = "default",
    log_path: Path | None = None,
    on_start: typing.Callable[[int], None] | None = None,
) -> subprocess.CompletedProcess:
    """
    Run a command inside a pivot_root environment with a fully prepared namespace.

    Sets up:
      - unshare: mount, UTS, IPC, PID, NET namespaces
      - bind-mounts /dev, /sys from the host (gives access to /dev/null, gpg, etc.)
      - mounts /proc in the new rootfs
      - Uses pivot_root instead of chroot for a stronger security boundary.
      - Sets the container hostname if specified, otherwise uses cid.
      - Drops capabilities from the bounding set (leaves minimal defaults or cap_add).
      - DNS: copies host /etc/resolv.conf into rootfs for the duration of the call,
        then restores the original (so it never leaks into a layer snapshot)

    This is the single authoritative place for all chroot execution in docksmith.
    Both builder (RUN steps) and runtime (container run) use this function so that
    any future fix or improvement applies everywhere automatically.
    """
    if not is_linux():
        raise RuntimeError("chroot_run is only supported on Linux.")

    rootfs_abs = str(rootfs.resolve())
    
    keep_caps_ints = {0, 1, 3, 5, 6, 7}  # CHOWN, DAC_OVERRIDE, FOWNER, KILL, SETUID, SETGID
    if cap_add:
        for cap in cap_add:
            cap_upper = cap.upper()
            if not cap_upper.startswith("CAP_"):
                cap_upper = f"CAP_{cap_upper}"
            if cap_upper not in CAPS:
                raise ValueError(f"Unknown capability: {cap}")
            keep_caps_ints.add(CAPS[cap_upper])

    # --- DNS injection ---
    guest_resolv = rootfs / "etc" / "resolv.conf"
    host_resolv = Path("/etc/resolv.conf")
    resolv_backup: bytes | None = None
    if inject_dns and host_resolv.is_file():
        guest_resolv.parent.mkdir(parents=True, exist_ok=True)
        if guest_resolv.is_file():
            resolv_backup = guest_resolv.read_bytes()
        shutil.copy2(host_resolv, guest_resolv)

    # --- Wrapper: bind-mount /dev and /sys, mount /proc, then pivot_root ---
    # We use an inline Python script run by the host's Python executable.
    # This avoids dynamic linking issues if we try to execute host binaries (like umount)
    # after the root has been pivoted.
    wrapper = f'''
import os
import sys
import subprocess
import ctypes
import ctypes.util
import socket

def run(c, msg):
    if subprocess.call(c, shell=False) != 0:
        print(f"Error: {{msg}}", file=sys.stderr)
        sys.exit(1)

rootfs = {repr(rootfs_abs)}
old_root = os.path.join(rootfs, ".old_root")

run(["mount", "--bind", rootfs, rootfs], "bind mount rootfs onto itself failed")
os.makedirs(old_root, exist_ok=True)
os.makedirs(os.path.join(rootfs, "dev"), exist_ok=True)
run(["mount", "--bind", "/dev", os.path.join(rootfs, "dev")], "mount /dev failed")
os.makedirs(os.path.join(rootfs, "sys"), exist_ok=True)
run(["mount", "--bind", "/sys", os.path.join(rootfs, "sys")], "mount /sys failed")
os.makedirs(os.path.join(rootfs, "proc"), exist_ok=True)
run(["mount", "-t", "proc", "proc", os.path.join(rootfs, "proc")], "mount /proc failed")

# system pivot_root before chdir
run(["pivot_root", rootfs, old_root], "pivot_root failed")

try:
    os.chdir("/")
except Exception as e:
    print(f"Error: chdir / failed: {{e}}", file=sys.stderr)
    sys.exit(1)

# Set Hostname
try:
    target_hostname = {repr(hostname)}
    target_cid = {repr(cid)}
    if target_hostname:
        socket.sethostname(target_hostname)
    elif target_cid:
        socket.sethostname(target_cid)
except Exception as e:
    print(f"Error: sethostname failed: {{e}}", file=sys.stderr)
    sys.exit(1)

# Now use ctypes for umount2 so we don't need umount inside the container
libc_path = ctypes.util.find_library("c") or "libc.so.6"
libc = ctypes.CDLL(libc_path)

# MNT_DETACH = 2
if libc.umount2(b"/.old_root", 2) != 0:
    print("Error: umount2 /.old_root failed", file=sys.stderr)
    sys.exit(1)

try:
    os.rmdir("/.old_root")
except Exception as e:
    print(f"Error: rmdir /.old_root failed: {{e}}", file=sys.stderr)
    sys.exit(1)

# Drop capabilities
try:
    PR_CAPBSET_DROP = 24
    caps_to_keep = {repr(keep_caps_ints)}
    for cap in range(64):
        if cap not in caps_to_keep:
            libc.prctl(PR_CAPBSET_DROP, cap, 0, 0, 0)
except Exception as e:
    print(f"Error dropping capabilities: {{e}}", file=sys.stderr)
    sys.exit(1)

cmd = {repr(cmd)}
if {repr(seccomp_profile)} != "unconfined":
    import ctypes
    
    # Blocked syscalls for default profile (x86_64)
    blocked_syscalls = [
        165, # mount
        166, # umount2
        167, # swapon
        168, # swapoff
        169, # reboot
        175, # init_module
        176, # delete_module
        246, # kexec_load
        313, # finit_module
    ]
    
    BPF_LD_W_ABS = 0x20
    BPF_JMP_JEQ_K = 0x15
    BPF_RET_K = 0x06
    SECCOMP_RET_ERRNO = 0x00050000 | 1
    SECCOMP_RET_ALLOW = 0x7fff0000

    class sock_filter(ctypes.Structure):
        _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8), ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32)]

    class sock_fprog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(sock_filter))]

    filters = [sock_filter(BPF_LD_W_ABS, 0, 0, 0)]
    for sc in blocked_syscalls:
        filters.append(sock_filter(BPF_JMP_JEQ_K, 0, 1, sc))
        filters.append(sock_filter(BPF_RET_K, 0, 0, SECCOMP_RET_ERRNO))
    filters.append(sock_filter(BPF_RET_K, 0, 0, SECCOMP_RET_ALLOW))
    
    FilterArray = sock_filter * len(filters)
    prog = sock_fprog(len(filters), FilterArray(*filters))
    
    libc = ctypes.CDLL(libc_path, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0: # PR_SET_NO_NEW_PRIVS
        print(f"Warning: prctl(PR_SET_NO_NEW_PRIVS) failed: {{ctypes.get_errno()}}", file=sys.stderr)
    
    if libc.prctl(22, 2, ctypes.byref(prog)) != 0: # PR_SET_SECCOMP
        print(f"Warning: prctl(PR_SET_SECCOMP) failed: {{ctypes.get_errno()}}", file=sys.stderr)

try:
    os.execvp(cmd[0], cmd)
except Exception as e:
    print(f"Error: execvp {{cmd}} failed: {{e}}", file=sys.stderr)
    sys.exit(1)
'''
    argv = []
    if not rootless and netns_name:
        argv.extend(["nsenter", f"--net=/var/run/netns/{netns_name}"])

    argv.extend(["unshare"])
    
    if rootless:
        argv.extend(["--user", "--map-root-user"])

    argv.extend([
        "--mount",
        "--uts",
        "--ipc",
        "--pid",
    ])
    
    if rootless or not netns_name:
        argv.append("--net")
        
    argv.extend([
        "--fork",
        sys.executable, "-c",
        wrapper,
    ])

    def preexec():
        if cgroup_path:
            try:
                with open(cgroup_path / "cgroup.procs", "w") as f:
                    f.write(str(os.getpid()))
            except OSError as exc:
                print(f"Failed to write to cgroup.procs: {exc}", file=sys.stderr)

    stdout_arg = subprocess.PIPE if log_path else None
    stderr_arg = subprocess.STDOUT if log_path else None
    
    try:
        proc = subprocess.Popen(argv, preexec_fn=preexec, stdout=stdout_arg, stderr=stderr_arg, text=False)
        if on_start:
            on_start(proc.pid)
            
        if log_path:
            import threading
            def pump():
                with open(log_path, "ab") as f:
                    while True:
                        chunk = proc.stdout.read(4096)
                        if not chunk:
                            break
                        f.write(chunk)
                        f.flush()
                        sys.stdout.buffer.write(chunk)
                        sys.stdout.buffer.flush()
            t = threading.Thread(target=pump, daemon=True)
            t.start()
            
        proc.wait()
    except FileNotFoundError as e:
        raise RuntimeError(
            "unshare not found. Install util-linux and run as root."
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

    return subprocess.CompletedProcess(args=argv, returncode=proc.returncode, stdout=b"", stderr=b"")


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

    h.update(src_pattern.encode())
    for root, dirs, files in os.walk(src):
        dirs.sort()
        files.sort()
        root_path = Path(root)
        
        for d in dirs:
            p = root_path / d
            rel = p.relative_to(src).as_posix()
            h.update(rel.encode())
            h.update(b"\0")
            if p.is_symlink():
                h.update(b"link\0")
                h.update(os.readlink(p).encode())
            else:
                h.update(b"dir\0")
            h.update(b"|")
            
        for f in files:
            p = root_path / f
            rel = p.relative_to(src).as_posix()
            h.update(rel.encode())
            h.update(b"\0")
            if p.is_symlink():
                h.update(b"link\0")
                h.update(os.readlink(p).encode())
            elif p.is_file():
                h.update(sha256_file(p).encode())
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
