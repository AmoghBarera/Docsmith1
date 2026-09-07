# Docksmith Project Overview

Welcome to Docksmith, a lightweight, Python-based Linux container engine. Docksmith enables building images from Docksmithfiles (similar to Dockerfiles) and running isolated containers using native Linux primitives (`namespaces`, `cgroups`, `overlayfs`, `seccomp`, etc.).

## 🏗 Architecture

Docksmith is fundamentally built around the concept of composing Linux features to achieve containerization. The engine executes as a CLI tool (`docksmith/cli.py`) and divides its responsibilities into image building, storage, and container runtime.

### Storage & OverlayFS
- **Layer Storage**: Image layers are stored as content-addressable tarballs in `~/.docksmith/layers/`. 
- **Caching**: The builder (`builder.py`) uses a cache key based on the previous layer's digest and the instruction text.
- **OverlayFS**: For container runtime and during build operations, Docksmith uses `overlayfs`. Multiple layer tarballs are extracted into `~/.docksmith/images/<image>/<digest>` and stacked as `lowerdir` components. An empty `upperdir` acts as the read-write layer for the running container.

### Execution Flow (`runtime.py` and `utils.py`)
- **`run_container`**: Evaluates the image manifest, sets up the network bridge, sets resource limits via cgroups, and prepares the `overlayfs` mount.
- **`chroot_run`**: The core execution primitive. It wraps the target binary in a highly privileged Python script executed within an `unshare` context. It drops capabilities, applies `seccomp` filters via BPF (Berkeley Packet Filter), bind-mounts `/dev`, `/sys`, and `/proc`, and executes a `pivot_root` to jail the process inside the assembled filesystem.

### Networking (`network.py`)
- Docksmith implements simple bridge networking. A host bridge (`docksmith0`) is created with a default subnet (`172.30.0.1/24`).
- Containers are assigned unique IPs from an IP pool (`ip_pool.json`).
- Virtual Ethernet (`veth`) pairs connect the container's network namespace to the host bridge. Port forwarding is handled via `iptables` DNAT rules.

## 📂 Codebase Structure

```
docksmith/
├── docksmith/                 # Core package
│   ├── builder.py             # Parses Docksmithfiles and snapshots image layers
│   ├── cache.py               # Cache hit/miss logic for layer digests
│   ├── cli.py                 # Argument parsing and entrypoints (build, run)
│   ├── layer_store.py         # Reads/writes raw layer tarballs to ~/.docksmith
│   ├── manifest.py            # Manages image manifests (CMD, ENV, WORKDIR)
│   ├── network.py             # Bridge, veth pairs, iptables, and IP allocation
│   ├── parser.py              # Parses Docksmithfile syntax (FROM, COPY, RUN, etc.)
│   ├── runtime.py             # Container lifecycle, cgroups, and cleanup
│   ├── state.py               # Container state tracking (state.json)
│   └── utils.py               # Core primitives: chroot_run, hashing, tarring
├── tests/                     # Pytest suite
│   ├── test_builder.py        # Validates image building and caching
│   ├── test_integration.py    # End-to-end container testing
│   └── test_isolation.py      # Verifies PID namespaces, seccomp, and rootless
```

## 🛠 Design Decisions & Recent Improvements

During the latest codebase audit, several critical improvements were made:
- **Diff-Based Layer Snapshotting**: `builder.py` was refactored to mount `overlayfs` during the image build process. Instead of performing an $O(N^2)$ full-filesystem snapshot for each instruction, Docksmith now relies on the `upperdir` to capture atomic diffs, drastically reducing disk space and improving build speeds.
- **Concurrency Safety**: File locks (`fcntl`) were added to IP allocation and state management to prevent corruption when launching multiple containers simultaneously.
- **Graceful Cleanup**: Signal handlers (`SIGTERM`, `SIGINT`) were implemented to ensure proper `umount` of overlay filesystems and destruction of `cgroups`, preventing zombie processes and resource leaks.
- **Security**: The `chroot_run` wrapper was hardened to prevent local command injection via dynamic shell generation.

## 🚀 Onboarding

### Requirements
- A modern Linux environment (Ubuntu 22.04+ recommended)
- `python3.10+`
- `util-linux` (`unshare`, `pivot_root`)
- `iproute2` and `iptables`
- Run as `root` (or `sudo`) for full functionality. `rootless` mode is supported but lacks networking and cgroup features.

### Quick Start
1. Ensure `docksmith` is in your `PYTHONPATH` or installed as an editable module.
2. Build an image: `sudo python3 docksmith/cli.py build -t my-app .`
3. Run the container: `sudo python3 docksmith/cli.py run my-app`
4. Run tests: `sudo pytest docksmith/tests`
