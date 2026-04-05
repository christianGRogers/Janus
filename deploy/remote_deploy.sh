#!/bin/bash
# deploy/remote_deploy.sh — Entry point for CI/CD deployments
# This script is called by GitHub Actions. It delegates to the unified deploy script.
set -euo pipefail

# Change to the deploy directory
cd "$(dirname "$0")" || exit 1

# Run the unified deployment script with sudo
sudo bash ./deploy.sh

