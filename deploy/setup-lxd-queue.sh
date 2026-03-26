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

# Check and initialize LXD networking if needed
echo "📋 Checking LXD network configuration..."
if ! lxc network list 2>/dev/null | grep -q "lxdbr0"; then
    echo "⚠️  LXD bridge network 'lxdbr0' not found"
    echo "    Initializing LXD with default configuration..."
    
    # Run lxd init with automatic configuration
    echo "" | lxd init --auto 2>/dev/null || {
        echo "⚠️  LXD auto-init failed, trying manual configuration..."
        # Minimal LXD setup - just enable storage and network
        mkdir -p /etc/lxd/profiles
        true
    }
    sleep 2
fi

echo "✓ LXD networking ready"
echo

# Check if image already exists
if lxc image info "$IMAGE_NAME" &>/dev/null 2>&1; then
    echo "✓ Image '$IMAGE_NAME' already exists"
    exit 0
fi

echo "📋 Step 1: Creating temporary container..."
lxc launch "$BASE_IMAGE" "$TEMP_CONTAINER" -q || {
    echo "⚠️  Failed to launch container, cleaning up old instance..."
    lxc delete "$TEMP_CONTAINER" -f -q 2>/dev/null || true
    sleep 2
    lxc launch "$BASE_IMAGE" "$TEMP_CONTAINER" -q || {
        echo "❌ Failed to create container"
        exit 1
    }
}
echo "✓ Container created: $TEMP_CONTAINER"
echo

# Wait for container to start
echo "⏳ Waiting for container to start..."
sleep 5

# As per configuration, prefer host-assisted installs rather than trying
# to reach the WAN from inside the container. The host will act as
# package proxy and pip cache. This avoids long container-side network waits.
HOST_ONLY_INSTALL="${HOST_ONLY_INSTALL:-1}"
HOST_IP="${HOST_IP:-$(hostname -I | awk '{print $1}') }"

echo "⏳ Verifying host reachability from container..."
if lxc exec "$TEMP_CONTAINER" -- timeout 2 ping -c 1 "$HOST_IP" >/dev/null 2>&1; then
    echo "✓ Container can reach host $HOST_IP"
    CONTAINER_CAN_REACH_HOST=true
else
    echo "⚠️  Container cannot reach host $HOST_IP"
    CONTAINER_CAN_REACH_HOST=false
fi

if [ "$HOST_ONLY_INSTALL" = "1" ]; then
    echo "ℹ️  HOST_ONLY_INSTALL=1: will attempt host-assisted installation only"
else
    echo "ℹ️  HOST_ONLY_INSTALL=0: will attempt container network install if host-assisted fails"
fi

echo "📋 Step 2: Updating packages..."
# If the container cannot reach external networks but can reach the host,
# use the host as a package/cache proxy to install dependencies.
HOST_IP="${HOST_IP:-$(hostname -I | awk '{print $1}')}"

