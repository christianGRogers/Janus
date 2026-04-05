#!/usr/bin/env bash
# deploy/remote_deploy.sh — Runs on the remote server during CI/CD.
# Called by the GitHub Actions workflow after the repo is rsync'd.
set -euo pipefail

APP_DIR="/home/christian/janus"
VENV_DIR="$APP_DIR/venv"
SERVICE_NAME="janus"

cd "$APP_DIR"

# ── Create / update virtualenv ────────────────────────────────────────────────
if [ ! -x "$VENV_DIR/bin/python" ] || ! "$VENV_DIR/bin/python" -m pip --version &>/dev/null; then
    echo "▸ Creating virtual environment..."
    rm -rf "$VENV_DIR"
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m ensurepip --upgrade
fi

echo "▸ Upgrading pip..."
"$VENV_DIR/bin/python" -m pip install --upgrade pip

echo "▸ Installing dependencies..."
"$VENV_DIR/bin/pip" install .

# ── Prepare LXD image (one-time setup) ──────────────────────────────────────
# Check if LXD is available and image doesn't exist
if command -v lxc &>/dev/null; then
    echo "▸ Checking LXD configuration..."
    
    # Check if LXD has been initialized
    if ! lxc network list &>/dev/null 2>&1; then
        echo "⚠️  LXD is installed but not initialized"
        echo "   Initializing LXD with default configuration..."
        echo "" | sudo lxd init --auto 2>/dev/null || {
            echo "   LXD auto-init failed. Manual init may be needed:"
            echo "   sudo lxd init --auto"
        }
        sleep 2
    fi
    
    if ! lxc image info from-instance-flying-oarfish &>/dev/null 2>&1; then
        echo "⚠️  LXD image 'from-instance-flying-oarfish' not found. This deployment assumes the image already exists."
        echo "    Manual image creation steps (run on host):"
        echo "      lxc launch ubuntu:22.04 janus-setup-temp"
        echo "      lxc exec janus-setup-temp -- apt-get update && apt-get install -y python3 python3-pip"
        echo "      lxc stop janus-setup-temp"
        echo "      lxc publish janus-setup-temp --alias from-instance-flying-oarfish"
        echo "      lxc delete janus-setup-temp -f"
        echo "    Continuing deployment without automatic image creation."
    else
        echo "▸ LXD image 'from-instance-flying-oarfish' already exists"
    fi
else
    echo "⚠️  LXD CLI not available, skipping container queue setup"
    echo "   Install LXD with: sudo snap install lxd"
    echo "   Then initialize: lxd init --auto"
fi

# ── Install / reload systemd service ─────────────────────────────────────────
echo "▸ Installing systemd service (with LXD container queue support)..."

# Use LXD-enabled service file if available, otherwise use standard
if [ -f "deploy/janus-with-lxd.service" ]; then
    sudo cp deploy/janus-with-lxd.service /etc/systemd/system/janus.service
    echo "  ✓ Using LXD-enabled service configuration"
else
    sudo cp deploy/janus.service /etc/systemd/system/janus.service
    echo "  ✓ Using standard service configuration"
fi

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

# Restart service, but continue if it fails (might need reboot or manual fix)
if sudo systemctl restart "$SERVICE_NAME" 2>&1; then
    echo "  ✓ Service restarted successfully"
else
    # Service might have failed to start due to LXD not being available
    echo "  ⚠️  Service restart had issues, but this may be expected if LXD is not available"
    echo "     The service is still enabled and will start on next boot"
fi

echo ""
echo "▸ Deployment complete — service status:"
sudo systemctl status "$SERVICE_NAME" --no-pager || echo "  ⚠️  Service status check failed"

# ── Verify LXD queue is initializing ─────────────────────────────────────────
echo ""
echo "▸ Checking LXD container queue status..."
sleep 2

# Check if service is running
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "  ✓ Service is running"
    
    if sudo journalctl -u janus.service -n 10 2>/dev/null | grep -q "Container queue"; then
        echo "  ✓ LXD container queue initialized successfully"
    else
        echo "  ℹ️  Container queue may be initializing or disabled"
    fi
else
    echo "  ⚠️  Service is not running. Check with:"
    echo "     sudo systemctl status janus.service"
    echo "     sudo journalctl -u janus.service -n 50"
fi

echo ""
echo "▸ To monitor container provisioning:"
echo "  watch lxc list"
echo ""
echo "▸ To follow logs:"
echo "  sudo journalctl -u janus.service --follow"
echo ""
echo "▸ If service failed to start, you may need to:"
echo "  1. Ensure LXD is installed: snap install lxd"
echo "  2. Create the LXD image manually (see deploy/test-lxd-setup.sh for guidance)"
echo "     Example manual steps:"
echo "       lxc launch ubuntu:22.04 janus-setup-temp"
echo "       lxc exec janus-setup-temp -- apt-get update && apt-get install -y python3 python3-pip"
echo "       lxc stop janus-setup-temp"
echo "       lxc publish janus-setup-temp --alias from-instance-flying-oarfish"
echo "       lxc delete janus-setup-temp -f"
echo "  3. Restart service: sudo systemctl restart janus.service"
