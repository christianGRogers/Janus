"""LXD container management and lifecycle control.

Manages communication with the LXD cluster API to spin up, monitor,
and tear down containers for compute nodes. Containers are pre-provisioned
in a queue to reduce user wait time.

Configuration via environment variables:
    LXD_SOCKET           – Unix socket path (default: /var/snap/lxd/common/lxd/unix.socket)
    LXD_CLUSTER_ENDPOINT – HTTP(S) endpoint if not using socket
    LXD_IMAGE_NAME       – LXD image alias to use (default: janus-compute-node)
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
    """Low-level client for LXD REST API (socket or HTTP)."""

    def __init__(self):
        self.socket_path = os.environ.get(
            "LXD_SOCKET",
            "/var/snap/lxd/common/lxd/unix.socket"
        )
        self.http_endpoint = os.environ.get("LXD_CLUSTER_ENDPOINT")
        self.use_socket = not self.http_endpoint
        self.timeout = 30

    def _make_request(self, method: str, path: str, data: Optional[dict] = None) -> dict:
        """Make a request to LXD API via socket or HTTP."""
        if self.use_socket:
            return self._socket_request(method, path, data)
        else:
            return self._http_request(method, path, data)

    def _socket_request(self, method: str, path: str, data: Optional[dict] = None) -> dict:
        """Send request via Unix socket."""
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.socket_path)
            sock.settimeout(self.timeout)

            # Build HTTP-style request
            body = json.dumps(data) if data else ""
            headers = f"Host: localhost\r\nContent-Type: application/json\r\n"
            if body:
                headers += f"Content-Length: {len(body)}\r\n"
            request = f"{method} {path} HTTP/1.1\r\n{headers}\r\n{body}"

            sock.sendall(request.encode())
            response = sock.recv(65536).decode()
            sock.close()

            # Parse HTTP response
            parts = response.split("\r\n\r\n", 1)
            body_text = parts[1] if len(parts) > 1 else ""
            return json.loads(body_text) if body_text else {}

        except Exception as exc:
            logger.error(f"LXD socket request failed: {exc}")
            raise

    def _http_request(self, method: str, path: str, data: Optional[dict] = None) -> dict:
        """Send request via HTTP(S) endpoint."""
        try:
            import requests
            url = f"{self.http_endpoint}{path}"
            headers = {"Content-Type": "application/json"}
            
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=self.timeout)
            elif method == "POST":
                resp = requests.post(url, json=data, headers=headers, timeout=self.timeout)
            elif method == "DELETE":
                resp = requests.delete(url, headers=headers, timeout=self.timeout)
            else:
                raise ValueError(f"Unsupported method: {method}")

            resp.raise_for_status()
            return resp.json()

        except Exception as exc:
            logger.error(f"LXD HTTP request failed: {exc}")
            raise

    def create_container(self, config: ContainerConfig) -> dict:
        """Create a new LXD container."""
        payload = {
            "name": config.name,
            "source": {"type": "image", "alias": config.image},
            "profiles": [config.profile],
            "config": {
                "limits.cpu": str(config.cpu_limit),
                "limits.memory": f"{config.memory_limit}MB",
                "root.size": f"{config.disk_limit}GB",
            },
        }
        logger.info(f"Creating container: {config.name}")
        return self._make_request("POST", "/1.0/containers", payload)

    def start_container(self, name: str) -> dict:
        """Start a stopped container."""
        payload = {"action": "start", "timeout": 30}
        logger.info(f"Starting container: {name}")
        return self._make_request("POST", f"/1.0/containers/{name}/state", payload)

    def stop_container(self, name: str, force: bool = False) -> dict:
        """Stop a running container."""
        payload = {"action": "stop", "timeout": 30, "force": force}
        logger.info(f"Stopping container: {name}")
        return self._make_request("POST", f"/1.0/containers/{name}/state", payload)

    def delete_container(self, name: str) -> dict:
        """Delete a container."""
        logger.info(f"Deleting container: {name}")
        return self._make_request("DELETE", f"/1.0/containers/{name}")

    def get_container_status(self, name: str) -> dict:
        """Get container status and metadata."""
        return self._make_request("GET", f"/1.0/containers/{name}")

    def list_containers(self) -> List[str]:
        """List all container names."""
        result = self._make_request("GET", "/1.0/containers")
        # Result typically: {"metadata": ["/1.0/containers/name1", "/1.0/containers/name2"]}
        metadata = result.get("metadata", [])
        return [path.split("/")[-1] for path in metadata]

    def execute_command(self, name: str, command: List[str]) -> dict:
        """Execute a command inside a container."""
        payload = {
            "command": command,
            "wait-for-websocket": False,
            "interactive": False,
        }
        logger.info(f"Executing in {name}: {' '.join(command)}")
        return self._make_request("POST", f"/1.0/containers/{name}/exec", payload)


class LXDManager:
    """High-level manager for provisioning and lifecycle of compute node containers."""

    def __init__(self):
        self.client = LXDContainerClient()
        self.image_name = os.environ.get("LXD_IMAGE_NAME", "janus-compute-node")
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
