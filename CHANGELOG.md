# Docksmith Changelog

## [Unreleased]
### Fixed
- **Medium (Issue 6):** Optimized memory usage during `COPY` hashing by using `os.walk` to incrementally stream and hash file paths, instead of loading all `rglob` results into memory.
- **High (Issue 4):** Fixed redundant full-filesystem layer snapshots in `builder.py`. The builder now uses `overlayfs` during the build process, capturing only the `upperdir` diffs for each layer. This significantly reduces storage space and improves build performance.
- **High (Issue 3):** Fixed resource leaks on container exit by adding `SIGINT`/`SIGTERM` handlers and skipping `rm_tree` if `umount` fails.
- **Medium (Issue 5):** Fixed silent cgroup leaks by explicitly killing any remaining processes in the container's cgroup before attempting to remove it.
- **High (Issue 2):** Fixed race conditions in IP allocation (`network.py`) and container state management (`state.py`) by adding file locking via `fcntl`.
- **Critical (Issue 1):** Fixed a command injection vulnerability in `utils.py:chroot_run`. The inline Python script now uses `subprocess.call` with `shell=False` and passes command arguments as a list instead of a shell-interpolated string.
