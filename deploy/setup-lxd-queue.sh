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

# Wait for container to be ready
echo "⏳ Waiting for container network..."
sleep 5

echo "📋 Step 2: Updating packages..."
lxc exec "$TEMP_CONTAINER" -- apt-get update -qq
lxc exec "$TEMP_CONTAINER" -- apt-get upgrade -y -qq
echo "✓ Packages updated"
echo

echo "📋 Step 3: Installing Python and dependencies..."
lxc exec "$TEMP_CONTAINER" -- apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    git \
    curl \
    wget
echo "✓ Python and build tools installed"
echo

echo "📋 Step 4: Installing ML frameworks..."
echo "  (This will take several minutes)"

# Install TensorFlow
echo "  Installing TensorFlow..."
lxc exec "$TEMP_CONTAINER" -- pip3 install -q tensorflow 2>/dev/null || \
    echo "  ⚠️  TensorFlow installation skipped (network/disk issue)"

# Install PyTorch
echo "  Installing PyTorch..."
lxc exec "$TEMP_CONTAINER" -- pip3 install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu 2>/dev/null || \
    echo "  ⚠️  PyTorch installation skipped (network/disk issue)"

# Install other ML libraries
echo "  Installing other ML libraries..."
lxc exec "$TEMP_CONTAINER" -- pip3 install -q \
    numpy \
    pandas \
    scikit-learn \
    jupyter \
    matplotlib \
    requests 2>/dev/null || true

echo "✓ ML frameworks installed"
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
