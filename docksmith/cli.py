"""
CLI: docksmith build | run | images | rmi
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import os
from pathlib import Path

from docksmith import __version__
from docksmith.builder import build_from_path
from docksmith.manifest import delete_manifest, list_images
from docksmith.runtime import run_container


def _cmd_build(args: argparse.Namespace) -> int:
    ctx = Path(args.context).resolve()
    try:
        build_from_path(ctx, args.tag, log=print)
    except Exception as e:
        print(f"build failed: {e}", file=sys.stderr)
        return 1
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        return run_container(
            args.image,
            cmd_override=args.cmd_override,
            memory=args.memory,
            cpus=args.cpus,
            pids_limit=args.pids_limit,
            cap_add=args.cap_add,
            hostname=args.hostname,
            port_mappings=args.publish,
            keep=args.keep,
            rootless=args.rootless,
            seccomp_profile=args.seccomp,
        )
    except Exception as e:
        print(f"run failed: {e}", file=sys.stderr)
        return 1

def _cmd_layers(_args: argparse.Namespace) -> int:
    from docksmith.utils import images_dir
    if not images_dir().exists():
        print("No layers found.")
        return 0
        
    print("IMAGE\tLAYER ID")
    found = False
    for image_dir in images_dir().iterdir():
        if image_dir.is_dir():
            for layer_dir in image_dir.iterdir():
                if layer_dir.is_dir():
                    found = True
                    print(f"{image_dir.name}\t{layer_dir.name}")
                    
    if not found:
        print("No layers found.")
    return 0

def _cmd_network(args: argparse.Namespace) -> int:
    if args.net_command == "setup":
        from docksmith.network import setup_bridge
        try:
            setup_bridge()
            return 0
        except Exception as e:
            print(f"network setup failed: {e}", file=sys.stderr)
            return 1
    return 1


def _cmd_images(_args: argparse.Namespace) -> int:
    names = list_images()
    if not names:
        print("REPOSITORY\tTAG")
        print("(none)")
        return 0
    print("IMAGE")
    for n in names:
        print(n)
    return 0


def _cmd_rmi(args: argparse.Namespace) -> int:
    from docksmith.manifest import manifest_path

    mp = manifest_path(args.image)
    if delete_manifest(args.image):
        print(f"Removed image {args.image} (manifest was {mp})")
        return 0
    print(f"Image not found: {args.image}", file=sys.stderr)
    return 1


def _cmd_exec(args: argparse.Namespace) -> int:
    from docksmith.state import load_state
    state = load_state(args.id)
    if not state or state.get("status") != "running":
        print(f"Container {args.id} is not running.")
        return 1
        
    unshare_pid = state["pid"]
    
    # Find child pid
    try:
        res = subprocess.run(["ps", "-o", "pid", "--no-headers", "--ppid", str(unshare_pid)], capture_output=True, text=True, check=True)
        child_pid = res.stdout.strip().split('\n')[0].strip()
        if not child_pid:
            raise ValueError
    except Exception:
        print(f"Could not find container process for container {args.id}")
        return 1

    cmd = ["nsenter", "-t", child_pid, "--all"] + args.cmd
    try:
        os.execvp(cmd[0], cmd)
    except OSError as e:
        print(f"exec failed: {e}")
        return 1
    return 0

def _cmd_logs(args: argparse.Namespace) -> int:
    from docksmith.state import get_container_dir
    log_path = get_container_dir(args.id) / "container.log"
    if not log_path.exists():
        print(f"No logs found for {args.id}")
        return 1
        
    if not args.f:
        sys.stdout.buffer.write(log_path.read_bytes())
        return 0
        
    with open(log_path, "rb") as f:
        while True:
            chunk = f.read(4096)
            if not chunk:
                time.sleep(0.1)
                continue
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
    return 0

def _cmd_stats(args: argparse.Namespace) -> int:
    from docksmith.state import load_state
    
    def format_bytes(b: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if b < 1024: return f"{b:.2f} {unit}"
            b /= 1024
        return f"{b:.2f} TB"

    print(f"{'CONTAINER ID':<20} {'CPU %':<10} {'MEM USAGE / LIMIT':<30} {'NET I/O (RX / TX)'}")
    
    cids = [args.id] if args.id else []
    if not cids:
        from docksmith.utils import docksmith_home
        containers_dir = docksmith_home() / "containers"
        if containers_dir.exists():
            cids = [d.name for d in containers_dir.iterdir() if d.is_dir()]
            
    for cid in cids:
        state = load_state(cid)
        if not state or state.get("status") != "running":
            continue
            
        cg = Path(state["cgroup_path"]) if state.get("cgroup_path") else None
        mem_usage = "N/A"
        mem_max = "N/A"
        cpu_pct = "N/A"
        
        if cg and cg.exists():
            try:
                mem = int((cg / "memory.current").read_text().strip())
                mem_usage = format_bytes(mem)
                mx = (cg / "memory.max").read_text().strip()
                mem_max = "unlimited" if mx == "max" else format_bytes(int(mx))
            except Exception: pass
            
            try:
                stat = (cg / "cpu.stat").read_text()
                usage = 0
                for line in stat.splitlines():
                    if line.startswith("usage_usec"):
                        usage = int(line.split()[1])
                # One-shot stat: just print total cpu time used (since we'd need to measure delta over time for %)
                # For simplicity in v1, display total ms used
                cpu_pct = f"{usage / 1000:.0f}ms (total)"
            except Exception: pass
            
        net_io = "N/A"
        netns = state.get("netns_name")
        if netns:
            try:
                res = subprocess.run(["nsenter", f"--net=/var/run/netns/{netns}", "cat", "/proc/net/dev"], capture_output=True, text=True)
                for line in res.stdout.splitlines():
                    if "eth0:" in line:
                        parts = line.split(":")[1].split()
                        rx = format_bytes(int(parts[0]))
                        tx = format_bytes(int(parts[8]))
                        net_io = f"{rx} / {tx}"
            except Exception: pass
            
        print(f"{cid[:20]:<20} {cpu_pct:<10} {mem_usage} / {mem_max:<10} {net_io}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="docksmith",
        description="Docksmith - a minimal container image builder and runner (Linux).",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    pb = sub.add_parser("build", help="Build an image from a Docksmithfile")
    pb.add_argument("-t", "--tag", required=True, help="Image name / tag")
    pb.add_argument(
        "context",
        nargs="?",
        default=".",
        help="Build context directory (default: .)",
    )
    pb.set_defaults(func=_cmd_build)

    pr = sub.add_parser("run", help="Run a container from a built image")
    pr.add_argument("image", help="Image name")
    pr.add_argument("cmd_override", nargs=argparse.REMAINDER, help="Override default CMD")
    pr.add_argument("--memory", help="Memory limit (e.g. 512m, 1g)")
    pr.add_argument("--cpus", help="CPU limit (e.g. 1.0, 0.5)")
    pr.add_argument("--pids-limit", type=int, help="PIDs limit")
    pr.add_argument("--cap-add", action="append", help="Add a capability (e.g. CAP_SYS_ADMIN)")
    pr.add_argument("--hostname", help="Container hostname")
    pr.add_argument("-p", "--publish", action="append", help="Publish a container's port to the host (e.g. 8080:80)")
    pr.add_argument("--keep", action="store_true", help="Keep the container's overlayfs directories after exit")
    pr.add_argument("--rootless", action="store_true", help="Run in rootless mode using user namespaces")
    pr.add_argument("--seccomp", default="default", help="Seccomp profile (e.g. 'unconfined', 'default')")
    pr.set_defaults(func=_cmd_run)

    pi = sub.add_parser("images", help="List images")
    pi.set_defaults(func=_cmd_images)
    
    pl = sub.add_parser("layers", help="List extracted image layers")
    pl.set_defaults(func=_cmd_layers)

    px = sub.add_parser("rmi", help="Remove an image manifest")
    px.add_argument("image", help="Image name")
    px.set_defaults(func=_cmd_rmi)
    
    pe = sub.add_parser("exec", help="Run a command in a running container")
    pe.add_argument("id", help="Container ID")
    pe.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to run")
    pe.set_defaults(func=_cmd_exec)
    
    pl = sub.add_parser("logs", help="View container logs")
    pl.add_argument("id", help="Container ID")
    pl.add_argument("-f", action="store_true", help="Follow log output")
    pl.set_defaults(func=_cmd_logs)
    
    ps = sub.add_parser("stats", help="View container stats")
    ps.add_argument("id", nargs="?", help="Container ID (optional, shows all running if omitted)")
    ps.set_defaults(func=_cmd_stats)

    pn = sub.add_parser("network", help="Network management")
    pn_sub = pn.add_subparsers(dest="net_command", required=True)
    pn_setup = pn_sub.add_parser("setup", help="Setup host-side bridge and NAT")
    pn.set_defaults(func=_cmd_network)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
