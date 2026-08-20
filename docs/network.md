# Docksmith Networking Architecture

Docksmith implements a simplified container networking model using Linux bridges, `veth` (virtual ethernet) pairs, and `iptables` for NAT and port forwarding.

## Architecture

1. **Host-Side Bridge (`docksmith0`)**
   - The user runs `python main.py network setup` once to initialize the networking environment on the host.
   - This creates a Linux bridge named `docksmith0` and assigns it the subnet `172.30.0.1/24`.
   - It also enables IP forwarding (`net.ipv4.ip_forward=1`) and adds a `POSTROUTING MASQUERADE` iptables rule for `172.30.0.0/24` traffic exiting via the host's default interface.

2. **Per-Container Setup (`docksmith/network.py`)**
   - Before executing the container payload, Docksmith pre-provisions a persistent network namespace (`ds_<cid>`) using the `ip netns add` command.
   - A `veth` pair is created. The host end (`vethH_<cid>`) is attached to `docksmith0`. The container end (`vethC_<cid>`) is moved into the `ds_<cid>` namespace, renamed to `eth0`, and assigned a dynamic IP (e.g., `172.30.0.2`) from a simple JSON-backed allocator (`~/.docksmith/ip_pool.json`).
   - The default route inside the namespace is set to the bridge (`172.30.0.1`).
   
3. **Execution**
   - We utilize `nsenter --net=/var/run/netns/ds_<cid>` injected into the `unshare` command to ensure the container executes perfectly isolated inside the pre-configured namespace.
   
4. **Port Mapping (DNAT)**
   - The `-p <host_port>:<container_port>` flag adds a `PREROUTING DNAT` rule in `iptables` targeting the container's IP. 

5. **Cleanup**
   - On exit, the network namespace is deleted (which automatically tears down the veth pair).
   - Any DNAT rules associated with the container are cleanly removed.
   - The IP address is released back into the `ip_pool.json`.

---

## Manual Verification Sequence

You can run the following steps on a Linux system with root privileges to manually verify the network implementation.

**1. Initialize the Bridge**
```bash
sudo python3 main.py network setup
```

**2. Create a Test Image**
```bash
mkdir -p /tmp/docksmith_net && cd /tmp/docksmith_net
echo 'FROM scratch' > Docksmithfile
# Use a minimal base like alpine for real testing
sudo python3 /path/to/main.py build -t my_alpine .
```
*(Assuming you build an image `my_alpine` that has standard shell/network utils)*

**3. Test Inter-Container Connectivity**
Start a long-running container to act as the target:
```bash
sudo python3 main.py run my_alpine sleep 1000
```
Check its assigned IP (e.g., `172.30.0.2`). In another terminal, ping it from a second container:
```bash
sudo python3 main.py run my_alpine ping -c 3 172.30.0.2
```

**4. Test Internet Connectivity**
```bash
sudo python3 main.py run my_alpine ping -c 3 8.8.8.8
```

**5. Test Port Mapping**
Start a basic HTTP server inside the container mapped to port 8080:
```bash
sudo python3 main.py run -p 8080:8000 my_alpine python3 -m http.server 8000
```
In another terminal on the host:
```bash
curl localhost:8080
```