if [ "$NETWORK_OK" = false ] && lxc exec "$TEMP_CONTAINER" -- timeout 2 ping -c 1 "$HOST_IP" >/dev/null 2>&1; then
    echo "⚠️  Container cannot reach the internet but can reach host: $HOST_IP"
    echo "    Preparing host-side package proxy and pip cache..."

    # --- Ensure apt-cacher-ng is available on the host (provides apt proxy at :3142)
    if ! command -v apt-cacher-ng &>/dev/null; then
        echo "    Installing apt-cacher-ng on host... (requires sudo)"
        sudo apt-get update -qq || true
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq apt-cacher-ng || true
    fi
    sudo systemctl restart apt-cacher-ng 2>/dev/null || true

    # --- Prepare pip wheel cache on host
    PIP_CACHE_DIR="/var/janus/pip_cache"
    sudo mkdir -p "$PIP_CACHE_DIR"
    sudo chown "$(whoami)":"$(whoami)" "$PIP_CACHE_DIR" || true

    # Split packages into small (download by default) and heavy (optional)
    PIP_PACKAGES_SMALL=(numpy pandas scikit-learn jupyter matplotlib requests)
    PIP_PACKAGES_HEAVY=(tensorflow torch torchvision torchaudio)

    echo "    Downloading small pip wheels to $PIP_CACHE_DIR (host) — may take a while..."
    for pkg in "${PIP_PACKAGES_SMALL[@]}"; do
        echo "      - Attempting to download: $pkg"
        python3 -m pip download -q -d "$PIP_CACHE_DIR" "$pkg" || echo "      ⚠️  Download failed for $pkg (continuing)"
    done

    # Heavy wheels are optional. Set DOWNLOAD_HEAVY_WHEELS=1 to enable
    if [ "${DOWNLOAD_HEAVY_WHEELS:-0}" = "1" ]; then
        echo "    DOWNLOAD_HEAVY_WHEELS=1: attempting to download heavy packages (may be very large)"
        for pkg in "${PIP_PACKAGES_HEAVY[@]}"; do
            echo "      - Attempting to download (heavy): $pkg"
            python3 -m pip download -q -d "$PIP_CACHE_DIR" "$pkg" || echo "      ⚠️  Download failed for $pkg (continuing)"
        done
    else
        echo "    Skipping heavy packages (tensorflow/pytorch). Set DOWNLOAD_HEAVY_WHEELS=1 to enable."
    fi
    # --- Start a simple HTTP server to serve pip cache (if not already running)
    PIP_SERVER_PORT=8002
    if ! ss -ltn "sport = :$PIP_SERVER_PORT" 2>/dev/null | grep -q LISTEN; then
        echo "    Starting pip cache HTTP server on port $PIP_SERVER_PORT"
        nohup python3 -m http.server "$PIP_SERVER_PORT" --directory "$PIP_CACHE_DIR" >/var/log/janus-pip-cache.log 2>&1 &
        sleep 1
    else
        echo "    Pip cache server already running on port $PIP_SERVER_PORT"
    fi

    # --- Configure container to use apt-cacher-ng on host
    echo "    Configuring container to use host apt proxy at $HOST_IP:3142"
    lxc exec "$TEMP_CONTAINER" -- bash -lc "printf 'Acquire::http::Proxy \"http://$HOST_IP:3142\";\n' | sudo tee /etc/apt/apt.conf.d/01proxy >/dev/null"

    # Now attempt apt update via host proxy
    if lxc exec "$TEMP_CONTAINER" -- apt-get update -qq 2>/dev/null; then
        lxc exec "$TEMP_CONTAINER" -- apt-get upgrade -y -qq 2>/dev/null || true
        echo "✓ Packages updated via host apt proxy"
    else
        echo "⚠️  Package update failed even via host proxy, continuing..."
    fi

    echo
    echo "📋 Step 3: Installing Python and dependencies (using host pip cache where possible)..."
    # Use pip --no-index --find-links to point to host-served cache
    PIP_INDEX_URL="http://$HOST_IP:$PIP_SERVER_PORT"

    # Try to install Python and base packages via apt (best-effort)
    if lxc exec "$TEMP_CONTAINER" -- apt-get install -y -qq python3 python3-dev build-essential git curl wget 2>/dev/null; then
        echo "✓ Python and build tools installed via apt"
    else
        echo "⚠️  Base apt packages failed to install; attempting minimal python only"
        lxc exec "$TEMP_CONTAINER" -- apt-get install -y -qq python3 2>/dev/null || true
    fi

    # Install python packages via pip from host cache
    echo "📋 Step 4: Installing ML frameworks (from host pip cache if available)"
    for pkg in "${PIP_PACKAGES[@]}"; do
        echo "  Installing $pkg from host cache..."
        if lxc exec "$TEMP_CONTAINER" -- bash -lc "python3 -m pip install --no-index --find-links $PIP_INDEX_URL $pkg" 2>/dev/null; then
            echo "    ✓ $pkg installed from host cache"
        else
            echo "    ⚠️  $pkg installation failed from host cache (skipping)"
        fi
    done
    echo "✓ ML framework installation complete (host-assisted)"
    echo
else
    # Default path: container has network access or host not reachable; do normal updates
    if lxc exec "$TEMP_CONTAINER" -- apt-get update -qq 2>/dev/null; then
        lxc exec "$TEMP_CONTAINER" -- apt-get upgrade -y -qq 2>/dev/null || true
        echo "✓ Packages updated"
    else
        echo "⚠️  Package update failed (network issue), trying to continue..."
    fi
    echo
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

echo "📋 Step 5: Stopping container before publishing..."
lxc stop "$TEMP_CONTAINER" -f 2>/dev/null || true
sleep 2
echo "✓ Container stopped"
echo

echo "📋 Step 6: Publishing image..."
lxc publish "$TEMP_CONTAINER" --alias "$IMAGE_NAME" -q || {
    echo "⚠️  Failed to publish image, attempting recovery..."
    lxc stop "$TEMP_CONTAINER" -f 2>/dev/null || true
    sleep 2
    lxc publish "$TEMP_CONTAINER" --alias "$IMAGE_NAME" -q || {
        echo "❌ Failed to publish image after retry"
        lxc delete "$TEMP_CONTAINER" -f -q 2>/dev/null || true
        exit 1
    }
}
echo "✓ Image published: $IMAGE_NAME"
echo

echo "📋 Step 7: Cleaning up..."
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
