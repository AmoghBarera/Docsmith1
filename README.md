# Docksmith

Docksmith is a **small, educational container engine** written in Python 3.11+. It provides a CLI to **build** images from a `Docksmithfile`, **cache** layers deterministically, **store** content-addressed tar layers, and **run** containers on Linux using **namespaces** and **chroot**.

This is not a production container runtime; it is designed to be **readable** and **explainable** in interviews or coursework.

## Architecture

```text
┌─────────────┐     ┌──────────┐     ┌─────────────┐     ┌──────────────┐
│ Docksmithfile│────▶│ parser   │────▶│ builder     │────▶│ layer_store  │
└─────────────┘     └──────────┘     │  + cache     │     │ ~/.docksmith │
                                     └──────┬──────┘     │   /layers    │
                                            │          └──────────────┘
                                            ▼
                                     ┌──────────────┐
                                     │ manifest.json │
                                     │ ~/.docksmith │
                                     │   /images    │
                                     └──────┬───────┘
                                            │
                                     ┌──────▼───────┐
                                     │ runtime      │
                                     │ unshare+     │
                                     │ chroot+CMD   │
                                     └──────────────┘
```

- **`parser.py`** — Tokenizes instructions (`FROM`, `COPY`, `RUN`, `WORKDIR`, `ENV`, `CMD`) into structured objects.
- **`builder.py`** — Walks instructions, applies `COPY`/`RUN` to a temporary rootfs, snapshots full rootfs tars, stores layers, writes manifests.
- **`cache.py`** — Keys: `SHA256(prev_layer_digest + instruction + content_hash)`; values: layer digest.
- **`layer_store.py`** — Content-addressed storage: `~/.docksmith/layers/<sha256>.tar`.
- **`manifest.py`** — Image metadata: name, base, layer digests, env, cmd, workdir.
- **`runtime.py`** — Merges layers into a temp rootfs, runs `unshare` + `chroot` + `/bin/sh` to apply env/workdir and `exec` the configured command.

## Workflow

1. **Build** — Parse file → execute steps → each `FROM` / `COPY` / `RUN` produces a **full rootfs snapshot** tar → digest → store → update cache map.
2. **Run** — Load manifest → extract layer tars **in order** into a temp directory → `unshare` (mount, UTS, IPC, PID) + `chroot` → shell sets `ENV`, `cd` to `WORKDIR`, `exec` `CMD`.

## Commands

From the project directory (where `main.py` lives):

```bash
python main.py build -t myimage .
python main.py run myimage
python main.py images
python main.py rmi myimage
```

Or:

```bash
python -m docksmith build -t myimage .
```

Override state directory:

```bash
export DOCKSMITH_HOME=/tmp/docksmith-test
```

## Docksmithfile

Supported instructions:

| Instruction | Behavior |
|-------------|----------|
| `FROM` | First line only. `FROM scratch` = empty rootfs. Otherwise expects `~/.docksmith/bases/<sanitized-name>.tar` (e.g. `ubuntu:latest` → `ubuntu_latest.tar`). |
| `WORKDIR` | Creates directories in the build rootfs; recorded in manifest. |
| `ENV` | Key/value pairs merged into manifest (applied at run time). |
| `COPY` | Copies from build context into rootfs; new **layer** (snapshot). |
| `RUN` | Runs a shell command **inside chroot** (Linux, usually **root**); new **layer**. |
| `CMD` | Default command for `docksmith run` (JSON or shell form). |

Example `examples/Docksmithfile` mirrors common Dockerfile patterns.

### Base images

Docksmith does not pull from a registry. To use something like `FROM ubuntu:latest`, export a rootfs tarball and place it at:

```text
~/.docksmith/bases/ubuntu_latest.tar
```

Example (with Docker installed elsewhere):

```bash
docker pull ubuntu:latest
docker export "$(docker create ubuntu:latest)" > ubuntu_latest.tar
mkdir -p ~/.docksmith/bases && mv ubuntu_latest.tar ~/.docksmith/bases/ubuntu_latest.tar
```

## Caching

For each layer-producing step, a **cache key** is computed:

```text
cache_key = SHA256(
    previous_layer_digest
    + "\\0"
    + instruction_text
    + "\\0"
    + content_hash
)
```

- **`previous_layer_digest`** — Hex digest of the prior layer (empty string before the first layer).
- **`instruction_text`** — The canonical instruction line (e.g. full `COPY` line).
- **`content_hash`** — For `COPY`, a deterministic hash of the source paths/contents; for `FROM`, hash of the base tar if present; for `RUN`, empty string.

If `~/.docksmith/cache/<cache_key>` exists and points to an existing layer tar, the build prints **`CACHE HIT`** and reuses that layer (rootfs is restored from that snapshot). Otherwise **`CACHE MISS`** rebuilds.

This is **deterministic**: same inputs → same keys → same reuse behavior.

## Requirements

- **Python** 3.11+
- **Linux** for `docksmith run` and for `RUN` lines during build (`unshare`, `chroot`; typically requires **root** or appropriate capabilities).

On Windows you can still run **unit tests** and edit code; execution paths are Linux-oriented.

## Tests

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

## Security note

`chroot` and namespace isolation here are **not** a security boundary comparable to Docker with seccomp, cgroups, and user namespaces configured for untrusted workloads. Use only with trusted build contexts and images.

## License

Educational use; adapt as needed.
