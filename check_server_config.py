#!/usr/bin/env python3
"""
Check Janus server LXD configuration and diagnose container queue issues.
"""

import os
import sys
import subprocess

print("╔════════════════════════════════════════════════════════════╗")
print("║  Janus Server LXD Configuration Check                     ║")
print("╚════════════════════════════════════════════════════════════╝")
print()

# 1. Check environment variables
print("📋 Environment Variables:")
print("─" * 60)
env_vars = [
    "LXD_SOCKET",
    "LXD_CLUSTER_ENDPOINT",
    "LXD_IMAGE_NAME",
    "CONTAINER_QUEUE_SIZE",
    "CONTAINER_PROVISION_DELAY",
    "CONTAINER_READY_TIMEOUT",
]

for var in env_vars:
    value = os.environ.get(var)
    status = "✓" if value else "✗"
    print(f"{status} {var:30} = {value or '(not set)'}")
print()

# 2. Check LXD socket
print("🔌 LXD Socket:")
print("─" * 60)
socket_path = os.environ.get("LXD_SOCKET", "/var/snap/lxd/common/lxd/unix.socket")
socket_exists = os.path.exists(socket_path)
print(f"{'✓' if socket_exists else '✗'} {socket_path}")
if not socket_exists:
    print("  ⚠️  LXD socket not found. Make sure LXD is running.")
print()

# 3. Check LXD CLI
print("🛠️  LXD CLI:")
print("─" * 60)
try:
    result = subprocess.run(["lxc", "version"], capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        print("✓ LXD CLI is available")
        print(f"  {result.stdout.strip()}")
    else:
        print("✗ LXD CLI error:")
        print(f"  {result.stderr.strip()}")
except FileNotFoundError:
    print("✗ LXD CLI not found in PATH")
except Exception as e:
    print(f"✗ Error checking LXD CLI: {e}")
print()

# 4. Check LXD image
print("🖼️  LXD Images:")
print("─" * 60)
try:
    result = subprocess.run(["lxc", "image", "list"], capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        image_name = os.environ.get("LXD_IMAGE_NAME", "janus-compute-node")
        lines = result.stdout.strip().split('\n')
        
        # Find image in output
        found = False
        for line in lines:
            if image_name in line:
                print(f"✓ Image '{image_name}' found:")
                print(f"  {line}")
                found = True
                break
        
        if not found:
            print(f"✗ Image '{image_name}' not found")
            print("  Available images:")
            for line in lines[3:]:  # Skip header lines
                if line.strip() and '|' in line:
                    print(f"    {line}")
    else:
        print("✗ Error listing images:")
        print(f"  {result.stderr.strip()}")
except Exception as e:
    print(f"✗ Error checking images: {e}")
print()

# 5. Check containers
print("🐳 LXD Containers:")
print("─" * 60)
try:
    result = subprocess.run(["lxc", "list"], capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        lines = result.stdout.strip().split('\n')
        
        # Count containers
        janus_containers = 0
        for line in lines[3:]:  # Skip header
            if line.strip() and 'janus' in line.lower():
                janus_containers += 1
                print(f"  {line}")
        
        if janus_containers == 0:
            print("  ⚠️  No Janus containers running")
        else:
            print(f"  ✓ {janus_containers} Janus container(s) found")
    else:
        print("✗ Error listing containers:")
        print(f"  {result.stderr.strip()}")
except Exception as e:
    print(f"✗ Error checking containers: {e}")
print()

# 6. Configuration recommendations
print("💡 Configuration Recommendations:")
print("─" * 60)

missing = []
if not os.environ.get("LXD_SOCKET") and not os.environ.get("LXD_CLUSTER_ENDPOINT"):
    missing.append("LXD_SOCKET or LXD_CLUSTER_ENDPOINT")
if not os.environ.get("LXD_IMAGE_NAME"):
    missing.append("LXD_IMAGE_NAME")

if missing:
    print("⚠️  Missing environment variables:")
    for var in missing:
        print(f"   - {var}")
    print()
    print("Set these variables before starting the server:")
    print("   export LXD_SOCKET=/var/snap/lxd/common/lxd/unix.socket")
    print("   export LXD_IMAGE_NAME=janus-compute-node")
    print("   export CONTAINER_QUEUE_SIZE=5")
    print()
else:
    print("✓ All required environment variables are set")

if not socket_exists:
    print()
    print("⚠️  LXD socket not found:")
    print("   1. Make sure LXD is installed: snap install lxd")
    print("   2. Initialize LXD: lxd init")
    print("   3. Check socket exists: ls -la /var/snap/lxd/common/lxd/unix.socket")

print()
print("╔════════════════════════════════════════════════════════════╗")
print("║  End of Configuration Check                                ║")
print("╚════════════════════════════════════════════════════════════╝")
