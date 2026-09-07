# Docksmith Changelog

## [Unreleased]
### Fixed
- **Critical (Issue 1):** Fixed a command injection vulnerability in `utils.py:chroot_run`. The inline Python script now uses `subprocess.call` with `shell=False` and passes command arguments as a list instead of a shell-interpolated string.
