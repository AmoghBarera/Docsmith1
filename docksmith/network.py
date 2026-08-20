import subprocess
import os
import sys
import json
import uuid
from pathlib import Path

from docksmith.utils import docksmith_home

BRIDGE_NAME = "docksmith0"
SUBNET_CIDR = "172.30.0.1/24"
SUBNET_PREFIX = "172.30.0"
IP_POOL_FILE = docksmith_home() / "ip_pool.json"

def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def setup_bridge() -> None:
    """
    Sets up the host-side bridge and NAT.
    """
    if os.geteuid() != 0:
        print("Network setup must be run as root.")
        sys.exit(1)

    print(f"Setting up bridge {BRIDGE_NAME}...")

    # Check if bridge exists
    res = run_cmd(["ip", "link", "show", BRIDGE_NAME], check=False)
    if res.returncode != 0:
        run_cmd(["ip", "link", "add", "name", BRIDGE_NAME, "type", "bridge"])
        run_cmd(["ip", "addr", "add", SUBNET_CIDR, "dev", BRIDGE_NAME])
        run_cmd(["ip", "link", "set", "dev", BRIDGE_NAME, "up"])
        print(f"Bridge {BRIDGE_NAME} created with {SUBNET_CIDR}")
    else:
        print(f"Bridge {BRIDGE_NAME} already exists.")

    # Enable IP forwarding
    fwd_path = Path("/proc/sys/net/ipv4/ip_forward")
    if fwd_path.read_text().strip() != "1":
        print("Enabling IPv4 forwarding...")
        try:
            fwd_path.write_text("1\n")
        except OSError as e:
            print(f"Warning: Could not enable IP forwarding automatically: {e}", file=sys.stderr)
            print("Please run: sysctl -w net.ipv4.ip_forward=1", file=sys.stderr)

    # Setup MASQUERADE
    print("Setting up NAT MASQUERADE...")
    # Check if rule exists
    check_nat = run_cmd(["iptables", "-t", "nat", "-C", "POSTROUTING", "-s", "172.30.0.0/24", "!", "-o", BRIDGE_NAME, "-j", "MASQUERADE"], check=False)
    if check_nat.returncode != 0:
        run_cmd(["iptables", "-t", "nat", "-A", "POSTROUTING", "-s", "172.30.0.0/24", "!", "-o", BRIDGE_NAME, "-j", "MASQUERADE"])
        print("NAT MASQUERADE rule added.")
    else:
        print("NAT MASQUERADE rule already exists.")
    
    print("Network setup complete.")


def allocate_ip(cid: str) -> str:
    """Allocates the next available IP for a container ID."""
    if not IP_POOL_FILE.exists():
        IP_POOL_FILE.write_text("{}")
    
    with open(IP_POOL_FILE, "r") as f:
        pool = json.load(f)
    
    if cid in pool:
        return pool[cid]
        
    used_ips = set(pool.values())
    
    for i in range(2, 255):
        ip = f"{SUBNET_PREFIX}.{i}"
        if ip not in used_ips:
            pool[cid] = ip
            with open(IP_POOL_FILE, "w") as f:
                json.dump(pool, f)
            return ip
            
    raise RuntimeError("No available IP addresses in the pool")


def release_ip(cid: str) -> None:
    """Releases an IP allocated to a container ID."""
    if not IP_POOL_FILE.exists():
        return
        
    with open(IP_POOL_FILE, "r") as f:
        pool = json.load(f)
        
    if cid in pool:
        del pool[cid]
        with open(IP_POOL_FILE, "w") as f:
            json.dump(pool, f)


def setup_container_network(cid: str, port_mappings: list[str] | None = None) -> tuple[str, str]:
    """
    Creates netns, veth pair, assigns IP, applies DNAT.
    Returns (netns_name, container_ip)
    """
    netns_name = f"ds_{cid}"
    veth_host = f"vh_{cid}"
    veth_cont = f"vc_{cid}"
    
    # Check if bridge exists first!
    res = run_cmd(["ip", "link", "show", BRIDGE_NAME], check=False)
    if res.returncode != 0:
        raise RuntimeError(f"Bridge {BRIDGE_NAME} does not exist. Run 'docksmith network setup' first.")
        
    ip = allocate_ip(cid)
    
    try:
        run_cmd(["ip", "netns", "add", netns_name])
        run_cmd(["ip", "link", "add", veth_host, "type", "veth", "peer", "name", veth_cont])
        run_cmd(["ip", "link", "set", veth_host, "master", BRIDGE_NAME])
        run_cmd(["ip", "link", "set", veth_host, "up"])
        
        run_cmd(["ip", "link", "set", veth_cont, "netns", netns_name])
        run_cmd(["ip", "netns", "exec", netns_name, "ip", "link", "set", "dev", veth_cont, "name", "eth0"])
        run_cmd(["ip", "netns", "exec", netns_name, "ip", "addr", "add", f"{ip}/24", "dev", "eth0"])
        run_cmd(["ip", "netns", "exec", netns_name, "ip", "link", "set", "eth0", "up"])
        run_cmd(["ip", "netns", "exec", netns_name, "ip", "link", "set", "lo", "up"])
        
        # Add default route
        run_cmd(["ip", "netns", "exec", netns_name, "ip", "route", "add", "default", "via", "172.30.0.1"])
        
        # Apply port mappings
        if port_mappings:
            for mapping in port_mappings:
                host_port, cont_port = mapping.split(":")
                run_cmd([
                    "iptables", "-t", "nat", "-A", "PREROUTING", 
                    "-p", "tcp", "--dport", host_port, 
                    "-j", "DNAT", "--to-destination", f"{ip}:{cont_port}"
                ])
                # We might also need to allow routing for this traffic on the bridge if iptables FORWARD defaults to DROP
                # For simplicity, docksmith assumes FORWARD allows docker/bridge traffic.
                
        return netns_name, ip
        
    except Exception as e:
        # Partial failure cleanup
        teardown_container_network(cid, ip, port_mappings)
        raise RuntimeError(f"Network setup failed: {e}")


def teardown_container_network(cid: str, ip: str, port_mappings: list[str] | None = None) -> None:
    """Destroys netns, removes DNAT, releases IP."""
    netns_name = f"ds_{cid}"
    
    if port_mappings:
        for mapping in port_mappings:
            try:
                host_port, cont_port = mapping.split(":")
                run_cmd([
                    "iptables", "-t", "nat", "-D", "PREROUTING", 
                    "-p", "tcp", "--dport", host_port, 
                    "-j", "DNAT", "--to-destination", f"{ip}:{cont_port}"
                ], check=False)
            except Exception:
                pass
                
    run_cmd(["ip", "netns", "delete", netns_name], check=False)
    
    release_ip(cid)
