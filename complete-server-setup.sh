#!/bin/bash
# Minimal Janus server setup with LXD container queue
# Run as: sudo bash complete-server-setup.sh

set -e

# Ensure root
[ "$EUID" -eq 0 ] || { echo "❌ Run with sudo"; exit 1; }

echo "� Setting up Janus with LXD container queue..."

# 1. User and permissions
id janus &>/dev/null || useradd -m -s /bin/bash janus
usermod -a -G lxd janus 2>/dev/null || true

# 2. Directories
mkdir -p /opt/janus/{app,models,logs,venv}
chown -R janus:janus /opt/janus

# 3. Repository
if [ ! -d "/opt/janus/app/.git" ]; then
    sudo -u janus git clone https://github.com/christianGRogers/Janus.git /opt/janus/app
fi

# 4. Python venv and dependencies
if [ ! -f /opt/janus/venv/bin/python3 ]; then
    sudo -u janus python3 -m venv /opt/janus/venv
    sudo -u janus /opt/janus/venv/bin/pip install -q --upgrade pip setuptools wheel
    sudo -u janus /opt/janus/venv/bin/pip install -q -e /opt/janus/app uvicorn[standard]
fi

# 5. Systemd service
cp /opt/janus/app/deploy/janus-with-lxd.service /etc/systemd/system/janus.service
systemctl daemon-reload
systemctl enable janus.service

# 6. LXD socket permissions
chmod 666 /var/snap/lxd/common/lxd/unix.socket 2>/dev/null || true

# 7. Start
systemctl restart janus.service
sleep 2

# 8. Status
if systemctl is-active --quiet janus.service; then
    echo "✅ Janus is running with LXD container queue"
    echo "   View logs: sudo journalctl -u janus.service -f"
else
    echo "❌ Service failed to start"
    journalctl -u janus.service -n 20 --no-pager
fi
