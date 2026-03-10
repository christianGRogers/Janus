#!/usr/bin/env bash
# deploy/remote_deploy.sh — Runs on the remote server during CI/CD.
# Called by the GitHub Actions workflow after the repo is rsync'd.
set -euo pipefail

APP_DIR="/home/christian/janus"
VENV_DIR="$APP_DIR/venv"
SERVICE_NAME="janus"

cd "$APP_DIR"

# ── Create / update virtualenv ────────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "▸ Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "▸ Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install .

# ── Install / reload systemd service ─────────────────────────────────────────
echo "▸ Installing systemd service..."
sudo cp deploy/janus.service /etc/systemd/system/janus.service
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "▸ Deployment complete — service status:"
sudo systemctl status "$SERVICE_NAME" --no-pager || true
