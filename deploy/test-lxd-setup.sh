#!/bin/bash
# deploy/test-lxd-setup.sh
# Quick diagnostic script to verify LXD networking is working
# Run this to debug network issues before attempting image creation

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  LXD Network Diagnostic Tool                              ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo

# Check 1: Is LXD installed?
echo "✓ Check 1: LXD Installation"
if ! command -v lxc &>/dev/null; then
    echo "  ❌ LXD CLI not found"
    echo "  Install with: sudo snap install lxd"
    exit 1
fi
echo "  ✅ LXD CLI available"
echo

# Check 2: Are networks configured?
echo "✓ Check 2: LXD Networks"
if ! lxc network list &>/dev/null 2>&1; then
    echo "  ❌ Cannot list LXD networks"
    echo "  LXD daemon may not be running or not initialized"
    echo "  Initialize with: lxd init --auto"
    exit 1
fi

if ! lxc network list 2>/dev/null | grep -q lxdbr0; then
    echo "  ❌ Default bridge 'lxdbr0' not found"
    echo "  Creating bridge with: lxc network create lxdbr0 ipv4.address=10.40.96.1/24 ipv4.nat=true"
    lxc network create lxdbr0 ipv4.address=10.40.96.1/24 ipv4.nat=true || true
fi

echo "  ✅ Networks configured:"
lxc network list | grep -E "^\|" | tail -n +2 | sed 's/^/    /'
echo

# Check 3: Bridge is up and has IP
echo "✓ Check 3: Bridge Interface"
if ip addr show lxdbr0 &>/dev/null 2>&1; then
    IP=$(ip addr show lxdbr0 | grep "inet " | awk '{print $2}')
    echo "  ✅ Bridge is active with IP: $IP"
else
    echo "  ⚠️  Bridge interface not active - attempting recovery..."
    sudo ip link set lxdbr0 up 2>/dev/null || true
fi
echo

# Check 4: Test container
echo "✓ Check 4: Container Launch Test"
TEST_CONTAINER="lxd-diag-test-$$"

if lxc launch ubuntu:22.04 "$TEST_CONTAINER" -q 2>/dev/null; then
    echo "  ✅ Container launched: $TEST_CONTAINER"
    sleep 5
    
    # Check 5: Network from container
    echo "✓ Check 5: Container Network Access"
    
    if lxc exec "$TEST_CONTAINER" -- timeout 3 ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        echo "  ✅ Container can reach 8.8.8.8 (Google DNS)"
    else
        echo "  ❌ Container cannot reach 8.8.8.8"
    fi
    
    if lxc exec "$TEST_CONTAINER" -- timeout 3 curl -s -m 2 http://archive.ubuntu.com/ubuntu/dists/jammy/InRelease > /dev/null 2>&1; then
        echo "  ✅ Container can reach Ubuntu archive"
    else
        echo "  ❌ Container cannot reach Ubuntu archive"
    fi
    
    if lxc exec "$TEST_CONTAINER" -- apt-get update -qq 2>/dev/null; then
        echo "  ✅ Package manager works"
    else
        echo "  ⚠️  Package manager failed (network issue)"
    fi
    
    # Cleanup
    lxc delete "$TEST_CONTAINER" -f -q 2>/dev/null || true
    echo "  ✅ Test container cleaned up"
else
    echo "  ❌ Failed to launch test container"
fi
echo

# Summary
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  Diagnostic Complete                                       ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo

# If we got here and container worked, we're good
if [ -z "$TEST_CONTAINER" ] || lxc delete "$TEST_CONTAINER" -f -q &>/dev/null; then
    echo "✅ LXD networking appears to be working correctly!"
    echo ""
    echo "You can now run: bash deploy/setup-lxd-queue.sh"
    exit 0
else
    echo "⚠️  LXD networking has issues"
    echo ""
    echo "Recovery steps:"
    echo "1. Check LXD daemon: systemctl status snap.lxd.daemon"
    echo "2. Initialize LXD: lxd init --auto"
    echo "3. Verify bridge: ip addr show lxdbr0"
    echo "4. Restart daemon: sudo snap restart lxd"
    echo "5. Run this test again"
    exit 1
fi
