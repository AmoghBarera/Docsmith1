# Docksmith Changelog

## [Unreleased]
### Fixed
- **High (Issue 3):** Fixed resource leaks on container exit by adding `SIGINT`/`SIGTERM` handlers and skipping `rm_tree` if `umount` fails.
- **Medium (Issue 5):** Fixed silent cgroup leaks by explicitly killing any remaining processes in the container's cgroup before attempting to remove it.
- **High (Issue 2):** Fixed race conditions in IP allocation (`network.py`) and container state management (`state.py`) by adding file locking via `fcntl`.
- **Critical (Issue 1):** Fixed a command injection vulnerability in `utils.py:chroot_run`. The inline Python script now uses `subprocess.call` with `shell=False` and passes command arguments as a list instead of a shell-interpolated string.
