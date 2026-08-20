#!/usr/bin/env bash
#
# demo_script.sh
# A quick, copy-pasteable demonstration of Docksmith's core features.
# This script sets up a basic container, explores stats and execs, and tears it down.
#
# Requires: A valid `ubuntu_latest.tar` or similar in ~/.docksmith/bases/

set -e

echo "=== 1. Building a simple web server image ==="
mkdir -p demo_workspace
cd demo_workspace

cat << 'EOF' > Docksmithfile
FROM ubuntu_latest
RUN apt-get update && apt-get install -y python3
CMD ["python3", "-m", "http.server", "80"]
EOF

echo "Building..."
docksmith build -t demo_web .
cd ..

echo -e "\n=== 2. Starting container with resource limits and port forwarding ==="
# We start it in the background to continue our demo.
docksmith run -p 8080:80 --memory 512m --cpus 0.5 demo_web &
SERVER_PID=$!
sleep 2 # Let the container boot and write state

echo -e "\n=== 3. Checking live container stats (Cgroups & Net I/O) ==="
docksmith stats

echo -e "\n=== 4. Testing network port forwarding ==="
echo "Curling localhost:8080..."
curl -s http://localhost:8080 | head -n 5

echo -e "\n=== 5. Exec-ing into the isolated environment ==="
# We assume this is the only container running for this demo
CID=$(docksmith stats | tail -n 1 | awk '{print $1}')
echo "Running 'ps aux' inside container $CID..."
docksmith exec $CID ps aux

echo -e "\n=== 6. Tearing down ==="
kill $SERVER_PID
wait $SERVER_PID 2>/dev/null || true
echo "Demo complete."
