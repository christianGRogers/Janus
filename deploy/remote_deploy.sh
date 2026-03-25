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
    if ! lxc image info janus-compute-node &>/dev/null 2>&1; then
        echo "▸ Creating LXD container image (this will take 10-15 minutes)..."
        bash deploy/setup-lxd-queue.sh || echo "⚠️  LXD image creation failed, continuing..."
    else
        echo "▸ LXD image 'janus-compute-node' already exists"
    fi
else
    echo "⚠️  LXD CLI not available, skipping container queue setup"
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
sudo systemctl restart "$SERVICE_NAME"

echo "▸ Deployment complete — service status:"
sudo systemctl status "$SERVICE_NAME" --no-pager || true

# ── Verify LXD queue is initializing ─────────────────────────────────────────
echo ""
echo "▸ Checking LXD container queue status..."
sleep 2
if sudo journalctl -u janus.service -n 10 2>/dev/null | grep -q "Container queue"; then
    echo "  ✓ LXD container queue initialized successfully"
else
    echo "  ℹ️  Container queue may be initializing or disabled"
fi

echo ""
echo "▸ To monitor container provisioning:"
echo "  watch lxc list"
echo ""
echo "▸ To follow logs:"
echo "  sudo journalctl -u janus.service --follow"
