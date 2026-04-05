#!/bin/bash
# Diagnostic script for janus.service startup issues
# Run on server: sudo bash diagnose-service.sh

echo "═════════════════════════════════════════════════════════════"
echo "  Janus Service Diagnostic Script"
echo "═════════════════════════════════════════════════════════════"
echo

echo "1️⃣  Checking user and home directory..."
if id janus &>/dev/null; then
    echo "   ✓ User 'janus' exists"
    echo "     $(id janus)"
else
    echo "   ✗ User 'janus' does NOT exist"
    exit 1
fi

echo
echo "2️⃣  Checking home directory..."
if [ -d /home/janus ]; then
    echo "   ✓ Home directory exists"
    ls -ld /home/janus
else
    echo "   ✗ Home directory does NOT exist"
    echo "     Create with: mkdir -p /home/janus && chown janus:janus /home/janus"
fi

echo
echo "3️⃣  Checking app directory..."
if [ -d /opt/janus/app ]; then
    echo "   ✓ App directory exists"
    echo "     Permissions: $(ls -ld /opt/janus/app)"
else
    echo "   ✗ App directory does NOT exist"
    exit 1
fi

echo
echo "4️⃣  Checking venv..."
if [ -d /opt/janus/venv ]; then
    echo "   ✓ Venv directory exists"
    if [ -f /opt/janus/venv/bin/python3 ]; then
        echo "   ✓ Python executable found"
    else
        echo "   ✗ Python executable NOT found in venv"
    fi
else
    echo "   ✗ Venv directory does NOT exist"
    exit 1
fi

echo
echo "5️⃣  Checking if janus can run uvicorn..."
echo "   Testing: sudo -u janus /opt/janus/venv/bin/python3 --version"
if sudo -u janus /opt/janus/venv/bin/python3 --version 2>/dev/null; then
    echo "   ✓ janus user can run Python"
else
    echo "   ✗ janus user CANNOT run Python"
fi

echo
echo "6️⃣  Checking groups..."
echo "   janus groups: $(groups janus | tr ' ' '\n')"
if groups janus | grep -q lxd; then
    echo "   ✓ janus is in lxd group"
else
    echo "   ⚠️  janus is NOT in lxd group"
    echo "     Fix with: usermod -a -G lxd janus"
fi

echo
echo "7️⃣  Checking LXD socket..."
if [ -S /var/snap/lxd/common/lxd/unix.socket ]; then
    echo "   ✓ LXD socket exists"
    echo "     Permissions: $(ls -la /var/snap/lxd/common/lxd/unix.socket | awk '{print $1, $3, $4}')"
else
    echo "   ⚠️  LXD socket NOT found"
fi

echo
echo "8️⃣  Checking service file..."
if [ -f /etc/systemd/system/janus.service ]; then
    echo "   ✓ Service file exists"
    echo "   User: $(grep '^User=' /etc/systemd/system/janus.service)"
    echo "   Group: $(grep '^Group=' /etc/systemd/system/janus.service)"
    echo "   SupplementaryGroups: $(grep '^SupplementaryGroups=' /etc/systemd/system/janus.service)"
else
    echo "   ✗ Service file NOT found"
fi

echo
echo "9️⃣  Attempting manual start (for 5 seconds)..."
echo "   Running: sudo -u janus /opt/janus/venv/bin/uvicorn janus.server.app:app --host 0.0.0.0 --port 8000 &"
timeout 5 sudo -u janus /opt/janus/venv/bin/uvicorn janus.server.app:app --host 0.0.0.0 --port 8000 &
PID=$!
sleep 2
if ps -p $PID > /dev/null 2>&1; then
    echo "   ✓ Uvicorn started successfully!"
    kill $PID 2>/dev/null
    wait $PID 2>/dev/null
else
    echo "   ✗ Uvicorn failed to start"
fi

echo
echo "═════════════════════════════════════════════════════════════"
echo "  Diagnostic Complete"
echo "═════════════════════════════════════════════════════════════"
