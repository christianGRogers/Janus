#!/bin/bash
# Setup script for Janus LXD Container Queue
# Usage: bash setup-lxd-queue.sh

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  Janus LXD Container Queue Setup                           ║"
echo "╚════════════════════════════════════════════════════════════╝"

# Check LXD is installed
if ! command -v lxc &> /dev/null; then
    echo "❌ LXD is not installed. Install with:"
    echo "   sudo snap install lxd"
    exit 1
fi

echo "✓ LXD detected: $(lxc --version)"

# Check socket
SOCKET="/var/snap/lxd/common/lxd/unix.socket"
if [ ! -S "$SOCKET" ]; then
    echo "❌ LXD socket not found at $SOCKET"
    exit 1
fi
echo "✓ LXD socket ready"

# Step 1: Create base image
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "Step 1: Creating base image 'from-instance-flying-oarfish'..."
echo "═══════════════════════════════════════════════════════════════"

TEMP_CONTAINER="janus-setup-temp"

# Clean up any previous failed attempts
lxc delete "$TEMP_CONTAINER" --force 2>/dev/null || true

# Launch a base container
echo "Launching temporary container..."
lxc launch ubuntu:22.04 "$TEMP_CONTAINER" --quiet

# Wait for network
echo "Waiting for container network..."
sleep 5

# Update packages
echo "Installing dependencies..."
lxc exec "$TEMP_CONTAINER" -- apt-get update > /dev/null 2>&1
lxc exec "$TEMP_CONTAINER" -- apt-get upgrade -y > /dev/null 2>&1
lxc exec "$TEMP_CONTAINER" -- apt-get install -y \
    python3 \
    python3-pip \
    build-essential \
    curl \
    wget \
    git \
    > /dev/null 2>&1

echo "Creating Python venv at /opt/janus-env..."
lxc exec "$TEMP_CONTAINER" -- python3 -m venv /opt/janus-env > /dev/null 2>&1

echo "Installing Python dependencies in venv..."
lxc exec "$TEMP_CONTAINER" -- /opt/janus-env/bin/pip install --upgrade pip setuptools wheel > /dev/null 2>&1
lxc exec "$TEMP_CONTAINER" -- /opt/janus-env/bin/pip install \
    tensorflow \
    numpy \
    scikit-learn \
    pandas \
    requests \
    h5py \
    > /dev/null 2>&1

# Optional: Install PyTorch if needed (uncomment to enable)
# echo "Installing PyTorch (CPU)..."
# lxc exec "$TEMP_CONTAINER" -- /opt/janus-env/bin/pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu > /dev/null 2>&1

# Publish image
echo "Publishing image..."
lxc stop "$TEMP_CONTAINER" --quiet
lxc publish "$TEMP_CONTAINER" --alias from-instance-flying-oarfish --quiet
lxc delete "$TEMP_CONTAINER" --quiet

echo "✓ Image 'from-instance-flying-oarfish' created successfully"
echo ""
lxc image info from-instance-flying-oarfish | grep -E "Aliases|Size|Created"

# Step 2: Test container provisioning
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "Step 2: Testing container provisioning..."
echo "═══════════════════════════════════════════════════════════════"

TEST_CONTAINER="janus-test-node"
lxc delete "$TEST_CONTAINER" --force 2>/dev/null || true

echo "Launching test container..."
lxc launch from-instance-flying-oarfish "$TEST_CONTAINER" --quiet

echo "Waiting for boot..."
sleep 5

echo "Testing Python from venv..."
if lxc exec "$TEST_CONTAINER" -- /opt/janus-env/bin/python3 -c "import tensorflow; print(f'TensorFlow {tensorflow.__version__}')" 2>/dev/null; then
    echo "✓ TensorFlow working in venv"
else
    echo "⚠ Warning: TensorFlow not working in venv"
fi

echo "Cleaning up test container..."
lxc delete "$TEST_CONTAINER" --force --quiet

# Step 3: Configuration
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "Step 3: Configuration"
echo "═══════════════════════════════════════════════════════════════"

echo ""
echo "Add these to your Janus .env file or export them:"
echo ""
cat << 'EOF'
# LXD Container Queue Configuration
export LXD_SOCKET="/var/snap/lxd/common/lxd/unix.socket"
export LXD_IMAGE_FINGERPRINT="b03058e361bf"
export LXD_PROFILE="default"
export LXD_CONTAINER_PREFIX="janus-node"

# Resource Limits (adjust to your hardware)
export LXD_CPU_LIMIT="2"
export LXD_MEMORY_LIMIT="2048"
export LXD_DISK_LIMIT="20"

# Queue Behavior
export CONTAINER_QUEUE_SIZE="5"           # Number of pre-provisioned containers
export CONTAINER_PROVISION_DELAY="2"      # Seconds between spawning
export CONTAINER_READY_TIMEOUT="60"       # Max wait for container ready
EOF

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "Step 4: Starting Janus"
echo "═══════════════════════════════════════════════════════════════"

echo ""
echo "From your Janus repository directory, run:"
echo ""
echo "  export LXD_SOCKET=\"/var/snap/lxd/common/lxd/unix.socket\""
echo "  export LXD_IMAGE_FINGERPRINT=\"b03058e361bf\""
echo "  export CONTAINER_QUEUE_SIZE=\"5\""
echo "  uvicorn janus.server.app:app --reload"
echo ""

echo "═══════════════════════════════════════════════════════════════"
echo "Step 5: Verification"
echo "═══════════════════════════════════════════════════════════════"

echo ""
echo "Once Janus is running, verify the queue in another terminal:"
echo ""
echo "  # Get JWT token first (log in)"
echo "  TOKEN=\$(curl -X POST http://localhost:8000/auth/login \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"email\": \"user@example.com\", \"password\": \"...\"}'  \\"
echo "    | jq -r .token)"
echo ""
echo "  # Check queue status"
echo "  curl -H \"Authorization: Bearer \$TOKEN\" \\"
echo "    http://localhost:8000/queue-status | jq ."
echo ""

echo "═══════════════════════════════════════════════════════════════"
echo "Setup Complete! ✓"
echo "═══════════════════════════════════════════════════════════════"
echo ""
#!/bin/bash
# Deprecated: detailed setup moved to deploy/ and then removed.
echo "Notice: setup-lxd-queue.sh is deprecated. Create the 'from-instance-flying-oarfish' LXD image manually if needed."
echo "Manual example:
  lxc launch ubuntu:22.04 janus-setup-temp
  lxc exec janus-setup-temp -- apt-get update && apt-get install -y python3 python3-pip
  lxc stop janus-setup-temp
  lxc publish janus-setup-temp --alias from-instance-flying-oarfish
  lxc delete janus-setup-temp -f"
exit 0
echo "  Containers: $(lxc list -c n --format csv | wc -l)"
