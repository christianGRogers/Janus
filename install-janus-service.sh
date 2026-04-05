#!/bin/bash
# One-command setup script for Janus with LXD container queue
# Run on Linux server: bash install-janus-service.sh

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  Janus Server Permanent Installation                       ║"
echo "║  (with LXD Container Queue)                                ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "❌ This script must be run with sudo"
    echo "   Run: sudo bash install-janus-service.sh"
    exit 1
fi

# Step 1: Prerequisites
echo "📋 Step 1: Checking prerequisites..."
echo "─────────────────────────────────────────────────────────────"

if ! command -v lxc &> /dev/null; then
    echo "❌ LXD CLI not found. Install with: snap install lxd"
    exit 1
fi
echo "✓ LXD CLI found"

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found"
    exit 1
fi
echo "✓ Python 3 found"

if ! command -v git &> /dev/null; then
    echo "❌ Git not found. Install with: apt install git"
    exit 1
fi
echo "✓ Git found"

echo

# Step 2: Create janus user
echo "📋 Step 2: Creating janus user..."
echo "─────────────────────────────────────────────────────────────"

if ! id "janus" &>/dev/null 2>&1; then
    useradd -m -s /bin/bash -G lxd janus
    echo "✓ User 'janus' created"
else
    echo "✓ User 'janus' already exists"
    # Ensure janus is in lxd group
    usermod -a -G lxd janus
    echo "✓ User added to lxd group"
fi

echo

# Step 3: Create directories
echo "📋 Step 3: Creating application directories..."
echo "─────────────────────────────────────────────────────────────"

mkdir -p /opt/janus/models
mkdir -p /opt/janus/logs
mkdir -p /opt/janus/venv
chown -R janus:janus /opt/janus
chmod -R 755 /opt/janus
echo "✓ Directories created"

echo

# Step 4: Clone repository
echo "📋 Step 4: Cloning Janus repository..."
echo "─────────────────────────────────────────────────────────────"

if [ -d "/opt/janus/app" ]; then
    echo "⚠️  /opt/janus/app already exists, skipping clone"
    echo "    To update: cd /opt/janus/app && git pull"
else
    sudo -u janus git clone https://github.com/christianGRogers/Janus.git /opt/janus/app
    echo "✓ Repository cloned"
fi

echo

# Step 5: Set up Python virtual environment
echo "📋 Step 5: Setting up Python virtual environment..."
echo "─────────────────────────────────────────────────────────────"

sudo -u janus python3 -m venv /opt/janus/venv
sudo -u janus /opt/janus/venv/bin/pip install --upgrade pip setuptools wheel
echo "✓ Virtual environment created"

# Install dependencies
echo "  Installing dependencies (this may take a while)..."
sudo -u janus /opt/janus/venv/bin/pip install -e /opt/janus/app
sudo -u janus /opt/janus/venv/bin/pip install uvicorn[standard]
echo "✓ Dependencies installed"

echo

# Step 6: Prepare LXD image
echo "📋 Step 6: Preparing LXD image..."
echo "─────────────────────────────────────────────────────────────"

if lxc image info from-instance-flying-oarfish &>/dev/null 2>&1; then
    echo "✓ Image 'from-instance-flying-oarfish' already exists"
else
    echo "  Creating image (this will take 5-10 minutes)..."
    sudo -u janus bash /opt/janus/app/deploy/setup-lxd-queue.sh
    
    if lxc image info from-instance-flying-oarfish &>/dev/null 2>&1; then
        echo "✓ Image created successfully"
    else
        echo "⚠️  Image creation may have failed. Check manually:"
        echo "    bash /opt/janus/app/deploy/setup-lxd-queue.sh"
    fi
fi

echo

# Step 7: Install systemd service
echo "📋 Step 7: Installing systemd service..."
echo "─────────────────────────────────────────────────────────────"

cp /opt/janus/app/deploy/janus-with-lxd.service /etc/systemd/system/janus.service

# Update paths in service file to match actual installation
sed -i 's|/opt/janus|/opt/janus|g' /etc/systemd/system/janus.service

systemctl daemon-reload
systemctl enable janus.service
echo "✓ Service installed and enabled"

echo

# Step 8: Start service
echo "📋 Step 8: Starting Janus service..."
echo "─────────────────────────────────────────────────────────────"

systemctl start janus.service

# Wait for service to start
sleep 2

if systemctl is-active --quiet janus.service; then
    echo "✓ Service started successfully"
else
    echo "⚠️  Service may have failed to start"
    echo "    Check logs: sudo journalctl -u janus.service"
fi

echo

# Step 9: Summary
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  Installation Complete! ✓                                  ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo

echo "📊 Service Status:"
systemctl status janus.service --no-pager

echo
echo "📝 Useful Commands:"
echo "─────────────────────────────────────────────────────────────"
echo "  View logs:           sudo journalctl -u janus.service -f"
echo "  Service status:      sudo systemctl status janus.service"
echo "  Restart service:     sudo systemctl restart janus.service"
echo "  Stop service:        sudo systemctl stop janus.service"
echo "  View containers:     lxc list | grep janus"
echo

echo "🚀 Next Steps:"
echo "─────────────────────────────────────────────────────────────"
echo "  1. Wait for LXD containers to provision (watch with: watch lxc list)"
echo "  2. Test with: python login_and_register_node.py user@example.com password https://janus.bradensbay.com"
echo "  3. Monitor: sudo journalctl -u janus.service --follow"
echo

echo "📖 Documentation:"
echo "─────────────────────────────────────────────────────────────"
echo "  Full setup guide:    /opt/janus/app/PERMANENT_SETUP.md"
echo "  Troubleshooting:     /opt/janus/app/TROUBLESHOOTING_LXD_QUEUE.md"
echo

echo "✓ Installation finished!"
