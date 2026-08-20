# Contributing to Docksmith

Thank you for your interest in contributing to Docksmith! 

Since Docksmith builds and tests deeply integrated Linux container namespaces and cgroup limits, our testing strategy requires a bit more setup than a standard Python project.

## Running Tests

We split our tests into two categories:

### 1. Unit Tests (Fast, Unprivileged)
Unit tests cover pure logic (like argument parsing, IP allocation arithmetic, and memory string conversions). These can be run on any OS and do not require root privileges.

```bash
pytest tests/test_utils.py tests/test_parser.py tests/test_cache.py tests/test_builder.py
```

### 2. Integration Tests (Requires Linux & Root)
Integration tests actually execute `pivot_root`, bind mounts, namespace `unshare`, and cgroup v2 modifications. These **must** be run on a Linux machine (or VM) with root privileges. 

We strongly recommend running these tests carefully as root, as they interact with system-level resources.

```bash
sudo env PATH="$PATH" PYTHONPATH="$PYTHONPATH" pytest tests/test_integration.py tests/test_isolation.py
```

## Continuous Integration (CI)
Our GitHub Actions workflow automatically handles testing on every PR. It runs the unit tests natively, and utilizes the passwordless `sudo` provided by GitHub's `ubuntu-latest` runners to thoroughly verify the integration tests in a safe, ephemeral environment.

## Benchmarks
If you are optimizing critical paths (like container startup or memory footprint), please run our benchmark suite against your changes and include the output in your PR:

```bash
sudo python benchmarks/bench.py
```
