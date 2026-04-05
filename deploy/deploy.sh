#!/bin/bash
# deploy/deploy.sh — Complete, unified Janus deployment
# This is the ONLY script needed. All paths are consistent.
# Run on target server as: sudo bash deploy.sh

set -euo pipefail

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION - All paths defined here
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

APP_DIR="/opt/janus"
VENV_DIR="$APP_DIR/venv"
SERVICE_NAME="janus"
GITHUB_REPO="https://github.com/christianGRogers/Janus.git"
LXD_IMAGE_FINGERPRINT="b03058e361bf"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPER FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

die() {
    echo "❌ ERROR: $1" >&2
    exit 1
}

step() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "▶ $1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. PRE-FLIGHT CHECKS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

step "Pre-flight checks"

[ "$EUID" -eq 0 ] || die "Must run with sudo"
command -v python3 >/dev/null || die "python3 not found"
command -v git >/dev/null || die "git not found"

echo "✓ Running as root"
echo "✓ Python 3 available: $(python3 --version)"
echo "✓ Git available: $(git --version)"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. CREATE USER AND DIRECTORIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

step "Creating user and directories"

# Create janus user if needed
if ! id janus &>/dev/null; then
    useradd -m -s /bin/bash janus
    echo "✓ Created user: janus"
else
    echo "✓ User janus already exists"
fi

# Create app directory structure
mkdir -p "$APP_DIR" "$APP_DIR/models" "$APP_DIR/logs"
chown -R janus:janus "$APP_DIR"
chmod 755 "$APP_DIR"
echo "✓ Created directories: $APP_DIR"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. CLONE/UPDATE REPOSITORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

step "Setting up repository"

if [ -d "$APP_DIR/.git" ]; then
    echo "✓ Repository already exists, updating..."
    cd "$APP_DIR"
    sudo -u janus git fetch origin
    sudo -u janus git reset --hard origin/main
else
    echo "✓ Cloning repository..."
    sudo -u janus git clone "$GITHUB_REPO" "$APP_DIR"
fi

cd "$APP_DIR"
echo "✓ Repository ready at: $APP_DIR"
git log -1 --oneline | sed 's/^/  /'

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. CREATE AND CONFIGURE VIRTUAL ENVIRONMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

step "Setting up Python virtual environment"

if [ ! -d "$VENV_DIR" ]; then
    echo "  Creating venv..."
    sudo -u janus python3 -m venv "$VENV_DIR"
else
    echo "  ✓ Venv already exists"
fi

# Ensure proper permissions
chown -R janus:janus "$VENV_DIR"
chmod 755 "$VENV_DIR"

# Upgrade pip
echo "  Upgrading pip..."
sudo -u janus "$VENV_DIR/bin/python" -m pip install -q --upgrade pip setuptools wheel

# Install janus package and dependencies
echo "  Installing janus package..."
sudo -u janus "$VENV_DIR/bin/pip" install -q -e "$APP_DIR"

# Verify installation
if "$VENV_DIR/bin/python" -c "import janus; print(f'Janus {janus.__version__ if hasattr(janus, \"__version__\") else \"package\"} installed')"; then
    echo "✓ Virtual environment ready at: $VENV_DIR"
else
    die "Failed to verify janus package installation"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. CONFIGURE LXD (Optional but recommended)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

step "Configuring LXD (container queue)"

if ! command -v lxc &>/dev/null; then
    echo "⚠ LXD not installed. Install with: snap install lxd"
    echo "  Continuing without container queue support."
else
    # Add janus to lxd group
    usermod -a -G lxd janus 2>/dev/null || true
    
    # Check if image exists
    if lxc image info "$LXD_IMAGE_FINGERPRINT" &>/dev/null; then
        echo "✓ LXD image exists: $LXD_IMAGE_FINGERPRINT"
    else
        echo "⚠ LXD image not found: $LXD_IMAGE_FINGERPRINT"
        echo "  The container queue will be disabled until the image is available."
        echo "  To create the image, see: deploy/test-lxd-setup.sh"
    fi
    
    # Ensure socket is accessible
    if [ -S /var/snap/lxd/common/lxd/unix.socket ]; then
        chmod 666 /var/snap/lxd/common/lxd/unix.socket
        echo "✓ LXD socket configured"
    fi
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. INSTALL SYSTEMD SERVICE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

step "Installing systemd service"

# Copy service file
cp "$APP_DIR/deploy/janus-with-lxd.service" /etc/systemd/system/janus.service
systemctl daemon-reload
systemctl enable janus.service
echo "✓ Service installed: /etc/systemd/system/janus.service"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. START SERVICE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

step "Starting service"

systemctl restart janus.service
sleep 2

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. VERIFY DEPLOYMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

step "Verifying deployment"

if systemctl is-active --quiet janus.service; then
    echo "✅ Service is RUNNING"
    echo ""
    systemctl status janus.service --no-pager | head -10
else
    echo "❌ Service FAILED to start"
    echo ""
    systemctl status janus.service --no-pager || true
    echo ""
    echo "Recent logs:"
    journalctl -u janus.service -n 20 --no-pager || true
    exit 1
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 9. SUMMARY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

step "Deployment complete"

echo ""
echo "📍 Installation paths:"
echo "   App:     $APP_DIR"
echo "   Venv:    $VENV_DIR"
echo "   Service: /etc/systemd/system/janus.service"
echo ""
echo "🔍 Verification commands:"
echo "   systemctl status janus.service"
echo "   journalctl -u janus.service -f"
echo "   curl http://localhost:8000/health"
echo ""
echo "🐳 Container queue:"
echo "   watch lxc list"
echo ""
echo "✅ Janus is ready for inference!"
echo ""
