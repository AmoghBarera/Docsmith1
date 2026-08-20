"""Integration tests for docksmith CLI and containers."""

import os
import sys
import time
import subprocess
import pytest
import tempfile
import shutil
from pathlib import Path
from docksmith.utils import is_linux

def is_root() -> bool:
    return os.geteuid() == 0 if hasattr(os, "geteuid") else False

@pytest.fixture(scope="module")
def docksmith_bin():
    return [sys.executable, str(Path(__file__).parent.parent / "main.py")]

@pytest.fixture(scope="module")
def test_image(docksmith_bin):
    """Creates a basic image using a statically compiled C binary."""
    with tempfile.TemporaryDirectory() as td:
        ctx = Path(td)
        
        c_src = ctx / "hello.c"
        c_src.write_text("""
#include <stdio.h>
int main() {
    printf("HELLO_DOCKSMITH\\n");
    return 0;
}
""")
        subprocess.run(["gcc", "-static", "-O2", str(c_src), "-o", str(ctx / "hello")], check=True)
        
        c_looper = ctx / "looper.c"
        c_looper.write_text("""
#include <stdio.h>
#include <unistd.h>
int main() {
    while(1) {
        printf("loop\\n");
        fflush(stdout);
        sleep(1);
    }
    return 0;
}
""")
        subprocess.run(["gcc", "-static", "-O2", str(c_looper), "-o", str(ctx / "looper")], check=True)
        
        df = ctx / "Docksmithfile"
        df.write_text("""
FROM scratch
COPY hello /hello
COPY looper /looper
CMD ["/hello"]
""")
        
        # We need a scratch base tar
        base_tar = ctx / "scratch.tar"
        rootfs = ctx / "rootfs"
        rootfs.mkdir()
        subprocess.run(["tar", "-cf", str(base_tar), "-C", str(rootfs), "."], check=True)
        bases_dir = Path.home() / ".docksmith" / "bases"
        bases_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_tar, bases_dir / "scratch.tar")
        
        subprocess.run(docksmith_bin + ["build", "-t", "integration_test", str(ctx)], check=True)
        yield "integration_test"

@pytest.mark.skipif(not is_linux(), reason="Requires Linux")
@pytest.mark.skipif(not is_root(), reason="Requires root")
@pytest.mark.skipif(shutil.which("gcc") is None, reason="Requires gcc")
def test_container_run(docksmith_bin, test_image):
    """Test basic container execution."""
    res = subprocess.run(docksmith_bin + ["run", test_image], capture_output=True, text=True)
    assert res.returncode == 0
    assert "HELLO_DOCKSMITH" in res.stdout

@pytest.mark.skipif(not is_linux(), reason="Requires Linux")
@pytest.mark.skipif(not is_root(), reason="Requires root")
@pytest.mark.skipif(shutil.which("gcc") is None, reason="Requires gcc")
def test_container_memory_limit(docksmith_bin, test_image):
    """Test setting cgroup memory limit."""
    res = subprocess.run(docksmith_bin + ["run", "--memory", "10m", test_image], capture_output=True, text=True)
    assert res.returncode == 0
    assert "Memory=10m" in res.stdout

@pytest.mark.skipif(not is_linux(), reason="Requires Linux")
@pytest.mark.skipif(not is_root(), reason="Requires root")
@pytest.mark.skipif(shutil.which("gcc") is None, reason="Requires gcc")
def test_subcommands(docksmith_bin, test_image):
    """Test exec, logs, and stats subcommands."""
    # Start container in background
    proc = subprocess.Popen(docksmith_bin + ["run", test_image, "/looper"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2) # wait for boot
    
    try:
        # Check stats to get CID
        res = subprocess.run(docksmith_bin + ["stats"], capture_output=True, text=True)
        lines = res.stdout.strip().splitlines()
        assert len(lines) >= 2, "No running container found in stats"
        
        cid = lines[1].split()[0]
        
        # Test logs
        res = subprocess.run(docksmith_bin + ["logs", cid], capture_output=True, text=True)
        assert "loop" in res.stdout
        
        # Test exec
        res = subprocess.run(docksmith_bin + ["exec", cid, "/hello"], capture_output=True, text=True)
        assert "HELLO_DOCKSMITH" in res.stdout
        
    finally:
        proc.kill()
        proc.wait()
