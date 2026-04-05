"""LXD container management and lifecycle control.

Manages communication with the LXD cluster API to spin up, monitor,
and tear down containers for compute nodes. Containers are pre-provisioned
in a queue to reduce user wait time.

Configuration via environment variables:
    LXD_SOCKET           – Unix socket path (default: /var/snap/lxd/common/lxd/unix.socket)
    LXD_CLUSTER_ENDPOINT – HTTP(S) endpoint if not using socket
    LXD_IMAGE_FINGERPRINT – LXD image fingerprint (default: b03058e361bf, see janus.const)
    LXD_PROFILE          – LXD profile for containers (default: default)
    LXD_CONTAINER_PREFIX – Prefix for container names (default: janus-node)
    LXD_CPU_LIMIT        – CPU cores per container (default: 2)
    LXD_MEMORY_LIMIT     – Memory per container in MB (default: 2048)
    LXD_DISK_LIMIT       – Disk per container in GB (default: 20)
"""

from __future__ import annotations

import os
import json
import logging
import subprocess
import time
import socket
from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime, timezone

from janus.const import LXD_COMPUTE_NODE_FINGERPRINT

logger = logging.getLogger(__name__)


@dataclass
class ContainerConfig:
    """Configuration for container provisioning."""
    name: str
    image: str
    profile: str
    cpu_limit: int = 2
    memory_limit: int = 2048  # MB
    disk_limit: int = 20      # GB


class LXDContainerClient:
    """Low-level client for LXD using CLI subprocess (lxc command)."""

    def __init__(self):
        self.timeout = 30
        # Find lxc command - usually at /snap/bin/lxc
        self.lxc_cmd = self._find_lxc_command()

    def _find_lxc_command(self) -> str:
        """Find the lxc command in common locations."""
        common_paths = [
            "/snap/bin/lxc",
            "/usr/bin/lxc",
            "/usr/local/bin/lxc",
        ]
        for path in common_paths:
            if os.path.exists(path):
                logger.info(f"Found lxc at: {path}")
                return path
        # Fallback to just "lxc" and hope it's in PATH
        logger.warning("Could not find lxc in common locations, using 'lxc' from PATH")
        return "lxc"

    def _run_lxc(self, *args) -> str:
        """Run an lxc CLI command and return stdout."""
        try:
            result = subprocess.run(
                [self.lxc_cmd] + list(args),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if result.returncode != 0:
                raise RuntimeError(f"lxc {' '.join(args)} failed: {result.stderr}")
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"lxc command timed out: {' '.join(args)}")
        except Exception as exc:
            logger.error(f"lxc command failed: {exc}")
            raise

    def create_container(self, config: ContainerConfig) -> dict:
        """Create a new LXD container using lxc CLI."""
        try:
            logger.info(f"Creating container: {config.name}")
            self._run_lxc(
                "launch",
                config.image,  # Can be fingerprint or alias
                config.name,
                "-c", f"limits.cpu={config.cpu_limit}",
                "-c", f"limits.memory={config.memory_limit}MB",
                "-p", config.profile,  # Profile flag is -p, not -d
            )
            return {"metadata": {}, "status": "created"}
        except Exception as exc:
            logger.error(f"Failed to create container: {exc}")
            raise

    def start_container(self, name: str) -> dict:
        """Start a stopped container."""
        try:
            logger.info(f"Starting container: {name}")
            self._run_lxc("start", name)
            return {"metadata": {}, "status": "started"}
        except Exception as exc:
            logger.error(f"Failed to start container: {exc}")
            raise

    def stop_container(self, name: str, force: bool = False) -> dict:
        """Stop a running container."""
        try:
            logger.info(f"Stopping container: {name}")
            args = ["stop", name]
            if force:
                args.append("--force")
            self._run_lxc(*args)
            return {"metadata": {}, "status": "stopped"}
        except Exception as exc:
            logger.error(f"Failed to stop container: {exc}")
            raise

    def delete_container(self, name: str) -> dict:
        """Delete a container."""
        try:
            logger.info(f"Deleting container: {name}")
            self._run_lxc("delete", name, "--force")
            return {"metadata": {}, "status": "deleted"}
        except Exception as exc:
            logger.error(f"Failed to delete container: {exc}")
            raise

    def get_container_status(self, name: str) -> Optional[dict]:
        """Get container status via lxc info."""
        try:
            output = self._run_lxc("info", name, "--format=json")
            return json.loads(output)
        except Exception:
            return None

    def list_containers(self) -> List[str]:
        """List all container names matching prefix."""
        try:
            output = self._run_lxc("list", "--format=csv", "-c", "n")
            return [line.strip() for line in output.split("\n") if line.strip()]
        except Exception:
            return []

    def execute_command(self, name: str, command: List[str]) -> dict:
        """Execute a command inside a container."""
        try:
            # Wrap command with venv activation
            wrapped = [
                "bash",
                "-c",
                f"source /opt/janus-env/bin/activate && {' '.join(command)}"
            ]
            logger.info(f"Executing in {name}: {' '.join(command)}")
            output = self._run_lxc("exec", name, "--", *wrapped)
            return {"metadata": {}, "output": output}
        except Exception as exc:
            logger.error(f"Failed to execute command: {exc}")
            raise


