#!/bin/bash
# Complete Janus server setup from scratch
# Run as: sudo bash complete-server-setup.sh

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  Janus Complete Server Setup                               ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "❌ This script must be run with sudo"
    exit 1
fi

# Step 1: Create janus user
echo "📋 Step 1: Creating janus user..."
if ! id "janus" &>/dev/null 2>&1; then
    useradd -m -s /bin/bash janus
    echo "   ✓ User created"
else
    echo "   ✓ User already exists"
fi

# Step 2: Create directory structure
echo "📋 Step 2: Creating directory structure..."
mkdir -p /opt/janus/{app,models,logs,venv}
chown -R janus:janus /opt/janus
chmod -R 755 /opt/janus
echo "   ✓ Directories created"

# Step 3: Add janus to lxd group
echo "📋 Step 3: Setting up group membership..."
if getent group lxd > /dev/null 2>&1; then
    usermod -a -G lxd janus
    echo "   ✓ Added to lxd group"
else
    echo "   ⚠️  lxd group not found"
fi

# Step 4: Check prerequisites
echo "📋 Step 4: Checking prerequisites..."
for cmd in git python3; do
    if command -v $cmd &> /dev/null; then
        echo "   ✓ $cmd found"
    else
        echo "   ❌ $cmd not found - please install it"
        exit 1
    fi
done

# Step 5: Clone repository (if not already present)
echo "📋 Step 5: Cloning repository..."
if [ -d "/opt/janus/app/.git" ]; then
    echo "   ✓ Repository already exists, pulling latest..."
    cd /opt/janus/app
    sudo -u janus git pull origin main || git pull
else
    echo "   Cloning from GitHub..."
    sudo -u janus git clone https://github.com/christianGRogers/Janus.git /opt/janus/app
    echo "   ✓ Repository cloned"
fi

# Step 6: Create Python venv
echo "📋 Step 6: Setting up Python virtual environment..."
if [ ! -f /opt/janus/venv/bin/python3 ]; then
    sudo -u janus python3 -m venv /opt/janus/venv
    echo "   ✓ Venv created"
else
    echo "   ✓ Venv already exists"
fi

# Step 7: Upgrade pip and install dependencies
echo "📋 Step 7: Installing dependencies (this may take a few minutes)..."
sudo -u janus /opt/janus/venv/bin/pip install --upgrade pip setuptools wheel > /dev/null 2>&1
sudo -u janus /opt/janus/venv/bin/pip install -e /opt/janus/app > /dev/null 2>&1
sudo -u janus /opt/janus/venv/bin/pip install uvicorn[standard] > /dev/null 2>&1
echo "   ✓ Dependencies installed"

# Step 8: Install systemd service
echo "📋 Step 8: Installing systemd service..."
if [ -f "/opt/janus/app/deploy/janus-with-lxd.service" ]; then
    cp /opt/janus/app/deploy/janus-with-lxd.service /etc/systemd/system/janus.service
    echo "   ✓ Service file copied"
else
    echo "   ❌ Service file not found in repository"
    exit 1
fi

# Step 9: Fix LXD socket permissions
echo "📋 Step 9: Setting up LXD access..."
if [ -S /var/snap/lxd/common/lxd/unix.socket ]; then
    chmod 666 /var/snap/lxd/common/lxd/unix.socket
    echo "   ✓ LXD socket permissions set"
else
    echo "   ⚠️  LXD socket not found (LXD may not be initialized)"
fi

# Step 10: Reload systemd and enable service
echo "📋 Step 10: Enabling systemd service..."
systemctl daemon-reload
systemctl enable janus.service
echo "   ✓ Service enabled"

# Step 11: Start service
echo "📋 Step 11: Starting Janus service..."
systemctl start janus.service
sleep 3

# Step 12: Check status
echo "📋 Step 12: Checking service status..."
echo
if systemctl is-active --quiet janus.service; then
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║  ✅ SUCCESS! Janus service is RUNNING                      ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo
    systemctl status janus.service --no-pager | head -15
else
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║  ⚠️  Service failed to start                               ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo
    echo "Recent logs:"
    journalctl -u janus.service -n 20 --no-pager
fi

echo
echo "📝 Useful commands:"
echo "   View logs:          sudo journalctl -u janus.service -f"
echo "   Service status:     sudo systemctl status janus.service"
echo "   Restart service:    sudo systemctl restart janus.service"
echo "   View containers:    lxc list"
echo
