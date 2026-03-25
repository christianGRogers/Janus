#!/bin/bash
# Start Janus server with LXD container queue enabled

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  Starting Janus Server with LXD Container Queue           ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo

# Step 1: Verify LXD is running
echo "📋 Step 1: Checking LXD..."
if ! command -v lxc &> /dev/null; then
    echo "❌ LXD CLI not found. Install with: snap install lxd"
    exit 1
fi

SOCKET="/var/snap/lxd/common/lxd/unix.socket"
if [ ! -S "$SOCKET" ]; then
    echo "❌ LXD socket not found at $SOCKET"
    echo "   Make sure LXD is running: sudo lxd"
    exit 1
fi
echo "✓ LXD is running"
echo

# Step 2: Verify image exists
echo "📋 Step 2: Checking LXD image..."
IMAGE_NAME="${LXD_IMAGE_NAME:-janus-compute-node}"

if ! lxc image info "$IMAGE_NAME" &>/dev/null; then
    echo "❌ Image '$IMAGE_NAME' not found"
    echo "   Create it with: bash setup-lxd-queue.sh"
    exit 1
fi
echo "✓ Image '$IMAGE_NAME' exists"
echo

# Step 3: Set environment variables
echo "📋 Step 3: Setting environment variables..."
export LXD_SOCKET="${SOCKET}"
export LXD_IMAGE_NAME="${LXD_IMAGE_NAME:-janus-compute-node}"
export CONTAINER_QUEUE_SIZE="${CONTAINER_QUEUE_SIZE:-5}"
export CONTAINER_PROVISION_DELAY="${CONTAINER_PROVISION_DELAY:-2}"
export CONTAINER_READY_TIMEOUT="${CONTAINER_READY_TIMEOUT:-60}"

echo "  LXD_SOCKET=$LXD_SOCKET"
echo "  LXD_IMAGE_NAME=$LXD_IMAGE_NAME"
echo "  CONTAINER_QUEUE_SIZE=$CONTAINER_QUEUE_SIZE"
echo "  CONTAINER_PROVISION_DELAY=$CONTAINER_PROVISION_DELAY"
echo "  CONTAINER_READY_TIMEOUT=$CONTAINER_READY_TIMEOUT"
echo

# Step 4: Start server
echo "📋 Step 4: Starting Janus server..."
echo "─────────────────────────────────────────────────────────────"
echo

cd "$(dirname "$0")"
uvicorn janus.server.app:app --host 0.0.0.0 --port 8000 --log-level debug
