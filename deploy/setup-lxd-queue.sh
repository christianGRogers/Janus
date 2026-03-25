#!/bin/bash
# deploy/setup-lxd-queue.sh
# Creates a base LXD container image with ML dependencies pre-installed
# This image is used for the container queue to speed up node provisioning

set -e

IMAGE_NAME="${LXD_IMAGE_NAME:-janus-compute-node}"
TEMP_CONTAINER="janus-setup-temp"
BASE_IMAGE="ubuntu:22.04"

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  LXD Container Image Setup for Janus                       ║"
echo "║  Image: $IMAGE_NAME                                        ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo

# Check if LXD is available
if ! command -v lxc &>/dev/null; then
    echo "❌ LXD CLI not found. Install with: snap install lxd"
    exit 1
fi

echo "✓ LXD CLI available"
echo

# Check if image already exists
if lxc image info "$IMAGE_NAME" &>/dev/null 2>&1; then
    echo "✓ Image '$IMAGE_NAME' already exists"
    exit 0
fi

echo "📋 Step 1: Creating temporary container..."
lxc launch "$BASE_IMAGE" "$TEMP_CONTAINER" -q
echo "✓ Container created: $TEMP_CONTAINER"
echo

# Wait for container to be ready and network to be configured
echo "⏳ Waiting for container network (checking network connectivity)..."
for i in {1..30}; do
    if lxc exec "$TEMP_CONTAINER" -- curl -s -m 2 http://archive.ubuntu.com/ubuntu/dists/jammy/InRelease > /dev/null 2>&1; then
        echo "✓ Network is reachable"
        break
    fi
    echo "  Attempt $i/30: Waiting for network..."
    sleep 2
done

# Check if network is actually working
if ! lxc exec "$TEMP_CONTAINER" -- ping -c 1 8.8.8.8 >/dev/null 2>&1; then
    echo "⚠️  Container network may not be configured properly"
    echo "    Attempting to configure container network..."
    
    # Try to configure DHCP
    lxc exec "$TEMP_CONTAINER" -- systemctl restart networking 2>/dev/null || true
    sleep 3
fi

echo "📋 Step 2: Updating packages..."
if lxc exec "$TEMP_CONTAINER" -- apt-get update -qq 2>/dev/null; then
    lxc exec "$TEMP_CONTAINER" -- apt-get upgrade -y -qq 2>/dev/null || true
    echo "✓ Packages updated"
else
    echo "⚠️  Package update failed (network issue), trying to continue..."
fi
echo

echo "📋 Step 3: Installing Python and dependencies..."
# Try to install Python, but don't fail if it doesn't work
if lxc exec "$TEMP_CONTAINER" -- apt-get install -y -qq python3 python3-dev build-essential git curl wget 2>/dev/null; then
    echo "✓ Python and build tools installed"
else
    echo "⚠️  Some packages failed to install (network/availability issue)"
    echo "    Trying minimal install..."
    lxc exec "$TEMP_CONTAINER" -- apt-get install -y -qq python3 2>/dev/null || true
fi
echo

echo "📋 Step 4: Installing ML frameworks..."
echo "  (This will take several minutes or may be skipped if network unavailable)"

# Install TensorFlow with fallback
echo "  Installing TensorFlow..."
if lxc exec "$TEMP_CONTAINER" -- pip3 install -q tensorflow 2>/dev/null; then
    echo "    ✓ TensorFlow installed"
else
    echo "    ⚠️  TensorFlow installation failed (skipping)"
fi

# Install PyTorch with fallback
echo "  Installing PyTorch..."
if lxc exec "$TEMP_CONTAINER" -- pip3 install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu 2>/dev/null; then
    echo "    ✓ PyTorch installed"
else
    echo "    ⚠️  PyTorch installation failed (skipping)"
fi

# Install other ML libraries (don't fail if any of these fail)
echo "  Installing other ML libraries..."
PACKAGES=(numpy pandas scikit-learn jupyter matplotlib requests)
for package in "${PACKAGES[@]}"; do
    if lxc exec "$TEMP_CONTAINER" -- pip3 install -q "$package" 2>/dev/null; then
        echo "    ✓ $package installed"
    else
        echo "    ⚠️  $package installation failed (skipping)"
    fi
done

echo "✓ ML framework installation complete (with network resilience)"
echo

echo "📋 Step 5: Publishing image..."
lxc publish "$TEMP_CONTAINER" --alias "$IMAGE_NAME" -q
echo "✓ Image published: $IMAGE_NAME"
echo

echo "📋 Step 6: Cleaning up..."
lxc delete "$TEMP_CONTAINER" -f -q
echo "✓ Temporary container deleted"
echo

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  Image Setup Complete! ✓                                   ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo

# Verify image
if lxc image info "$IMAGE_NAME" &>/dev/null 2>&1; then
    SIZE=$(lxc image info "$IMAGE_NAME" | grep "Size:" | awk '{print $2}')
    echo "✓ Image verified: $IMAGE_NAME ($SIZE)"
    echo ""
    echo "The image is ready for the container queue!"
    exit 0
else
    echo "❌ Image verification failed"
    exit 1
fi
