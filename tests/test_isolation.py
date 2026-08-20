"""Isolation tests for pivot_root."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from docksmith.utils import chroot_run, is_linux


def is_root() -> bool:
    return os.geteuid() == 0 if hasattr(os, "geteuid") else False


@pytest.mark.skipif(not is_linux(), reason="Requires Linux")
@pytest.mark.skipif(not is_root(), reason="Requires root privileges for unshare")
@pytest.mark.skipif(shutil.which("gcc") is None, reason="Requires gcc for static compilation")
def test_pivot_root_isolation(tmp_path: Path) -> None:
    # 1. Create a host secret
    host_secret = tmp_path / "host_secret.txt"
    host_secret.write_text("top secret")

    # 2. Create the rootfs
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()

    # 3. Create a static C program to check isolation
    c_source = tmp_path / "check.c"
    c_source.write_text(f"""
#include <stdio.h>
#include <unistd.h>
#include <sys/stat.h>

int main() {{
    // Check (a): Cannot see host files outside rootfs
    // We try to stat the host secret using its absolute path on the host
    struct stat st;
    if (stat("{host_secret.resolve()}", &st) == 0) {{
        fprintf(stderr, "SECURITY FAILURE: Can see host secret at {host_secret.resolve()}\\n");
        return 101;
    }}

    // Check (b): /proc is mounted and functional
    if (stat("/proc/self", &st) != 0) {{
        fprintf(stderr, "FAILURE: /proc/self does not exist\\n");
        return 102;
    }}
    
    // Check (c): /dev and /sys are mounted
    if (stat("/dev/null", &st) != 0) {{
        fprintf(stderr, "FAILURE: /dev/null does not exist\\n");
        return 103;
    }}
    if (stat("/sys", &st) != 0) {{
        fprintf(stderr, "FAILURE: /sys does not exist\\n");
        return 104;
    }}

    return 0; // Success!
}}
""")

    bin_path = rootfs / "check_isolation"
    compile_cmd = ["gcc", "-static", "-O2", str(c_source), "-o", str(bin_path)]
    result = subprocess.run(compile_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"Failed to statically compile test binary:\\n{result.stderr}")

    # 4. Run the static binary inside the isolated environment
    # Since it's statically linked, it doesn't need /lib or /bin/sh.
    proc = chroot_run(
        rootfs, 
        ["/check_isolation"], 
        check=False, 
        inject_dns=False
    )

    if proc.returncode == 101:
        pytest.fail("Isolation failed: Host filesystem is visible inside the container.")
    elif proc.returncode == 102:
        pytest.fail("Mount failed: /proc is not properly mounted in the new rootfs.")
    elif proc.returncode == 103:
        pytest.fail("Mount failed: /dev is not properly mounted.")
    elif proc.returncode == 104:
        pytest.fail("Mount failed: /sys is not properly mounted.")
    elif proc.returncode != 0:
        pytest.fail(f"Container command failed with exit code {proc.returncode}")
