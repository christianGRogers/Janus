#!/usr/bin/env bash
set -euo pipefail

# deploy/migrate-to-opt-janus.sh
# Automate Option A: create 'janus' system user, copy app to /opt/janus, create venv,
# install the app, install systemd service and start it.

SOURCE_DIR="${SOURCE_DIR:-/home/christian/janus}"
TARGET_DIR="${TARGET_DIR:-/opt/janus}"
SERVICE_FILE_SOURCE="${SERVICE_FILE_SOURCE:-$SOURCE_DIR/deploy/janus-with-lxd.service}"
USER_NAME="janus"
GROUP_NAME="janus"
PYTHON="${PYTHON:-python3}"

echo "== Janus migration to $TARGET_DIR =="

if [ ! -d "$SOURCE_DIR" ]; then
  echo "ERROR: Source directory $SOURCE_DIR does not exist. Adjust SOURCE_DIR and retry."
  exit 1
fi

# Create system user if missing
if id -u "$USER_NAME" >/dev/null 2>&1; then
  echo "User $USER_NAME already exists"
else
  echo "Creating system user $USER_NAME with home $TARGET_DIR"
  sudo useradd --system --create-home --home-dir "$TARGET_DIR" --shell /usr/sbin/nologin "$USER_NAME"
fi

# Ensure target dir exists
echo "Creating target dir $TARGET_DIR and syncing files"
sudo mkdir -p "$TARGET_DIR"
# Use rsync to preserve permissions; requires rsync installed on host
if ! command -v rsync &>/dev/null; then
  echo "rsync not found; installing rsync (requires sudo)"
  sudo apt-get update -qq || true
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rsync || true
fi

sudo rsync -a --delete "$SOURCE_DIR"/ "$TARGET_DIR"/

# Fix ownership
echo "Setting ownership to $USER_NAME:$GROUP_NAME"
sudo chown -R "$USER_NAME":"$GROUP_NAME" "$TARGET_DIR"

# Create venv and install app
VENV="$TARGET_DIR/venv"
if [ -x "$VENV/bin/python" ]; then
  echo "Virtualenv already exists at $VENV"
else
  echo "Creating virtualenv at $VENV"
  sudo -u "$USER_NAME" $PYTHON -m venv "$VENV"
fi

echo "Upgrading pip and installing app into venv"
sudo -u "$USER_NAME" "$VENV/bin/pip" install --upgrade pip setuptools wheel || true
sudo -u "$USER_NAME" "$VENV/bin/pip" install --no-cache-dir "$TARGET_DIR" || true

# Ensure model and logs directories exist and are writable
sudo mkdir -p "$TARGET_DIR/models" "$TARGET_DIR/logs"
sudo chown -R "$USER_NAME":"$GROUP_NAME" "$TARGET_DIR/models" "$TARGET_DIR/logs"

# Install systemd unit file
if [ -f "$SERVICE_FILE_SOURCE" ]; then
  echo "Copying service file $SERVICE_FILE_SOURCE to /etc/systemd/system/janus.service"
  sudo cp "$SERVICE_FILE_SOURCE" /etc/systemd/system/janus.service
else
  echo "Warning: $SERVICE_FILE_SOURCE not found. Using deploy/janus.service if present"
  if [ -f "$SOURCE_DIR/deploy/janus.service" ]; then
    sudo cp "$SOURCE_DIR/deploy/janus.service" /etc/systemd/system/janus.service
  else
    echo "No service file found in repo. You must create /etc/systemd/system/janus.service manually."
  fi
fi

# Reload systemd and enable/start service
echo "Reloading systemd and enabling janus.service"
sudo systemctl daemon-reload
sudo systemctl enable janus.service || true

echo "Starting (or restarting) janus.service"
sudo systemctl restart janus.service || true

# Show recent logs
echo "---- service status ----"
sudo systemctl status janus.service --no-pager || true

echo "---- journal (last 100 lines) ----"
sudo journalctl -u janus.service -n 100 --no-pager || true

echo "Migration complete. If the service failed to start, inspect the journal output above and ensure the ExecStart path and permissions are correct."
