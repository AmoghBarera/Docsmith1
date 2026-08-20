# Rootless Mode

Docksmith natively supports running containers without privileges using Linux User Namespaces.

By passing the `--rootless` flag, Docksmith leverages `CLONE_NEWUSER` to securely map the invoking unprivileged host user to the root (`UID 0`) user inside the container environment.

## Usage

```bash
# Run a rootless container
docksmith run --rootless alpine id
```

Inside the container, processes will see themselves running as `root` (uid=0). However, on the host system, they will execute safely entirely under your standard, unprivileged user account.

## Incompatibilities

Currently, some advanced features still require host-side root privileges to modify kernel subsystems and are structurally incompatible with `--rootless`. If you attempt to use these flags alongside `--rootless`, Docksmith will safely refuse to start the container rather than failing silently.

- **Bridge Networking (`-p` / `--publish`)**: Creating `veth` pairs and joining them to the `docksmith0` host bridge requires host root. Rootless containers will run inside a fully isolated network namespace containing only the `lo` loopback interface. They will not have outbound internet access.
- **Resource Limits (`--memory`, `--cpus`, `--pids-limit`)**: Configuring `cgroups` v2 limits requires root access (unless `systemd` delegation is manually configured by an administrator). Resource limits are disabled in rootless mode.

## Future Work

Currently, `--rootless` relies on `unshare --map-root-user`, which establishes a simple 1:1 UID mapping. In the future, this can be expanded to parse `/etc/subuid` and `/etc/subgid` utilizing the `newuidmap` and `newgidmap` binaries to allow for richer, multi-user ranges inside the unprivileged container.
