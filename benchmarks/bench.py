#!/usr/bin/env python3
"""
bench.py
Benchmarks Docksmith against Docker (and runc) for startup latency and memory overhead.
"""

import time
import subprocess
import statistics
import os
import sys
from pathlib import Path

def run_cmd(cmd):
    start = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
    end = time.time()
    return end - start, res

def measure_latency(engine="docksmith", iters=5):
    latencies = []
    
    # We use alpine as a common base
    # For docksmith, we assume a local image 'alpine_test' exists or we just use scratch
    if engine == "docksmith":
        cmd = [sys.executable, "main.py", "run", "scratch_test", "/bin/true"]
    else:
        cmd = ["docker", "run", "--rm", "alpine", "/bin/true"]
        
    print(f"Measuring {engine} startup latency ({iters} iterations)...")
    for i in range(iters):
        lat, res = run_cmd(cmd)
        if res.returncode != 0:
            print(f"Warning: {engine} failed: {res.stderr}")
            continue
        latencies.append(lat)
        
    if not latencies:
        return "N/A"
    return f"{statistics.mean(latencies)*1000:.2f} ms"

def measure_memory_overhead(engine="docksmith"):
    # Starts a sleep process and measures the memory of the runtime wrapper
    # For docksmith, we measure the memory of `python main.py run` process
    # For docker, we measure `docker run` client memory (daemon is separate, but client overhead is valid metric)
    
    if engine == "docksmith":
        cmd = [sys.executable, "main.py", "run", "scratch_test", "/bin/sleep", "10"]
    else:
        cmd = ["docker", "run", "--rm", "alpine", "sleep", "10"]
        
    print(f"Measuring {engine} memory overhead...")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2) # let it boot
    
    try:
        # Get RSS of the process
        res = subprocess.run(["ps", "-o", "rss=", "-p", str(proc.pid)], capture_output=True, text=True, check=True)
        rss_kb = int(res.stdout.strip())
        rss_mb = rss_kb / 1024
        result = f"{rss_mb:.2f} MB"
    except Exception as e:
        result = "N/A"
        
    proc.kill()
    proc.wait()
    return result

def main():
    if not sys.platform.startswith("linux"):
        print("Benchmarks must be run on Linux.")
        sys.exit(1)
        
    # Setup test image for docksmith
    print("Setting up docksmith test image...")
    # (Assuming we have a way to build scratch_test here, or just skipping setup for the sake of the script outline)
    
    results = []
    
    for engine in ["docksmith", "docker"]:
        try:
            if engine == "docker":
                subprocess.run(["docker", "--version"], check=True, capture_output=True)
        except Exception:
            print("Docker not installed, skipping docker benchmarks.")
            continue
            
        lat = measure_latency(engine)
        mem = measure_memory_overhead(engine)
        results.append(f"| {engine.capitalize():<15} | {lat:<20} | {mem:<20} |")
        
    md = "# Benchmark Results\\n\\n"
    md += "| Engine          | Avg Startup Latency  | Memory Overhead (Client) |\\n"
    md += "|-----------------|----------------------|--------------------------|\\n"
    md += "\\n".join(results) + "\\n"
    
    results_file = Path(__file__).parent / "results.md"
    results_file.write_text(md)
    print(f"\\nBenchmarks complete. Results written to {results_file.name}")
    print(md)

if __name__ == "__main__":
    main()
