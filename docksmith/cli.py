"""
CLI: docksmith build | run | images | rmi
"""

from __future__ import annotations

import argparse
import sys
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
            memory=args.memory,
            cpus=args.cpus,
            pids_limit=args.pids_limit,
            cap_add=args.cap_add,
            hostname=args.hostname,
            port_mappings=args.publish,
        )
    except Exception as e:
        print(f"run failed: {e}", file=sys.stderr)
        return 1

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
    pr.add_argument("--memory", help="Memory limit (e.g. 512m, 1g)")
    pr.add_argument("--cpus", help="CPU limit (e.g. 1.0, 0.5)")
    pr.add_argument("--pids-limit", type=int, help="PIDs limit")
    pr.add_argument("--cap-add", action="append", help="Add a capability (e.g. CAP_SYS_ADMIN)")
    pr.add_argument("--hostname", help="Container hostname")
    pr.add_argument("-p", "--publish", action="append", help="Publish a container's port to the host (e.g. 8080:80)")
    pr.set_defaults(func=_cmd_run)

    pi = sub.add_parser("images", help="List images")
    pi.set_defaults(func=_cmd_images)

    px = sub.add_parser("rmi", help="Remove an image manifest")
    px.add_argument("image", help="Image name")
    px.set_defaults(func=_cmd_rmi)

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
