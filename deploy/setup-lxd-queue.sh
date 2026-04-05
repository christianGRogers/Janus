#!/bin/bash
# deploy/setup-lxd-queue.sh (deprecated)
# This script was removed; image creation is intentionally manual or handled
# outside of the CI/CD pipeline. If you see references to this script they
# should be treated as informational only.

echo "Notice: deploy/setup-lxd-queue.sh has been deprecated and does nothing."
echo "If you need to create the 'from-instance-flying-oarfish' image, run the manual steps:"
echo "  lxc launch ubuntu:22.04 janus-setup-temp"
echo "  lxc exec janus-setup-temp -- apt-get update && apt-get install -y python3 python3-pip"
echo "  lxc stop janus-setup-temp"
echo "  lxc publish janus-setup-temp --alias from-instance-flying-oarfish"
echo "  lxc delete janus-setup-temp -f"

exit 0
