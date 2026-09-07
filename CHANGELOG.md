# Docksmith Changelog

## [Unreleased]
### Fixed
- **High (Issue 2):** Fixed race conditions in IP allocation (`network.py`) and container state management (`state.py`) by adding file locking via `fcntl`.
- **Critical (Issue 1):** Fixed a command injection vulnerability in `utils.py:chroot_run`. The inline Python script now uses `subprocess.call` with `shell=False` and passes command arguments as a list instead of a shell-interpolated string.
