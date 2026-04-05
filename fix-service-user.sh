#!/bin/bash
# Quick fix script for systemd error 217/USER
# Run on server: sudo bash fix-service-user.sh

set -e

echo "🔧 Fixing janus.service user/group issues..."
echo

# Step 1: Ensure janus user exists
if ! id "janus" &>/dev/null 2>&1; then
    echo "1️⃣  Creating janus user..."
    useradd -m -s /bin/bash -G lxd janus
    echo "   ✓ User created"
else
    echo "1️⃣  User janus already exists"
    echo "   ✓ Skipped"
fi

# Step 2: Ensure home directory
echo "2️⃣  Verifying home directory..."
if [ ! -d /home/janus ]; then
    mkdir -p /home/janus
fi
chown janus:janus /home/janus
chmod 750 /home/janus
echo "   ✓ Home directory setup"

# Step 3: Ensure in lxd group
echo "3️⃣  Adding to lxd group..."
usermod -a -G lxd janus
echo "   ✓ Group membership updated"

# Step 4: Fix directory ownership
echo "4️⃣  Fixing directory ownership..."
chown -R janus:janus /opt/janus/models
chown -R janus:janus /opt/janus/logs
echo "   ✓ Ownership fixed"

# Step 5: Reload systemd and restart
echo "5️⃣  Reloading systemd..."
systemctl daemon-reload
echo "   ✓ Daemon reloaded"

# Step 6: Start service
echo "6️⃣  Starting service..."
systemctl restart janus.service
sleep 2

# Step 7: Check status
echo "7️⃣  Checking service status..."
if systemctl is-active --quiet janus.service; then
    echo "   ✓ Service is RUNNING!"
else
    echo "   ✗ Service is still not running"
    echo "   Check logs with: journalctl -u janus.service -n 50"
fi

echo
echo "🔧 Fix complete!"
