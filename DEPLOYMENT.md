# Janus Deployment Guide

## Overview

Janus uses a **unified deployment script** that handles all setup tasks consistently:
- User and directory creation
- Repository cloning/updating
- Python virtual environment setup
- LXD container queue configuration (optional)
- Systemd service installation and startup

## Deployment Methods

### Method 1: Automated (CI/CD via GitHub Actions)

The GitHub Actions workflow automatically runs the deployment script via SSH:

```bash
# In .github/workflows/deploy.yml:
- name: Deploy to server
  uses: appleboy/ssh-action@v1
  with:
    host: ${{ secrets.DEPLOY_HOST }}
    username: ${{ secrets.DEPLOY_USER }}
    key: ${{ secrets.DEPLOY_KEY }}
    script: |
      cd /path/to/janus
      sudo bash deploy/remote_deploy.sh
```

### Method 2: Manual Deployment

SSH to your server and run:

```bash
cd ~/janus  # or wherever the repo is cloned
sudo bash deploy/deploy.sh
```

## Installation Paths

The deployment script uses consistent paths:

- **App directory**: `/opt/janus`
- **Virtual environment**: `/opt/janus/venv`
- **Models directory**: `/opt/janus/models`
- **Logs directory**: `/opt/janus/logs`
- **Service file**: `/etc/systemd/system/janus.service`

## What Gets Installed

1. **User**: Creates `janus` system user if not present
2. **Repository**: Clones/updates from GitHub (main branch)
3. **Python venv**: Creates isolated Python environment at `/opt/janus/venv`
4. **Dependencies**: Installs janus package and all dependencies
5. **LXD support**: Configures LXD socket permissions (if available)
6. **Systemd service**: Installs and enables `janus.service`

## Verifying Deployment

After deployment, verify with:

```bash
# Check service status
sudo systemctl status janus.service

# View logs
sudo journalctl -u janus.service -f

# Test API
curl http://localhost:8000/health

# Monitor container queue
watch lxc list
```

## Troubleshooting

If the service fails to start:

```bash
# Check error status
sudo systemctl status janus.service

# View detailed logs (last 50 lines)
sudo journalctl -u janus.service -n 50

# Try manual start to see errors
sudo -u janus /opt/janus/venv/bin/python -m uvicorn janus.server.app:app --host 0.0.0.0 --port 8000
```

## LXD Container Queue (Optional)

The container queue requires:
1. LXD installed: `snap install lxd`
2. LXD image with fingerprint `b03058e361bf`

To create the image manually:

```bash
lxc launch ubuntu:22.04 janus-setup-temp
lxc exec janus-setup-temp -- bash << 'EOF'
  apt-get update
  apt-get install -y python3 python3-pip
  python3 -m pip install -q tensorflow numpy
EOF
lxc stop janus-setup-temp
lxc publish janus-setup-temp --alias from-instance-flying-oarfish
lxc delete janus-setup-temp -f
```

See `deploy/test-lxd-setup.sh` for a complete example.

## Configuration

All paths and settings can be customized by editing `deploy/deploy.sh`:

```bash
APP_DIR="/opt/janus"          # Change app location
VENV_DIR="$APP_DIR/venv"      # Venv location
GITHUB_REPO="..."             # Change Git repo
LXD_IMAGE_FINGERPRINT="..."   # Change LXD image
```

## Debugging

For debugging deployment issues, the script provides:
- Detailed output with visual separators
- Pre-flight checks (python3, git, permissions)
- Clear error messages with remediation steps
- Verification at each step

Enable verbose output:

```bash
sudo bash -x deploy/deploy.sh
```

## Key Design Decisions

1. **Single script**: All setup tasks in one place, eliminating path mismatches
2. **Consistent paths**: App, venv, and service all reference `/opt/janus`
3. **User isolation**: All app operations run as `janus` user, not root
4. **LXD optional**: Works without LXD; container queue is a bonus feature
5. **Idempotent**: Can be run multiple times safely (won't break existing setup)
