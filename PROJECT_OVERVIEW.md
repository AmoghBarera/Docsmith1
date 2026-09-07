# Docksmith Project Overview

Welcome to Docksmith, a lightweight, Python-based Linux container engine. Docksmith enables building images from Docksmithfiles (similar to Dockerfiles) and running isolated containers using native Linux primitives. The core philosophy of Docksmith is to assemble complex containerization abstractions (`namespaces`, `cgroups`, `overlayfs`, `seccomp`, `pivot_root`) using transparent, easily readable Python code and standard Linux CLI utilities.

## 🏗 Deep Dive: Architecture & Implementation

Docksmith acts as a CLI tool (`docksmith/cli.py`) and is divided into three major architectural pillars: Image Building/Storage, Process Isolation, and Networking.

### 1. OverlayFS & Layer Storage
Docksmith utilizes a content-addressable storage model for container image layers.
- **Storage Strategy (`layer_store.py`)**: Individual image layers are stored as tarballs in `~/.docksmith/layers/<sha256>.tar`. Image manifests, which define the ordered list of layers, environment variables, and the entrypoint command, are tracked in `~/.docksmith/images/`.
- **OverlayFS Build Process (`builder.py`)**: When building an image, Docksmith mounts an `overlayfs` filesystem. The previous layers form the read-only `lowerdir` stack, while a blank directory serves as the `upperdir`. As commands (like `RUN` or `COPY`) are executed, all filesystem modifications are captured exclusively in the `upperdir`. Docksmith then tars only the `upperdir`, producing a minimal, atomic layer diff.
- **Caching (`cache.py`)**: A cache key is generated for each build step by hashing the previous layer's digest combined with the exact instruction text. This ensures idempotent builds and allows skipping redundant steps.

### 2. Process Isolation (`runtime.py` and `utils.py`)
Container execution relies on strict boundaries to jail processes and restrict their resource consumption.
- **Namespaces (`unshare`)**: Containers are launched within new Mount, PID, UTS, and Network namespaces via the Linux `unshare` utility.
- **Cgroups (`runtime.py`)**: Resource limits (memory, CPU) are enforced by creating a dedicated control group (cgroup) under `/sys/fs/cgroup/` for each container. The container's primary PID is written to `cgroup.procs`.
- **The Execution Wrapper (`chroot_run`)**: The most critical primitive. `chroot_run` wraps the target command in a highly privileged, inline Python script executed *inside* the new namespaces.
  - **Mounts**: It bind-mounts `/dev`, `/sys`, and `/proc` into the new root.
  - **`pivot_root`**: It executes a system `pivot_root` to firmly jail the process inside the assembled `overlayfs` filesystem, swapping the host root out entirely.
  - **Seccomp & Capabilities**: Before yielding control to the target binary via `os.execvp`, the wrapper uses `ctypes` to invoke `prctl` and `libseccomp`, dropping unnecessary root capabilities and applying Berkeley Packet Filter (BPF) rules to restrict dangerous syscalls.

### 3. Networking (`network.py`)
Docksmith provides a robust virtual network for containers to communicate with each other and the outside world.
- **Bridge Network**: A host bridge (`docksmith0`) is provisioned with a default `/24` subnet (e.g., `172.30.0.1/24`). `MASQUERADE` iptables rules are applied to enable outbound internet access.
- **IP Allocation**: Containers are dynamically assigned unique IP addresses tracked via a JSON-backed IP pool (`ip_pool.json`). File locking (`fcntl`) guarantees thread-safe allocations during concurrent orchestrations.
- **Veth Pairs**: A virtual ethernet (`veth`) pair is created. One end remains on the host and is attached to the `docksmith0` bridge, while the other end is injected into the container's isolated network namespace and configured with the allocated IP.
- **Port Mapping**: Incoming traffic is routed from the host to the container via `iptables` `DNAT` (Destination Network Address Translation) rules targeting the specific container IP.

## 📂 Codebase Structure

```
docksmith/
├── docksmith/                 # Core package
│   ├── builder.py             # Docksmithfile execution, overlayfs mounts, tar snapshotting
│   ├── cache.py               # Cryptographic hashing for layer hit/miss logic
│   ├── cli.py                 # Argument parsing and primary entrypoints (build, run, etc.)
│   ├── layer_store.py         # Reading, extracting, and writing raw layer tarballs
│   ├── manifest.py            # Image manifest (CMD, ENV, WORKDIR, layer arrays) CRUD operations
│   ├── network.py             # Bridge setup, veth pairs, iptables, and IP allocation
│   ├── parser.py              # Parsing Docksmithfile syntax (handling continuations, quotes)
│   ├── runtime.py             # Container lifecycle, cgroups, signal handling, and cleanup
│   ├── state.py               # Container state tracking (running, exited)
│   └── utils.py               # Core primitives: chroot_run, filesystem hashing, platform checks
├── tests/                     # Pytest suite
│   ├── test_builder.py        # Validates image building, layer creation, and cache hits
│   ├── test_integration.py    # End-to-end container testing (building and executing)
│   ├── test_isolation.py      # Verifies PID namespaces, seccomp filters, and rootless behaviors
│   └── test_parser.py         # Validates syntax parsing and instruction extraction
```

## 🛠 Design Decisions & Recent Improvements

During the latest codebase audit and remediation cycle, several critical improvements were implemented:
- **Diff-Based Layer Snapshotting**: Shifted from an $O(N^2)$ full-filesystem copy strategy to a true diff-based `overlayfs` snapshotting mechanism.
- **Concurrency Safety**: Implemented strict `fcntl` locks around the `state.json` and `ip_pool.json` files. Multiple containers can now be launched and destroyed simultaneously without state corruption.
- **Graceful Cleanup & Resource Management**: Bound `SIGTERM`/`SIGINT` handlers to ensure `overlayfs` mounts are cleanly detached and zombie processes within `cgroups` are `SIGKILL`'d before hierarchy teardown.
- **Security Hardening**: Neutralized local command injection vulnerabilities inside the `chroot_run` wrapper by migrating from dynamic string interpolation to strict list-based arguments with `shell=False`.

## 🚀 Onboarding

### Requirements
- A modern Linux environment (Ubuntu 22.04+ recommended)
- `python3.10+`
- `util-linux` (`unshare`, `pivot_root`)
- `iproute2` and `iptables`
- Execution as `root` (or via `sudo`) is required for full functionality (overlayfs, networking, and cgroups). A limited `rootless` mode is supported for specific isolation tests.

### Quick Start
1. Clone the repository and install the module or add it to your `PYTHONPATH`.
2. Build an image from a Docksmithfile:
   ```bash
   sudo python3 docksmith/cli.py build -t my-app .
   ```
3. Run the container interactively:
   ```bash
   sudo python3 docksmith/cli.py run my-app
   ```
4. Run the unit and integration test suite:
   ```bash
   sudo PYTHONPATH='.' pytest tests/
   ```