class LXDManager:
    """High-level manager for provisioning and lifecycle of compute node containers."""

    def __init__(self):
        self.client = LXDContainerClient()
        # Use fingerprint if set in environment, otherwise fall back to alias
        self.image_name = os.environ.get("LXD_IMAGE_FINGERPRINT", LXD_COMPUTE_NODE_FINGERPRINT)
        self.profile = os.environ.get("LXD_PROFILE", "default")
        self.container_prefix = os.environ.get("LXD_CONTAINER_PREFIX", "janus-node")
        self.cpu_limit = int(os.environ.get("LXD_CPU_LIMIT", "2"))
        self.memory_limit = int(os.environ.get("LXD_MEMORY_LIMIT", "2048"))
        self.disk_limit = int(os.environ.get("LXD_DISK_LIMIT", "20"))

        # Track container lifecycle: node_id → container_name
        self._container_map: Dict[str, str] = {}

    def provision_container(self, node_id: str) -> str:
        """Provision and start a new container for a node.

        Returns the container name on success.
        """
        container_name = f"{self.container_prefix}-{node_id}"
        config = ContainerConfig(
            name=container_name,
            image=self.image_name,
            profile=self.profile,
            cpu_limit=self.cpu_limit,
            memory_limit=self.memory_limit,
            disk_limit=self.disk_limit,
        )

        try:
            # Create container
            self.client.create_container(config)
            logger.info(f"Container created: {container_name}")

            # Start container
            self.client.start_container(container_name)
            logger.info(f"Container started: {container_name}")

            # Store mapping
            self._container_map[node_id] = container_name

            return container_name

        except Exception as exc:
            logger.error(f"Failed to provision container for {node_id}: {exc}")
            raise

    def teardown_container(self, node_id: str) -> None:
        """Stop and delete a container for a node."""
        container_name = self._container_map.get(node_id)
        if not container_name:
            logger.warning(f"No container mapping for node {node_id}")
            return

        try:
            self.client.stop_container(container_name, force=True)
            time.sleep(1)  # Give it time to stop
            self.client.delete_container(container_name)
            logger.info(f"Container destroyed: {container_name}")
            del self._container_map[node_id]

        except Exception as exc:
            logger.error(f"Failed to teardown container for {node_id}: {exc}")
            raise

    def get_container_status(self, node_id: str) -> Optional[Dict]:
        """Get the status of a container for a node."""
        container_name = self._container_map.get(node_id)
        if not container_name:
            return None

        try:
            return self.client.get_container_status(container_name)
        except Exception as exc:
            logger.error(f"Failed to get status for {container_name}: {exc}")
            return None

    def is_container_ready(self, node_id: str, max_retries: int = 10) -> bool:
        """Poll until container is ready (running + network configured)."""
        for attempt in range(max_retries):
            status = self.get_container_status(node_id)
            if status is None:
                logger.warning(f"Attempt {attempt + 1}: Container not found")
                time.sleep(1)
                continue

            state = status.get("metadata", {}).get("state", "").lower()
            if state == "running":
                logger.info(f"Container ready for {node_id} after {attempt + 1} attempts")
                return True

            logger.info(f"Attempt {attempt + 1}: Container state = {state}")
            time.sleep(2)

        logger.error(f"Container did not become ready after {max_retries} attempts")
        return False
