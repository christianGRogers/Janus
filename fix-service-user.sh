#!/bin/bash
# Quick fix script for systemd error 217/USER
# Run on server: sudo bash fix-service-user.sh

set -e

echo "🔧 Fixing janus.service user/group issues..."
echo

# Step 1: Ensure janus user exists (with no special shell restrictions)
if ! id "janus" &>/dev/null 2>&1; then
    echo "1️⃣  Creating janus user..."
    useradd -m -s /bin/bash janus
    echo "   ✓ User created"
else
    echo "1️⃣  User janus already exists"
fi

# Step 2: Ensure home directory has correct permissions
echo "2️⃣  Verifying home directory..."
if [ ! -d /home/janus ]; then
    mkdir -p /home/janus
fi
chown janus:janus /home/janus
chmod 755 /home/janus
echo "   ✓ Home directory ready"

# Step 3: Ensure janus is in lxd group
echo "3️⃣  Adding to lxd group..."
if getent group lxd > /dev/null 2>&1; then
    usermod -a -G lxd janus
    echo "   ✓ Added to lxd group"
else
    echo "   ⚠️  lxd group not found (LXD may not be installed)"
fi

# Step 4: Fix directory ownership
echo "4️⃣  Fixing directory ownership..."
chown -R janus:janus /opt/janus/models
chown -R janus:janus /opt/janus/logs
chown janus:janus /opt/janus
echo "   ✓ Ownership fixed"

# Step 5: Fix LXD socket permissions
echo "5️⃣  Fixing LXD socket permissions..."
if [ -S /var/snap/lxd/common/lxd/unix.socket ]; then
    chmod 666 /var/snap/lxd/common/lxd/unix.socket 2>/dev/null || true
    echo "   ✓ Socket permissions updated"
else
    echo "   ⚠️  LXD socket not found"
fi

# Step 6: Reload systemd and restart
echo "6️⃣  Reloading systemd..."
systemctl daemon-reload
echo "   ✓ Daemon reloaded"

# Step 7: Start service
echo "7️⃣  Starting service..."
systemctl restart janus.service || true
sleep 3

# Step 8: Check status
echo "8️⃣  Checking service status..."
if systemctl is-active --quiet janus.service; then
    echo "   ✓ Service is RUNNING!"
    systemctl status janus.service --no-pager | head -10
else
    echo "   ✗ Service is still not running"
    echo "   Recent logs:"
    journalctl -u janus.service -n 10 --no-pager
fi

echo
echo "🔧 Fix complete!"
