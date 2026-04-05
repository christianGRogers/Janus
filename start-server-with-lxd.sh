#!/bin/bash
# Start Janus server with LXD container queue enabled
# 
# ASSUMES: The LXD image with fingerprint b03058e361bf has a Python venv pre-installed
# at /opt/janus-env with all dependencies (TensorFlow, NumPy, etc.).
#
# The venv is automatically activated by lxd_manager.py when executing
# inference commands in containers.

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

# Step 2: Verify image exists (by fingerprint)
echo "📋 Step 2: Checking LXD image..."
IMAGE_FINGERPRINT="b03058e361bf"

if ! lxc image info "$IMAGE_FINGERPRINT" &>/dev/null; then
    echo "❌ Image with fingerprint '$IMAGE_FINGERPRINT' not found"
    echo "   Create the LXD image manually (see deploy/test-lxd-setup.sh for guidance)."
    exit 1
fi
echo "✓ Image with fingerprint '$IMAGE_FINGERPRINT' exists"
echo

# Step 3: Set environment variables
echo "📋 Step 3: Setting environment variables..."
export LXD_SOCKET="${SOCKET}"
export LXD_IMAGE_FINGERPRINT="${LXD_IMAGE_FINGERPRINT:-b03058e361bf}"
export CONTAINER_QUEUE_SIZE="${CONTAINER_QUEUE_SIZE:-5}"
export CONTAINER_PROVISION_DELAY="${CONTAINER_PROVISION_DELAY:-2}"
export CONTAINER_READY_TIMEOUT="${CONTAINER_READY_TIMEOUT:-60}"

echo "  LXD_SOCKET=$LXD_SOCKET"
echo "  LXD_IMAGE_FINGERPRINT=$LXD_IMAGE_FINGERPRINT"
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
